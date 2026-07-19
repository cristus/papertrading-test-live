"""Simple, reliable export: agents + ledger + filter status."""
import json, sqlite3, sys
from datetime import datetime

DB_PATH = "/workspace/paper_trader/data/phase3_exp.sqlite"

def export():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    
    agents = conn.execute("SELECT * FROM agents WHERE experiment_id=1 ORDER BY id").fetchall()
    agent_list = []
    total_equity, total_capital = 0, 0
    
    for a in agents:
        last = conn.execute(
            "SELECT cash_balance, position_qty FROM ledger WHERE agent_id=? ORDER BY id DESC LIMIT 1",
            (a["id"],)).fetchone()
        cash, pos = (last["cash_balance"], last["position_qty"]) if last else (a["starting_capital"], 0.0)
        snap = conn.execute("SELECT close FROM market_snapshots WHERE source='live' ORDER BY ts DESC LIMIT 1").fetchone()
        price = snap["close"] if snap else 0
        
        equity = cash + pos * price
        pnl = equity - a["starting_capital"]
        pnl_pct = (pnl / a["starting_capital"] * 100) if a["starting_capital"] > 0 else 0
        
        fills = conn.execute("SELECT COUNT(*) c FROM ledger WHERE agent_id=? AND event_type='FILL'", (a["id"],)).fetchone()["c"]
        rejects = conn.execute("SELECT COUNT(*) c FROM ledger WHERE agent_id=? AND event_type='REJECT'", (a["id"],)).fetchone()["c"]
        ft = conn.execute("SELECT COALESCE(SUM(fee),0) f, COALESCE(SUM(tds),0) t FROM ledger WHERE agent_id=? AND event_type='FILL'", (a["id"],)).fetchone()
        
        agent_list.append({
            "id": a["id"], "cohort": a["cohort"], "starting_capital": a["starting_capital"],
            "equity": round(equity,2), "pnl": round(pnl,2), "pnl_pct": round(pnl_pct,2),
            "position_qty": round(pos,8), "cash": round(cash,2), "trades": fills,
            "rejections": rejects, "fees": round(ft["f"],2), "tds": round(ft["t"],2),
            "alive": a["death_ts"] is None
        })
        total_equity += equity
        total_capital += a["starting_capital"]
    
    ledger = conn.execute(
        "SELECT * FROM ledger WHERE experiment_id=1 AND event_type IN ('FILL','REJECT','DEATH') ORDER BY id DESC LIMIT 80").fetchall()
    ledger_list = [{
        "ts": r["ts"], "ts_iso": datetime.fromtimestamp(r["ts"]/1000).isoformat(),
        "agent_id": r["agent_id"], "event_type": r["event_type"], "side": r["side"],
        "market_price": r["market_price"], "quantity": round(r["quantity"],8) if r["quantity"] else 0,
        "fee": round(r["fee"],2) if r["fee"] else 0, "tds": round(r["tds"],2) if r["tds"] else 0,
        "reason": r["reason"]
    } for r in ledger]
    
    # Equity history for charting (last 20 snapshots)
    equity_history = []
    for a in agents[:3]:  # Top 3 agents
        rows = conn.execute(
            "SELECT ts, equity FROM equity_curve WHERE agent_id=? ORDER BY ts DESC LIMIT 20",
            (a["id"],)).fetchall()
        equity_history.append({
            "agent_id": a["id"],
            "cohort": a["cohort"],
            "points": [{"ts": r["ts"], "equity": r["equity"]} for r in reversed(rows)]
        })
    
    data = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "summary": {
            "total_capital": round(total_capital,2), "total_equity": round(total_equity,2),
            "net_pnl": round(total_equity-total_capital,2),
            "net_pnl_pct": round((total_equity-total_capital)/total_capital*100,2) if total_capital>0 else 0,
            "agents_alive": sum(1 for a in agent_list if a["alive"]),
            "agents_total": len(agent_list),
            "total_trades": sum(a["trades"] for a in agent_list),
            "total_rejections": sum(a["rejections"] for a in agent_list),
            "total_fees": round(sum(a["fees"] for a in agent_list),2),
            "total_tds": round(sum(a["tds"] for a in agent_list),2)
        },
        "filters": {
            "emergency_pause": False,
            "trading_enabled": True,
            "max_capital_per_trade": "10%",
            "min_notional": 100.0,
            "fee_structure": "0.1% taker + 0.05% spread + 0.1% slippage + 1% TDS on sells",
            "position_limit": "1 open position per agent",
            "death_threshold": "40% of starting capital",
            "reproduction_threshold": "200% of starting capital"
        },
        "agents": agent_list,
        "ledger": ledger_list,
        "equity_history": equity_history
    }
    
    conn.close()
    return data

if __name__ == "__main__":
    d = export()
    with open("data.json", "w") as f:
        json.dump(d, f, indent=2)
    print(f"✓ Exported {len(d['agents'])} agents, {len(d['ledger'])} events, {len(d['equity_history'])} chart series")
    print(f"  Equity: ₹{d['summary']['total_equity']:,.2f} | P&L: {d['summary']['net_pnl_pct']:+.2f}%")
