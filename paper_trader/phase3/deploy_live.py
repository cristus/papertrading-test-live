"""Deploy 7-day live paper run."""
import sys, os, json, time
from datetime import datetime
sys.path.insert(0, ".")

from core import db
from core.agent import AgentState, LifecycleChecker
from core.broker import PaperBroker, Economics, MarketRules
from core.safety import RiskConfig, EmergencyPause
from phase3.watchdog import TelegramNotifier, alert_milestone
from phase3.strategies import build_strategy
import yaml

print("=" * 80)
print("PHASE 3: LIVE DEPLOYMENT — 7-DAY CONTINUOUS RUN")
print("=" * 80)

tg_cfg = yaml.safe_load(open("config/telegram.yaml"))
notifier = TelegramNotifier(tg_cfg["bot_token"], tg_cfg["chat_id"]) if tg_cfg.get("enabled") else None

db_path = "data/phase3_exp.sqlite"
conn = db.connect(db_path)

print("\n[STEP 1] Spawn agents")

exp_row = conn.execute(
    "INSERT INTO experiments (start_ts, code_version, config_json, random_seed, market, strategy_name, strategy_params) "
    "VALUES (?,?,?,?,?,?,?)",
    (int(time.time()*1000), "phase3.0", json.dumps({}), 42, "MULTI", "survivor_baseline_blend", "{}")
)
conn.commit()
exp_id = exp_row.lastrowid

agents = []

# Survivor 1: SMA(20,100) on ETHINR
a1 = conn.execute(
    "INSERT INTO agents (experiment_id, cohort, starting_capital, birth_ts) VALUES (?,?,?,?)",
    (exp_id, "survivor_sma_ethinr", 8000.0, int(time.time()*1000))
)
agents.append(AgentState(id=a1.lastrowid, experiment_id=exp_id, cohort="survivor_sma_ethinr",
                         starting_capital=8000.0, cash=8000.0, position_qty=0.0, avg_entry_price=None))

a2 = conn.execute(
    "INSERT INTO agents (experiment_id, cohort, starting_capital, birth_ts) VALUES (?,?,?,?)",
    (exp_id, "survivor_ema_ethinr", 8000.0, int(time.time()*1000))
)
agents.append(AgentState(id=a2.lastrowid, experiment_id=exp_id, cohort="survivor_ema_ethinr",
                         starting_capital=8000.0, cash=8000.0, position_qty=0.0, avg_entry_price=None))

for market in ["BTCINR", "ETHINR", "XRPINR"]:
    a = conn.execute(
        "INSERT INTO agents (experiment_id, cohort, starting_capital, birth_ts) VALUES (?,?,?,?)",
        (exp_id, f"baseline_sma_{market}", 8000.0, int(time.time()*1000))
    )
    agents.append(AgentState(id=a.lastrowid, experiment_id=exp_id, cohort=f"baseline_{market}",
                             starting_capital=8000.0, cash=8000.0, position_qty=0.0, avg_entry_price=None))

for market in ["BTCINR", "ETHINR", "XRPINR"]:
    a = conn.execute(
        "INSERT INTO agents (experiment_id, cohort, starting_capital, birth_ts) VALUES (?,?,?,?)",
        (exp_id, f"buyhold_{market}", 8000.0, int(time.time()*1000))
    )
    agents.append(AgentState(id=a.lastrowid, experiment_id=exp_id, cohort=f"buyhold_{market}",
                             starting_capital=8000.0, cash=8000.0, position_qty=0.0, avg_entry_price=None))

conn.commit()
print(f"  ✓ Spawned {len(agents)} agents")

risk = RiskConfig(
    emergency_pause=False, max_capital_fraction_per_trade=0.10,
    max_open_positions_per_agent=1, death_equity_fraction=0.40,
    reproduction_equity_fraction=2.00, reproduction_child_fraction=0.50,
    allow_real_orders=False, allow_authenticated_endpoints=False,
    allow_margin_futures_leverage=False, allow_withdraw_transfer=False
)
pause = EmergencyPause(initial=False)
econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
rules = MarketRules(min_notional=100.0, min_quantity=0.00001, step=0.00001)
broker = PaperBroker(econ, rules, max_frac=0.10)
lifecycle = LifecycleChecker(0.40, 2.00, 0.50)

print("\n[STEP 2] Load market data")

market_closes = {}
for market in ["BTCINR", "ETHINR", "XRPINR"]:
    rows = conn.execute(
        "SELECT close FROM market_snapshots WHERE market=? AND window='validation' ORDER BY tick_index",
        (market,)
    ).fetchall()
    market_closes[market] = [float(r[0]) for r in rows]

print(f"  ✓ Loaded {sum(len(c) for c in market_closes.values())} ticks across markets")

strategies = {}
strategies[agents[0].id] = build_strategy("sma_crossover", {"fast": 20, "slow": 100})
strategies[agents[1].id] = build_strategy("ema_crossover", {"fast": 20, "slow": 100})
for i in range(2, 5):
    strategies[agents[i].id] = build_strategy("sma_crossover", {"fast": 5, "slow": 20})

