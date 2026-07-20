"""
Generate a standalone HTML report that reads from the SQLite ledger.
Can be served on any web server or GitHub Pages.
"""
import json, sqlite3, time
from datetime import datetime

def generate_html_report():
    """Create a self-contained HTML file with live data embedded."""
    
    db_path = "data/phase3_exp.sqlite"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    
    # Fetch live data
    agents = conn.execute("SELECT * FROM agents WHERE experiment_id=1 ORDER BY id").fetchall()
    ledger = conn.execute(
        "SELECT * FROM ledger WHERE experiment_id=1 AND event_type IN ('FILL','DEATH','REJECT') ORDER BY id DESC LIMIT 50"
    ).fetchall()
    
    agent_data = []
    for a in agents:
        last = conn.execute(
            "SELECT cash_balance, position_qty FROM ledger WHERE agent_id=? ORDER BY id DESC LIMIT 1",
            (a["id"],)
        ).fetchone()
        
        if last:
            cash, pos = last["cash_balance"], last["position_qty"]
        else:
            cash, pos = a["starting_capital"], 0.0
        
        snap = conn.execute("SELECT close FROM market_snapshots WHERE source='live' ORDER BY ts DESC LIMIT 1").fetchone()
        price = snap["close"] if snap else 0
        
        equity = cash + pos * price
        pnl_pct = (equity - a["starting_capital"]) / a["starting_capital"] * 100
        
        trades = conn.execute("SELECT COUNT(*) c FROM ledger WHERE agent_id=? AND event_type='FILL'", (a["id"],)).fetchone()["c"]
        
        agent_data.append({
            "cohort": a["cohort"],
            "capital": a["starting_capital"],
            "equity": equity,
            "pnl_pct": pnl_pct,
            "position": pos,
            "trades": trades,
            "alive": a["death_ts"] is None
        })
    
    ledger_data = [
        {
            "ts": datetime.fromtimestamp(r["ts"]/1000).isoformat(),
            "agent_id": r["agent_id"],
            "type": r["event_type"],
            "side": r["side"],
            "price": r["market_price"],
            "qty": r["quantity"],
            "fee_tds": (r["fee"] or 0) + (r["tds"] or 0),
            "reason": r["reason"]
        }
        for r in ledger
    ]
    
    conn.close()
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Phase 3 — Live Paper Trading Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Courier New', monospace; background: #0a0e27; color: #e6e6e6; padding: 20px; }}
        .header {{ background: #1a1f3a; padding: 20px; border-left: 5px solid #00ff41; margin-bottom: 20px; border-radius: 4px; }}
        h1 {{ font-size: 28px; color: #00ff41; margin-bottom: 5px; }}
        .subtitle {{ font-size: 12px; color: #888; }}
        .timestamp {{ font-size: 11px; color: #666; margin-top: 10px; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 15px; margin-bottom: 20px; }}
        .card {{ background: #1a1f3a; padding: 15px; border: 1px solid #333; border-radius: 4px; }}
        .card h2 {{ font-size: 14px; color: #00ff41; margin-bottom: 15px; text-transform: uppercase; letter-spacing: 1px; }}
        .metric {{ display: flex; justify-content: space-between; margin: 8px 0; font-size: 13px; }}
        .label {{ color: #aaa; }}
        .value {{ font-weight: bold; color: #00ff41; }}
        .negative {{ color: #ff4444; }}
        .positive {{ color: #00ff41; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin: 10px 0; }}
        th {{ background: #1a1f3a; color: #00ff41; padding: 10px; text-align: left; border-bottom: 2px solid #00ff41; }}
        td {{ padding: 8px; border-bottom: 1px solid #333; }}
        tr:hover {{ background: #111; }}
        .status {{ padding: 8px 12px; border-radius: 4px; font-size: 12px; display: inline-block; }}
        .healthy {{ background: #004400; color: #00ff41; }}
        .warning {{ background: #443300; color: #ffaa00; }}
        .dead {{ background: #440000; color: #ff4444; }}
        .refresh-info {{ font-size: 11px; color: #666; margin-top: 15px; }}
        .last-update {{ font-size: 11px; color: #888; text-align: right; margin-top: 20px; border-top: 1px solid #333; padding-top: 10px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 PHASE 3 — LIVE PAPER TRADING</h1>
        <p class="subtitle">7-Day Continuous Experiment | ETHINR Focus + Multi-Market Baselines</p>
        <p class="timestamp">Generated: {datetime.now().isoformat()}</p>
    </div>

    <div class="grid">
        <div class="card">
            <h2>Portfolio Summary</h2>
            <div class="metric">
                <span class="label">Total Capital</span>
                <span class="value">₹{sum(a['capital'] for a in agent_data):,.0f}</span>
            </div>
            <div class="metric">
                <span class="label">Total Equity</span>
                <span class="value">₹{sum(a['equity'] for a in agent_data):,.2f}</span>
            </div>
            <div class="metric">
                <span class="label">Net P&L</span>
                <span class="{'positive' if sum(a['equity']-a['capital'] for a in agent_data) >= 0 else 'negative'}">
                    ₹{sum(a['equity']-a['capital'] for a in agent_data):+,.2f}
                </span>
            </div>
            <div class="metric">
                <span class="label">Avg Return</span>
                <span class="{'positive' if sum(a['pnl_pct'] for a in agent_data)/len(agent_data) >= 0 else 'negative'}">
                    {sum(a['pnl_pct'] for a in agent_data)/len(agent_data):+.2f}%
                </span>
            </div>
        </div>

        <div class="card">
            <h2>Agent Status</h2>
            <div class="metric">
                <span class="label">Agents Alive</span>
                <span class="value">{sum(1 for a in agent_data if a['alive'])}/{len(agent_data)}</span>
            </div>
            <div class="metric">
                <span class="label">Total Trades</span>
                <span class="value">{sum(a['trades'] for a in agent_data)}</span>
            </div>
            <div class="metric">
                <span class="label">Deaths</span>
                <span class="dead" style="background: transparent; color: #00ff41;">{len(agent_data) - sum(1 for a in agent_data if a['alive'])}</span>
            </div>
            <div class="metric">
                <span class="label">Top Performer</span>
                <span class="positive">{max(agent_data, key=lambda a: a['pnl_pct'])['cohort']}</span>
            </div>
        </div>

        <div class="card">
            <h2>Top Survivors</h2>
            {chr(10).join(f'''<div class="metric">
                <span class="label">{a['cohort']}</span>
                <span class="{
                    'positive' if a['pnl_pct'] >= 0 else 'negative'
                }">{a['pnl_pct']:+.2f}%</span>
            </div>''' for a in sorted(agent_data, key=lambda x: x['pnl_pct'], reverse=True)[:3])}
        </div>
    </div>

    <div class="card">
        <h2>Agent Performance Table</h2>
        <table>
            <thead>
                <tr>
                    <th>Agent / Cohort</th>
                    <th>Start Capital</th>
                    <th>Current Equity</th>
                    <th>P&L %</th>
                    <th>Position</th>
                    <th>Trades</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {chr(10).join(f'''<tr>
                    <td>{a['cohort']}</td>
                    <td>₹{a['capital']:,.0f}</td>
                    <td>₹{a['equity']:,.2f}</td>
                    <td class="{'positive' if a['pnl_pct'] >= 0 else 'negative'}">{a['pnl_pct']:+.2f}%</td>
                    <td>{a['position']:.8f}</td>
                    <td>{a['trades']}</td>
                    <td><span class="status {'healthy' if a['alive'] else 'dead'}">{
                        '✓ ALIVE' if a['alive'] else '✗ DEAD'
                    }</span></td>
                </tr>''' for a in agent_data)}
            </tbody>
        </table>
    </div>

    <div class="card">
        <h2>Recent Activity (Last 50 Events)</h2>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Agent ID</th>
                    <th>Event</th>
                    <th>Side</th>
                    <th>Price</th>
                    <th>Qty</th>
                    <th>Fee+TDS</th>
                    <th>Reason</th>
                </tr>
            </thead>
            <tbody>
                {chr(10).join(f'''<tr>
                    <td style="font-size: 11px;">{e['ts']}</td>
                    <td>{e['agent_id']}</td>
                    <td>{e['type']}</td>
                    <td>{e['side'] or '—'}</td>
                    <td>₹{e['price']:,.0f}</td>
                    <td>{e['qty']:.8f}</td>
                    <td>₹{e['fee_tds']:.2f}</td>
                    <td style="font-size: 11px; color: #888;">{(e['reason'] or '')[:40]}</td>
                </tr>''' for e in ledger_data)}
            </tbody>
        </table>
    </div>

    <div class="last-update">
        Last updated: {datetime.now().isoformat()} UTC<br>
        <strong>ℹ️ To get live updates:</strong> Refresh this page manually or set up auto-refresh in your browser (F5 every 30 seconds)
    </div>
</body>
</html>
"""
    
    with open("dashboard_live.html", "w") as f:
        f.write(html)
    
    return "dashboard_live.html"

if __name__ == "__main__":
    file = generate_html_report()
    print(f"✓ Report generated: {file}")
    print(f"✓ Size: {open(file).read().__sizeof__()} bytes")
