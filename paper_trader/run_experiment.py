"""run_experiment.py — Cohort runner.

Runs three capital-tier cohorts (identical strategy, market, time window)
against BACKTEST-replayed public CoinDCX candles. Fetches market data
ONCE per tick; all cohorts/agents read from the same stored snapshot.

Usage:
    python3 run_experiment.py [--config config/config.yaml]
"""
from __future__ import annotations
import argparse
import json
import os
import random
import sys
import time
import uuid

import yaml

sys.path.insert(0, os.path.dirname(__file__))

from core import db
from core.market_data import PublicMarketData
from core.broker import Economics, MarketRules
from core.agent import AgentState
from core.engine import Engine
from core.safety import load_risk_config, EmergencyPause

CODE_VERSION = "0.1.0"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")


def load_config(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def update_manifest(entry: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    manifest = {"experiments": []}
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)
    manifest["experiments"].append(entry)
    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def run(config_path: str) -> dict:
    cfg = load_config(config_path)
    risk = load_risk_config()  # loads config/risk.yaml, validates, freezes
    pause = EmergencyPause(initial=risk.emergency_pause)

    random.seed(cfg["random_seed"])

    market_symbol = cfg["market"]["symbol"]
    md = PublicMarketData()
    details = md.get_market_details(market_symbol)
    rules = MarketRules(min_notional=details["min_notional"],
                        min_quantity=details["min_quantity"], step=details["step"])
    econ = Economics(**cfg["economics"])

    # Fetch candles ONCE — shared by every cohort/agent (no individual polling)
    candles = md.get_candles(details["pair"], interval=cfg["data"]["candle_interval"],
                             limit=cfg["data"]["backtest_ticks"])
    if len(candles) < 5:
        raise RuntimeError("Not enough candle data returned from CoinDCX public API.")

    db_path = os.path.join(DATA_DIR, f"exp_{uuid.uuid4().hex[:10]}.sqlite")
    conn = db.init_db(db_path)

    start_ts = int(time.time() * 1000)
    strategy_params = cfg["strategy"]["params"]
    cur = conn.execute(
        "INSERT INTO experiments (start_ts, code_version, config_json, random_seed, market, "
        "strategy_name, strategy_params) VALUES (?,?,?,?,?,?,?)",
        (start_ts, CODE_VERSION, json.dumps(cfg), cfg["random_seed"], market_symbol,
         cfg["strategy"]["name"], json.dumps(strategy_params)))
    conn.commit()
    experiment_id = cur.lastrowid

    engine = Engine(conn, experiment_id, risk, econ, rules, cfg["strategy"]["name"],
                    strategy_params, pause)
    engine.store_candles_as_snapshots(candles)

    # Spawn one agent per cohort (identical market/window/strategy; capital differs)
    agents: dict[str, AgentState] = {}
    for cohort in cfg["cohorts"]:
        cur = conn.execute(
            "INSERT INTO agents (experiment_id, cohort, starting_capital, birth_ts, parent_agent_id) "
            "VALUES (?,?,?,?,NULL)",
            (experiment_id, cohort["name"], cohort["starting_capital"], candles[0]["time"]))
        agent_id = cur.lastrowid
        agents[cohort["name"]] = AgentState(
            id=agent_id, experiment_id=experiment_id, cohort=cohort["name"],
            starting_capital=cohort["starting_capital"], cash=cohort["starting_capital"],
            position_qty=0.0, avg_entry_price=None)
    conn.commit()

    closes = [c["close"] for c in candles]
    tick_seconds = cfg["data"]["tick_seconds"]
    hour_bucket_ticks = max(1, int(3600 / tick_seconds))
    peak_tracker: dict[int, float] = {}
    first_price = closes[0]

    for i, candle in enumerate(candles):
        if pause.is_paused:
            break
        mark_price = candle["close"]
        closes_so_far = closes[: i + 1]  # NO-LOOKAHEAD: strictly up to now

        for cohort in cfg["cohorts"]:
            agent = agents[cohort["name"]]
            engine.run_agent_tick(agent, closes_so_far, i, candle["time"], mark_price)

        conn.commit()

        if i % hour_bucket_ticks == 0:
            for cohort in cfg["cohorts"]:
                agent = agents[cohort["name"]]
                engine.record_equity(agent, i // hour_bucket_ticks, candle["time"], mark_price,
                                     peak_tracker)
                engine.record_benchmark(cohort["name"], cohort["starting_capital"], i,
                                        candle["time"], first_price, mark_price)
            conn.commit()

    end_ts = int(time.time() * 1000)
    conn.execute("UPDATE experiments SET end_ts=? WHERE id=?", (end_ts, experiment_id))
    conn.commit()

    summary = {
        "experiment_id": experiment_id,
        "db_path": db_path,
        "market": market_symbol,
        "ticks": len(candles),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "code_version": CODE_VERSION,
        "cohorts": [c["name"] for c in cfg["cohorts"]],
        "min_notional": rules.min_notional,
        "min_quantity": rules.min_quantity,
    }
    update_manifest(summary)
    conn.close()
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "config", "config.yaml"))
    args = ap.parse_args()
    result = run(args.config)
    print(json.dumps(result, indent=2))