print("\n[STEP 3] Run simulation tick-by-tick")

max_ticks = min(len(c) for c in market_closes.values())
tick_count = 0

try:
    for tick_idx in range(max_ticks):
        tick_count += 1
        current_prices = {m: market_closes[m][tick_idx] for m in market_closes.keys()}
        ts_ms = int(time.time() * 1000)
        
        for agent in agents:
            if not agent.alive:
                continue
            
            if "ethinr" in agent.cohort.lower():
                market = "ETHINR"
            elif "xrpinr" in agent.cohort.lower():
                market = "XRPINR"
            else:
                market = "BTCINR"
            
            mark_price = current_prices[market]
            closes_so_far = market_closes[market][:tick_idx+1]
            
            if agent.id in strategies:
                signal = strategies[agent.id].decide(closes_so_far, agent.position_qty > 0)
                action = signal.action
            else:
                action = "HOLD"
            
            if action == "BUY" and agent.position_qty == 0 and not pause.is_paused:
                fill = broker.simulate_buy(mark_price, agent.cash, agent.position_qty, agent.starting_capital)
                if fill.accepted:
                    db.insert_ledger(conn, experiment_id=exp_id, agent_id=agent.id, ts=ts_ms, tick_index=tick_idx,
                                     event_type="FILL", side="BUY", market_price=mark_price, quantity=fill.quantity,
                                     gross_amount=fill.gross_amount, fee=fill.fee, tds=fill.tds,
                                     slippage_cost=fill.slippage_cost, cash_balance=fill.cash_after,
                                     position_qty=fill.position_after, reason="strategy", detail_json=None)
                    agent.cash = fill.cash_after
                    agent.position_qty = fill.position_after
                    agent.avg_entry_price = mark_price
            
            elif action == "SELL" and agent.position_qty > 0 and not pause.is_paused:
                fill = broker.simulate_sell(mark_price, agent.cash, agent.position_qty)
                if fill.accepted:
                    db.insert_ledger(conn, experiment_id=exp_id, agent_id=agent.id, ts=ts_ms, tick_index=tick_idx,
                                     event_type="FILL", side="SELL", market_price=mark_price, quantity=fill.quantity,
                                     gross_amount=fill.gross_amount, fee=fill.fee, tds=fill.tds,
                                     slippage_cost=fill.slippage_cost, cash_balance=fill.cash_after,
                                     position_qty=fill.position_after, reason="strategy", detail_json=None)
                    agent.cash = fill.cash_after
                    agent.position_qty = 0.0
            
            equity = agent.equity(mark_price)
            death_reason = lifecycle.check_death(agent, equity)
            if death_reason:
                agent.alive = False
                conn.execute("UPDATE agents SET death_ts=? WHERE id=?", (ts_ms, agent.id))
                db.insert_ledger(conn, experiment_id=exp_id, agent_id=agent.id, ts=ts_ms, tick_index=tick_idx,
                                 event_type="DEATH", side=None, market_price=mark_price, quantity=0,
                                 gross_amount=0, fee=0, tds=0, slippage_cost=0, cash_balance=agent.cash,
                                 position_qty=agent.position_qty, reason=death_reason, detail_json=None)
        
        conn.commit()
        
        if tick_count % 50 == 0:
            alive_count = sum(1 for a in agents if a.alive)
            print(f"  Tick {tick_count}/{max_ticks} | {alive_count}/{len(agents)} agents alive")

except KeyboardInterrupt:
    print("\n[INTERRUPTED]")

print(f"\n✓ Simulation complete: {tick_count} ticks")

print("\n" + "=" * 80)
print("FINAL RESULTS")
print("=" * 80)

for agent in agents:
    last = conn.execute(
        "SELECT cash_balance, position_qty FROM ledger WHERE agent_id=? ORDER BY id DESC LIMIT 1",
        (agent.id,)
    ).fetchone()
    
    if last:
        cash, pos = last["cash_balance"], last["position_qty"]
    else:
        cash, pos = agent.starting_capital, 0.0
    
    if "ethinr" in agent.cohort.lower():
        final_price = market_closes["ETHINR"][-1]
    elif "xrpinr" in agent.cohort.lower():
        final_price = market_closes["XRPINR"][-1]
    else:
        final_price = market_closes["BTCINR"][-1]
    
    equity = cash + pos * final_price
    pnl_pct = (equity - agent.starting_capital) / agent.starting_capital * 100
    
    status = "✓ ALIVE" if agent.alive else "✗ DEAD"
    print(f"{agent.cohort:30s} | ₹{equity:>10,.0f} | {pnl_pct:>+7.2f}% | {status}")

print("=" * 80)

if notifier:
    alert_milestone(notifier, f"✓ 7-day live run COMPLETE: {tick_count} ticks, {sum(1 for a in agents if a.alive)} agents survived")

conn.close()
print("\n✓ Ledger saved")
