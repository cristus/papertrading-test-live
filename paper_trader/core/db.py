"""db.py — SQLite schema + append-only ledger enforcement.

One SQLite file per experiment. The `ledger` table is APPEND-ONLY:
triggers raise on any UPDATE or DELETE, enforcing the audit rule at the
database level (not just by convention).
"""
from __future__ import annotations
import sqlite3
import json
import os

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS experiments (
    id                INTEGER PRIMARY KEY,
    start_ts          INTEGER NOT NULL,
    end_ts            INTEGER,
    code_version      TEXT NOT NULL,
    config_json       TEXT NOT NULL,
    random_seed       INTEGER NOT NULL,
    market            TEXT NOT NULL,
    strategy_name     TEXT NOT NULL,
    strategy_params   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id                INTEGER PRIMARY KEY,
    experiment_id     INTEGER NOT NULL REFERENCES experiments(id),
    cohort            TEXT NOT NULL,
    starting_capital  REAL NOT NULL,
    birth_ts          INTEGER NOT NULL,
    death_ts          INTEGER,
    death_reason      TEXT,
    parent_agent_id   INTEGER REFERENCES agents(id)
);

CREATE TABLE IF NOT EXISTS ledger (
    id                INTEGER PRIMARY KEY,
    experiment_id     INTEGER NOT NULL,
    agent_id          INTEGER NOT NULL,
    ts                INTEGER NOT NULL,
    tick_index        INTEGER NOT NULL,
    event_type        TEXT NOT NULL,
    side              TEXT,
    market_price      REAL,
    quantity          REAL,
    gross_amount      REAL,
    fee               REAL,
    tds               REAL,
    slippage_cost     REAL,
    cash_balance      REAL,
    position_qty      REAL,
    reason            TEXT,
    detail_json       TEXT
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id                INTEGER PRIMARY KEY,
    experiment_id     INTEGER NOT NULL,
    tick_index        INTEGER NOT NULL,
    ts                INTEGER NOT NULL,
    open              REAL, high REAL, low REAL, close REAL, volume REAL,
    bid               REAL, ask REAL, last REAL,
    UNIQUE(experiment_id, tick_index)
);

CREATE TABLE IF NOT EXISTS equity_curve (
    id                INTEGER PRIMARY KEY,
    experiment_id     INTEGER NOT NULL,
    agent_id          INTEGER NOT NULL,
    hour_index        INTEGER NOT NULL,
    ts                INTEGER NOT NULL,
    equity            REAL NOT NULL,
    peak_equity       REAL NOT NULL,
    drawdown          REAL NOT NULL,
    open_position_value REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmarks (
    id                INTEGER PRIMARY KEY,
    experiment_id     INTEGER NOT NULL,
    cohort            TEXT NOT NULL,
    starting_capital  REAL NOT NULL,
    tick_index        INTEGER NOT NULL,
    ts                INTEGER NOT NULL,
    buy_hold_equity   REAL NOT NULL
);

CREATE TRIGGER IF NOT EXISTS ledger_no_update
BEFORE UPDATE ON ledger
BEGIN
    SELECT RAISE(ABORT, 'ledger is append-only: UPDATE forbidden');
END;

CREATE TRIGGER IF NOT EXISTS ledger_no_delete
BEFORE DELETE ON ledger
BEGIN
    SELECT RAISE(ABORT, 'ledger is append-only: DELETE forbidden');
END;

CREATE INDEX IF NOT EXISTS idx_ledger_agent ON ledger(agent_id);
CREATE INDEX IF NOT EXISTS idx_ledger_exp ON ledger(experiment_id);
CREATE INDEX IF NOT EXISTS idx_snap_exp ON market_snapshots(experiment_id, tick_index);
CREATE INDEX IF NOT EXISTS idx_equity_agent ON equity_curve(agent_id);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    conn = connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def connect_readonly(db_path: str) -> sqlite3.Connection:
    """Read-only connection for the dashboard. Writes will raise."""
    uri = f"file:{os.path.abspath(db_path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def insert_ledger(conn, **kw) -> int:
    cols = ["experiment_id", "agent_id", "ts", "tick_index", "event_type",
            "side", "market_price", "quantity", "gross_amount", "fee", "tds",
            "slippage_cost", "cash_balance", "position_qty", "reason", "detail_json"]
    vals = [kw.get(c) for c in cols]
    if isinstance(kw.get("detail_json"), (dict, list)):
        vals[cols.index("detail_json")] = json.dumps(kw["detail_json"])
    q = f"INSERT INTO ledger ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
    cur = conn.execute(q, vals)
    return cur.lastrowid
