"""Emergency-pause flag halts all trading."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.safety import EmergencyPause, RiskConfig, SafetyViolation, load_risk_config
from core.agent import AgentState
from core.engine import Engine
from core.broker import Economics, MarketRules
from core import db

def make_risk(**overrides):
    base = dict(emergency_pause=False, max_capital_fraction_per_trade=0.10,
               max_open_positions_per_agent=1, death_equity_fraction=0.40,
               reproduction_equity_fraction=2.00, reproduction_child_fraction=0.50,
               allow_real_orders=False, allow_authenticated_endpoints=False,
               allow_margin_futures_leverage=False, allow_withdraw_transfer=False)
    base.update(overrides)
    return RiskConfig(**base)

def test_emergency_pause_trip_halts_agent_tick(tmp_path):
    conn = db.init_db(str(tmp_path / "pause.sqlite"))
    conn.execute("INSERT INTO experiments (start_ts,code_version,config_json,random_seed,market,strategy_name,strategy_params) VALUES (1,'v','{}',1,'BTCINR','sma','{}')")
    conn.commit()
    risk = make_risk()
    econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
    rules = MarketRules(min_notional=100.0, min_quantity=0.00001, step=0.00001)
    pause = EmergencyPause(initial=False)
    engine = Engine(conn, 1, risk, econ, rules, "sma_crossover", {"fast_window":3,"slow_window":5}, pause)

    agent = AgentState(id=1, experiment_id=1, cohort="tier_2k", starting_capital=2000,
                       cash=2000, position_qty=0, avg_entry_price=None)

    pause.trip("operator halt")
    closes = [100,100,100,100,100,101,102,103,104,105]
    cash_before, pos_before = agent.cash, agent.position_qty
    engine.run_agent_tick(agent, closes, tick_index=len(closes)-1, ts=999, mark_price=105)

    # nothing changed — the tick was a no-op once paused
    assert agent.cash == cash_before
    assert agent.position_qty == pos_before

    row = conn.execute("SELECT * FROM ledger WHERE agent_id=1 ORDER BY id DESC LIMIT 1").fetchone()
    assert row["event_type"] == "PAUSED"

def test_risk_config_startup_pause_flag_propagates():
    risk = make_risk(emergency_pause=True)
    pause = EmergencyPause(initial=risk.emergency_pause)
    assert pause.is_paused is True

def test_risk_config_rejects_unsafe_overrides():
    """The immutable RiskConfig must self-reject if any prohibited capability is enabled."""
    try:
        make_risk(allow_real_orders=True).assert_safe()
        assert False, "should have raised SafetyViolation"
    except SafetyViolation:
        pass
    try:
        make_risk(allow_authenticated_endpoints=True).assert_safe()
        assert False
    except SafetyViolation:
        pass
    try:
        make_risk(max_capital_fraction_per_trade=0.25).assert_safe()
        assert False, "cap above 10% must be rejected"
    except SafetyViolation:
        pass

def test_risk_config_is_frozen_dataclass():
    risk = make_risk()
    try:
        risk.emergency_pause = True
        assert False, "RiskConfig must be immutable (frozen dataclass)"
    except Exception:
        pass
