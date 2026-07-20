"""dashboard/app.py — Read-only Flask dashboard.

STRICTLY READ-ONLY: every DB connection opened here is a SQLite URI
connection with mode=ro. There is no route that executes INSERT/UPDATE/
DELETE, no route that touches config/risk.yaml, and no route that can
place, modify, or trigger any trade. If a write is attempted against a
mode=ro connection, sqlite3 raises OperationalError ("attempt to write a
readonly database") — enforced by the database layer itself, not just by
convention.
"""
from __future__ import annotations
import os
import sys
import json
import glob

from flask import Flask, render_template, request, jsonify, abort

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.db import connect_readonly

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")

app = Flask(__name__)


def load_manifest() -> dict:
    if not os.path.exists(MANIFEST_PATH):
        return {"experiments": []}
    with open(MANIFEST_PATH) as f:
        return json.load(f)


def get_conn(experiment_db_path: str):
    full = os.path.join(DATA_DIR, os.path.basename(experiment_db_path))
    if not os.path.exists(full):
        abort(404)
    return connect_readonly(full)


def _resolve_db_for_experiment(exp_id: int) -> str | None:
    manifest = load_manifest()
    for e in manifest["experiments"]:
        if e["experiment_id"] == exp_id:
            return e["db_path"]
    return None


@app.route("/")
def index():
    manifest = load_manifest()
    return render_template("index.html", experiments=manifest["experiments"])


@app.route("/experiment/<int:exp_id>")
def experiment_detail(exp_id: int):
    db_path = _resolve_db_for_experiment(exp_id)
    if not db_path:
        abort(404)
    conn = get_conn(db_path)
    try:
        exp = conn.execute("SELECT * FROM experiments WHERE id=?", (exp_id,)).fetchone()
        agents = conn.execute("SELECT * FROM agents WHERE experiment_id=?", (exp_id,)).fetchall()

        equity_by_agent = {}
        for a in agents:
            rows = conn.execute(
                "SELECT hour_index, ts, equity, peak_equity, drawdown, open_position_value "
                "FROM equity_curve WHERE agent_id=? ORDER BY hour_index", (a["id"],)).fetchall()
            equity_by_agent[a["id"]] = [dict(r) for r in rows]

        benchmarks_by_cohort = {}
        for a in agents:
            rows = conn.execute(
                "SELECT tick_index, ts, buy_hold_equity FROM benchmarks WHERE cohort=? "
                "ORDER BY tick_index", (a["cohort"],)).fetchall()
            benchmarks_by_cohort[a["cohort"]] = [dict(r) for r in rows]

        # fee/TDS burden by tier — computed fresh from ledger, never cached
        fee_burden = {}
        for a in agents:
            row = conn.execute(
                "SELECT COALESCE(SUM(fee),0) fee_sum, COALESCE(SUM(tds),0) tds_sum, "
                "COUNT(*) fills FROM ledger WHERE agent_id=? AND event_type='FILL'",
                (a["id"],)).fetchone()
            fee_burden[a["cohort"]] = dict(row)

        # min-order rejection counts by tier
        reject_counts = {}
        for a in agents:
            row = conn.execute(
                "SELECT COUNT(*) c FROM ledger WHERE agent_id=? AND event_type='REJECT' "
                "AND reason LIKE 'min-order%'", (a["id"],)).fetchone()
            reject_counts[a["cohort"]] = row["c"]

        # drawdown / survival stats — fresh from ledger/equity_curve
        survival = {}
        for a in agents:
            max_dd_row = conn.execute(
                "SELECT MAX(drawdown) dd FROM equity_curve WHERE agent_id=?", (a["id"],)).fetchone()
            survival[a["cohort"]] = {
                "alive": a["death_ts"] is None,
                "death_reason": a["death_reason"],
                "max_drawdown": max_dd_row["dd"] if max_dd_row["dd"] is not None else 0.0,
            }

        return render_template(
            "experiment.html", exp=dict(exp), agents=[dict(a) for a in agents],
            equity_by_agent=equity_by_agent, benchmarks_by_cohort=benchmarks_by_cohort,
            fee_burden=fee_burden, reject_counts=reject_counts, survival=survival)
    finally:
        conn.close()


@app.route("/experiment/<int:exp_id>/ledger")
def ledger_browser(exp_id: int):
    db_path = _resolve_db_for_experiment(exp_id)
    if not db_path:
        abort(404)
    conn = get_conn(db_path)
    try:
        agent_id = request.args.get("agent_id", type=int)
        event_type = request.args.get("event_type", type=str)
        side = request.args.get("side", type=str)
        limit = min(request.args.get("limit", default=200, type=int), 2000)

        q = "SELECT * FROM ledger WHERE experiment_id=?"
        params = [exp_id]
        if agent_id:
            q += " AND agent_id=?"
            params.append(agent_id)
        if event_type:
            q += " AND event_type=?"
            params.append(event_type)
        if side:
            q += " AND side=?"
            params.append(side)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(q, params).fetchall()
        return render_template("ledger.html", rows=[dict(r) for r in rows], exp_id=exp_id,
                              agent_id=agent_id, event_type=event_type, side=side)
    finally:
        conn.close()


@app.route("/api/experiment/<int:exp_id>/equity.json")
def equity_json(exp_id: int):
    """Read-only JSON API for chart rendering. No write path exists."""
    db_path = _resolve_db_for_experiment(exp_id)
    if not db_path:
        abort(404)
    conn = get_conn(db_path)
    try:
        agents = conn.execute("SELECT id, cohort, starting_capital FROM agents WHERE experiment_id=?",
                              (exp_id,)).fetchall()
        out = {}
        for a in agents:
            rows = conn.execute(
                "SELECT ts, equity FROM equity_curve WHERE agent_id=? ORDER BY hour_index",
                (a["id"],)).fetchall()
            bench = conn.execute(
                "SELECT ts, buy_hold_equity FROM benchmarks WHERE cohort=? ORDER BY tick_index",
                (a["cohort"],)).fetchall()
            out[a["cohort"]] = {
                "starting_capital": a["starting_capital"],
                "equity": [{"ts": r["ts"], "equity": r["equity"]} for r in rows],
                "benchmark": [{"ts": r["ts"], "equity": r["buy_hold_equity"]} for r in bench],
            }
        return jsonify(out)
    finally:
        conn.close()


# --- Safety guard: refuse ANY non-GET method at the app level, belt & braces ---
@app.before_request
def enforce_read_only():
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        abort(405)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False)
