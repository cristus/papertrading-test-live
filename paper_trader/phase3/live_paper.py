"""
live_paper.py — 7-day parallel paper deployment of top candidates.

Deploys top N strategies on their validated markets + baselines.
All agents read from shared market-data fetch (no per-agent polling).
TDS tracked separately in ledger.
"""
from __future__ import annotations
import sys, os, time, json
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from core import db
from core.broker import PaperBroker, Economics, MarketRules
from core.agent import AgentState, LifecycleChecker
from core.engine import Engine
from core.safety import RiskConfig, EmergencyPause


def deploy_live_agents(survivors: list[dict], conn, experiment_id: int, risk: RiskConfig) -> list[AgentState]:
    """
    Spawn agent instances for each survivor + baseline + buy-and-hold benchmarks.
    All at ₹8,000 tier.
    """
    agents = []
    
    for i, survivor in enumerate(survivors[:6]):  # Max 6 slots
        agent_row = conn.execute(
            "INSERT INTO agents (experiment_id, cohort, starting_capital, birth_ts, parent_agent_id) "
            "VALUES (?,?,?,?,NULL)",
            (experiment_id, f"survivor_{i}_{survivor['family']}", 8000.0, int(time.time()*1000))
        )
        conn.commit()
        agent_id = agent_row.lastrowid
        agents.append(AgentState(
            id=agent_id, experiment_id=experiment_id, cohort=f"survivor_{i}",
            starting_capital=8000.0, cash=8000.0, position_qty=0.0, avg_entry_price=None
        ))
    
    # Add SMA baseline + buy-and-hold benchmarks
    for market in ["BTCINR", "ETHINR", "XRPINR"]:
        agent_row = conn.execute(
            "INSERT INTO agents (experiment_id, cohort, starting_capital, birth_ts, parent_agent_id) "
            "VALUES (?,?,?,?,NULL)",
            (experiment_id, f"benchmark_buyhold_{market}", 8000.0, int(time.time()*1000))
        )
        conn.commit()
        agents.append(AgentState(
            id=agent_row.lastrowid, experiment_id=experiment_id, cohort=f"benchmark_{market}",
            starting_capital=8000.0, cash=8000.0, position_qty=0.0, avg_entry_price=None
        ))
    
    print(f"Deployed {len(agents)} agents for 7-day live run")
    return agents


def run_live_ticks_for_days(conn, agents: list[AgentState], days: int = 7,
                            market_data_fetcher=None) -> dict:
    """
    Simulate live deployment: fetch market data continuously for N days,
    run all agents on every tick, track equity/pnl/deaths/reproduces.
    """
    econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
    rules = MarketRules(min_notional=100.0, min_quantity=0.00001, step=0.00001)
    risk = RiskConfig(
        emergency_pause=False, max_capital_fraction_per_trade=0.10,
        max_open_positions_per_agent=1, death_equity_fraction=0.40,
        reproduction_equity_fraction=2.00, reproduction_child_fraction=0.50,
        allow_real_orders=False, allow_authenticated_endpoints=False,
        allow_margin_futures_leverage=False, allow_withdraw_transfer=False
    )
    pause = EmergencyPause(initial=False)
    
    # For now: stub with dummy ticks (in real deployment, fetch live OHLC)
    summary = {
        "agents_deployed": len(agents),
        "days_run": days,
        "final_equities": {},
        "trades": {},
        "deaths": []
    }
    
    print(f"✓ Live deployment stub: {len(agents)} agents ready for {days}-day run")
    return summary
