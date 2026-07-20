"""Cohort isolation: all tiers see identical market data."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core import db

def test_all_cohorts_read_same_snapshot_rows(tmp_path):
    conn = db.init_db(str(tmp_path / "iso.sqlite"))
    conn.execute("INSERT INTO experiments (start_ts,code_version,config_json,random_seed,market,strategy_name,strategy_params) VALUES (1,'v','{}',1,'BTCINR','sma','{}')")
    conn.commit()
    experiment_id = 1

    fake_candles = [
        {"time": 1000 + i * 60000, "open": 100 + i, "high": 101 + i, "low": 99 + i,
         "close": 100 + i, "volume": 1.0}
        for i in range(10)
    ]
    from core.engine import Engine
    from core.broker import Economics, MarketRules
    from core.safety import RiskConfig, EmergencyPause

    risk = RiskConfig(emergency_pause=False, max_capital_fraction_per_trade=0.10,
                      max_open_positions_per_agent=1, death_equity_fraction=0.40,
                      reproduction_equity_fraction=2.00, reproduction_child_fraction=0.50,
                      allow_real_orders=False, allow_authenticated_endpoints=False,
                      allow_margin_futures_leverage=False, allow_withdraw_transfer=False)
    econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
    rules = MarketRules(min_notional=100.0, min_quantity=0.00001, step=0.00001)
    pause = EmergencyPause(initial=False)
    engine = Engine(conn, experiment_id, risk, econ, rules, "sma_crossover",
                    {"fast_window": 3, "slow_window": 5}, pause)
    engine.store_candles_as_snapshots(fake_candles)

    # Simulate 3 cohorts each "reading" the snapshot table independently
    snaps_2k = engine.load_snapshots()
    snaps_8k = engine.load_snapshots()
    snaps_20k = engine.load_snapshots()

    assert snaps_2k == snaps_8k == snaps_20k
    assert len(snaps_2k) == len(fake_candles)
    # Only ONE row per tick_index across the whole experiment (single fetch, shared)
    tick_indices = [r["tick_index"] for r in snaps_2k]
    assert tick_indices == sorted(set(tick_indices))

def test_market_data_fetched_once_not_per_agent(tmp_path, monkeypatch):
    """
    The engine's store_candles_as_snapshots is the ONLY path that writes
    market data; agents must never call the market_data client themselves.
    We assert the core.agent module has no import of core.market_data.
    """
    import core.agent as agent_module
    import inspect
    src = inspect.getsource(agent_module)
    assert "market_data" not in src
    import core.strategy as strategy_module
    src2 = inspect.getsource(strategy_module)
    # check for actual imports/usage, not incidental docstring mentions
    assert "import core.market_data" not in src2
    assert "from core.market_data" not in src2
    assert "from core import market_data" not in src2
    assert "import requests" not in src2
