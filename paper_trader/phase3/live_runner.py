"""
live_runner.py — Continuous live paper trading.
- Fetches 1h candles from CoinDCX every hour
- Runs all 8 agents on new data
- Actually spawns children on reproduction (200% equity)
- Pushes updates to GitHub after every tick
"""
import sys, os, json, time, sqlite3
from datetime import datetime
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from core.market_data import PublicMarketData
from core.broker import PaperBroker, Economics, MarketRules
from core.agent import AgentState, LifecycleChecker
from core.safety import RiskConfig, EmergencyPause
from phase3.strategies import build_strategy

DB_PATH = "data/phase3_exp.sqlite"
GITHUB_REPO = "/tmp/papertrading-test-live"

def push_to_github():
    """Export and push if changed."""
    os.system(f"cd {GITHUB_REPO} && git pull -q origin main 2>/dev/null && python3 export_live_data.py && git add data.json && if ! git diff --cached --quiet; then git commit -m 'Live update: $(date -Iseconds)' && git push; echo '✓ Pushed'; else echo '- No change'; fi")

def main():
    print("=" * 60)
    print("LIVE PAPER TRADING — Hourly Polling")
    print("=" * 60)
    
    md = PublicMarketData()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Load agents
    agents_rows = conn.execute("SELECT * FROM agents WHERE experiment_id=1 AND death_ts IS NULL ORDER BY id").fetchall()
    
    econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
    rules = MarketRules(min_notional=100.0, min_quantity=0.00001, step=0.00001)
    broker = PaperBroker(econ, rules, max_frac=0.10)
    lifecycle = LifecycleChecker(0.40, 2.00, 0.50)
    pause = EmergencyPause(initial=False)
    
    # Strategy mapping
    strategies = {}
    for a in agents_rows:
        if "survivor_sma" in a["cohort"]:
            strategies[a["id"]] = build_strategy("sma_crossover", {"fast": 20, "slow": 100})
        elif "survivor_ema" in a["cohort"]:
            strategies[a["id"]] = build_strategy("ema_crossover", {"fast": 20, "slow": 100})
        elif "baseline" in a["cohort"]:
            strategies[a["id"]] = build_strategy("sma_crossover", {"fast": 5, "slow": 20})
    
    agents = {}
    for a in agents_rows:
        last = conn.execute("SELECT cash_balance, position_qty FROM ledger WHERE agent_id=? ORDER BY id DESC LIMIT 1", (a["id"],)).fetchone()
        cash = last["cash_balance"] if last else a["starting_capital"]
        pos = last["position_qty"] if last else 0.0
        agents[a["id"]] = AgentState(
            id=a["id"], experiment_id=1, cohort=a["cohort"],
            starting_capital=a["starting_capital"], cash=cash, position_qty=pos,
            avg_entry_price=None, alive=True
        )
    
    # Market mapping
    market_for = {}
    for a in agents_rows:
        if "ethinr" in a["cohort"].lower():
            market_for[a["id"]] = "ETHINR"
        elif "xrpinr" in a["cohort"].lower():
            market_for[a["id"]] = "XRPINR"
        else:
            market_for[a["id"]] = "BTCINR"
    
    # Market configs
    markets = {
        "BTCINR": {"pair": "I-BTC_INR"},
        "ETHINR": {"pair": "I-ETH_INR"},
        "XRPINR": {"pair": "I-XRP_INR"},
    }
    
    print(f"\n✓ {len(agents)} agents loaded")
    print("✓ Polling CoinDCX every hour for new 1h candles\n")
    
    tick = 0
    while True:
        tick += 1
        ts = int(time.time() * 1000)
        print(f"\n[TICK {tick}] {datetime.utcnow().strftime('%H:%M UTC')}")
        
        # Fetch latest 1h candle for each market
        prices = {}
        for market, cfg in markets.items():
            try:
                candles = md.get_candles(cfg["pair"], interval="1h", limit=1)
                if candles:
                    prices[market] = candles[-1]["close"]
                    # Store snapshot
                    conn.execute(
                        "INSERT INTO market_snapshots (experiment_id, tick_index, ts, open, high, low, close, volume, bid, ask, last, market, source, window) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (1, tick, ts, candles[-1]["open"], candles[-1]["high"], candles[-1]["low"],
                         candles[-1]["close"], candles[-1]["volume"], candles[-1]["close"], candles[-1]["close"],
                         candles[-1]["close"], market, "live", "live"))
                    print(f"  {market}: ₹{candles[-1]['close']:,.2f}")
                else:
                    print(f"  {market}: no data")
            except Exception as e:
                print(f"  {market}: error — {e}")
        
        if not prices:
            print("  No market data, skipping tick")
            time.sleep(3600)
            continue
        
        conn.commit()
        
        # Run each agent
        for agent_id, agent in agents.items():
            if not agent.alive:
                continue
            
            market = market_for.get(agent_id, "BTCINR")
            price = prices.get(market)
            if not price:
                continue
            
            strat = strategies.get(agent_id)
            if not strat:
                continue  # buy-and-hold
            
            # Get price history for this market
            history = conn.execute(
                "SELECT close FROM market_snapshots WHERE market=? ORDER BY ts",
                (market,)).fetchall()
            closes = [float(r[0]) for r in history]
            
            signal = strat.decide(closes, agent.position_qty > 0)
            action = signal.action
            
            if action == "BUY" and agent.position_qty == 0 and not pause.is_paused:
                fill = broker.simulate_buy(price, agent.cash, agent.position_qty, agent.starting_capital)
                if fill.accepted:
                    db_insert_ledger(conn, 1, agent_id, ts, tick, "FILL", "BUY", price, fill)
                    agent.cash = fill.cash_after
                    agent.position_qty = fill.position_after
                    print(f"  [{agent.cohort}] BUY {fill.quantity:.6f} @ ₹{price:,.0f}")
                else:
                    db_insert_ledger(conn, 1, agent_id, ts, tick, "REJECT", "BUY", price, None, fill.reason)
            
            elif action == "SELL" and agent.position_qty > 0 and not pause.is_paused:
                fill = broker.simulate_sell(price, agent.cash, agent.position_qty)
                if fill.accepted:
                    db_insert_ledger(conn, 1, agent_id, ts, tick, "FILL", "SELL", price, fill)
                    agent.cash = fill.cash_after
                    agent.position_qty = 0.0
                    print(f"  [{agent.cohort}] SELL {fill.quantity:.6f} @ ₹{price:,.0f} | P&L: ₹{fill.cash_after - agent.cash + fill.gross_amount - fill.fee - fill.tds:,.2f}")
                else:
                    db_insert_ledger(conn, 1, agent_id, ts, tick, "REJECT", "SELL", price, None, fill.reason)
            
            # Lifecycle checks
            equity = agent.equity(price)
            death_reason = lifecycle.check_death(agent, equity)
            if death_reason:
                agent.alive = False
                conn.execute("UPDATE agents SET death_ts=?, death_reason=? WHERE id=?", (ts, death_reason, agent_id))
                db_insert_ledger(conn, 1, agent_id, ts, tick, "DEATH", None, price, None, death_reason)
                print(f"  💀 [{agent.cohort}] DEAD: {death_reason}")
            
            repro_reason = lifecycle.check_reproduction(agent, equity)
            if repro_reason:
                # Actually spawn a child!
                child_cap = lifecycle.child_capital(agent.starting_capital)
                agent.cash -= child_cap  # Deduct from parent
                child_row = conn.execute(
                    "INSERT INTO agents (experiment_id, cohort, starting_capital, birth_ts, parent_agent_id) VALUES (?,?,?,?,?)",
                    (1, f"{agent.cohort}_child_{tick}", child_cap, ts, agent_id))
                conn.commit()
                child_id = child_row.lastrowid
                agents[child_id] = AgentState(
                    id=child_id, experiment_id=1, cohort=f"{agent.cohort}_child_{tick}",
                    starting_capital=child_cap, cash=child_cap, position_qty=0.0,
                    avg_entry_price=None, alive=True, parent_agent_id=agent_id
                )
                # Child inherits parent's strategy
                strategies[child_id] = strat
                market_for[child_id] = market
                agent.reproduced_logged = True
                db_insert_ledger(conn, 1, agent_id, ts, tick, "REPRODUCE_SIGNAL", None, price, None, repro_reason)
                print(f"  🧬 [{agent.cohort}] REPRODUCTION! Child spawned with ₹{child_cap:,.0f}")
        
        conn.commit()
        
        # Push to GitHub
        push_to_github()
        
        # Wait for next hour
        print(f"  ⏳ Waiting 60 minutes for next candle...")
        time.sleep(3600)


def db_insert_ledger(conn, exp_id, agent_id, ts, tick, event, side, price, fill_or_reason, reason_text=None):
    if isinstance(fill_or_reason, str):
        # Rejection
        conn.execute(
            "INSERT INTO ledger (experiment_id, agent_id, ts, tick_index, event_type, side, market_price, quantity, gross_amount, fee, tds, slippage_cost, cash_balance, position_qty, reason) "
            "VALUES (?,?,?,?,?,?,?,0,0,0,0,0,0,0,?)",
            (exp_id, agent_id, ts, tick, event, side, price, fill_or_reason))
    else:
        fill = fill_or_reason
        conn.execute(
            "INSERT INTO ledger (experiment_id, agent_id, ts, tick_index, event_type, side, market_price, quantity, gross_amount, fee, tds, slippage_cost, cash_balance, position_qty, reason) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (exp_id, agent_id, ts, tick, event, side, price, fill.quantity, fill.gross_amount,
             fill.fee, fill.tds, fill.slippage_cost, fill.cash_after, fill.position_after,
             fill.reason if not reason_text else reason_text))


if __name__ == "__main__":
    main()
