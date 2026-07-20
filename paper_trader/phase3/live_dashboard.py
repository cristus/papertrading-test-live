"""
live_dashboard.py — Real-time web dashboard for 7-day live paper run.

Updates every 5 seconds from the SQLite ledger.
Shows: agent equity, P&L vs B&H, open positions, trades, health status.
"""
from flask import Flask, render_template, jsonify
import sqlite3, json, time, os
from datetime import datetime, timedelta

app = Flask(__name__, template_folder='../dashboard/templates')
DB_PATH = "data/phase3_exp.sqlite"

def get_db():
    """Get read-only connection to ledger."""
    conn = sqlite3.connect(f"file:{os.path.abspath(DB_PATH)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    """Main dashboard."""
    return render_template('live_dashboard.html')

@app.route('/api/agents')
def api_agents():
    """Get current agent status."""
    conn = get_db()
    agents = conn.execute("SELECT * FROM agents WHERE experiment_id=1 ORDER BY id").fetchall()
    data = []
    
    for a in agents:
        # Latest equity
        last = conn.execute(
            "SELECT cash_balance, position_qty FROM ledger WHERE agent_id=? ORDER BY id DESC LIMIT 1",
            (a["id"],)
        ).fetchone()
        
        if last:
            cash, pos = last["cash_balance"], last["position_qty"]
        else:
            cash, pos = a["starting_capital"], 0.0
        
        # Get latest price
        snap = conn.execute(
            "SELECT close FROM market_snapshots WHERE source='live' ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        price = snap["close"] if snap else 0
        
        equity = cash + pos * price
        pnl_pct = (equity - a["starting_capital"]) / a["starting_capital"] * 100
        
        # Count trades
        trades = conn.execute(
            "SELECT COUNT(*) c FROM ledger WHERE agent_id=? AND event_type='FILL'",
            (a["id"],)
        ).fetchone()["c"]
        
        data.append({
            "id": a["id"],
            "cohort": a["cohort"],
            "starting_capital": a["starting_capital"],
            "equity": equity,
            "pnl_pct": pnl_pct,
            "position": pos,
            "cash": cash,
            "trades": trades,
            "alive": a["death_ts"] is None
        })
    
    conn.close()
    return jsonify(data)

@app.route('/api/equity-curve')
def api_equity_curve():
    """Get equity curves for charting."""
    conn = get_db()
    agents = conn.execute("SELECT id, cohort FROM agents WHERE experiment_id=1").fetchall()
    
    curves = {}
    for a in agents:
        rows = conn.execute(
            "SELECT ts, equity FROM equity_curve WHERE agent_id=? ORDER BY ts",
            (a["id"],)
        ).fetchall()
        
        curves[a["cohort"]] = [{"ts": r["ts"], "equity": r["equity"]} for r in rows]
    
    conn.close()
    return jsonify(curves)

@app.route('/api/ledger')
def api_ledger():
    """Recent trades and events."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM ledger WHERE experiment_id=1 AND event_type IN ('FILL', 'DEATH', 'REPRODUCE_SIGNAL') "
        "ORDER BY id DESC LIMIT 50"
    ).fetchall()
    
    data = [dict(r) for r in rows]
    conn.close()
    return jsonify(data)

@app.route('/api/health')
def api_health():
    """Watchdog health status."""
    conn = get_db()
    
    # Check data freshness
    snap = conn.execute("SELECT MAX(ts) latest FROM market_snapshots WHERE source='live'").fetchone()
    now_ms = int(time.time() * 1000)
    stale = (now_ms - snap["latest"]) / 1000 / 60 if snap["latest"] else None
    
    # Check agents alive
    dead_agents = conn.execute(
        "SELECT COUNT(*) c FROM agents WHERE experiment_id=1 AND death_ts IS NOT NULL"
    ).fetchone()["c"]
    
    # Last 5m of ledger
    recent = conn.execute(
        "SELECT COUNT(*) c FROM ledger WHERE experiment_id=1 AND ts > ? AND event_type='FILL'",
        (int((time.time() - 300) * 1000),)
    ).fetchone()["c"]
    
    conn.close()
    
    return jsonify({
        "data_freshness_minutes": stale,
        "dead_agents": dead_agents,
        "fills_last_5m": recent,
        "status": "healthy" if stale and stale < 10 and dead_agents == 0 else "warning"
    })

if __name__ == '__main__':
    print("=" * 70)
    print("LIVE PAPER TRADING DASHBOARD")
    print("=" * 70)
    print("Starting on http://127.0.0.1:5000")
    print("Updates every 5 seconds from ledger")
    print("=" * 70)
    app.run(host='127.0.0.1', port=5000, debug=False)
