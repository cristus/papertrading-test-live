"""
export_live_data.py - Export live ledger data to data.json every 5 minutes
This script is called by cron and commits to GitHub
"""
import json, sqlite3, sys, os
from datetime import datetime
sys.path.insert(0, "/workspace/paper_trader")

DB_PATH = "/workspace/paper_trader/data/phase3_exp.sqlite"

def export_data():
    """Export current ledger state to JSON."""
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        
        # Get agents
        agents = conn.execute("SELECT * FROM agents WHERE experiment_id=1 ORDER BY id").fetchall()
        
        agent_list = []
        total_equity = 0
        total_capital = 0
        
        for a in agents:
            last = conn.execute(
                "SELECT cash_balance, position_qty FROM ledger WHERE agent_id=? ORDER BY id DESC LIMIT 1",
                (a["id"],)
            ).fetchone()
            
            if last:
                cash, pos = last["cash_balance"], last["position_qty"]
            else:
                cash, pos = a["starting_capital"], 0.0
            
            # Get latest price from any market
            snap = conn.execute(
                "SELECT close FROM market_snapshots WHERE source='live' ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            price = snap["close"] if snap else 0
            
            equity = cash + pos * price
            pnl = equity - a["starting_capital"]
            pnl_pct = (pnl / a["starting_capital"] * 100) if a["starting_capital"] > 0 else 0
            
            # Count trades
            fills = conn.execute(
                "SELECT COUNT(*) c FROM ledger WHERE agent_id=? AND event_type='FILL'",
                (a["id"],)
            ).fetchone()["c"]
            
            # Get fees + TDS
            fees_tds = conn.execute(
                "SELECT COALESCE(SUM(fee),0) fees, COALESCE(SUM(tds),0) tds FROM ledger WHERE agent_id=? AND event_type='FILL'",
                (a["id"],)
            ).fetchone()
            
            agent_list.append({
                "id": a["id"],
                "cohort": a["cohort"],
                "starting_capital": a["starting_capital"],
                "equity": round(equity, 2),
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "position_qty": round(pos, 8),
                "cash": round(cash, 2),
                "trades": fills,
                "fees": round(fees_tds["fees"], 2),
                "tds": round(fees_tds["tds"], 2),
                "alive": a["death_ts"] is None,
                "death_reason": a["death_reason"]
            })
            
            total_equity += equity
            total_capital += a["starting_capital"]
        
        # Get recent ledger events
        ledger = conn.execute(
            "SELECT * FROM ledger WHERE experiment_id=1 AND event_type IN ('FILL','REJECT','DEATH','REPRODUCE_SIGNAL') ORDER BY id DESC LIMIT 100"
        ).fetchall()
        
        ledger_list = [
            {
                "ts": r["ts"],
                "ts_iso": datetime.fromtimestamp(r["ts"]/1000).isoformat(),
                "agent_id": r["agent_id"],
                "event_type": r["event_type"],
                "side": r["side"],
                "market_price": r["market_price"],
                "quantity": round(r["quantity"], 8) if r["quantity"] else 0,
                "fee": round(r["fee"], 2) if r["fee"] else 0,
                "tds": round(r["tds"], 2) if r["tds"] else 0,
                "reason": r["reason"]
            }
            for r in ledger
        ]
        
        # Build summary
        data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "summary": {
                "total_capital": round(total_capital, 2),
                "total_equity": round(total_equity, 2),
                "net_pnl": round(total_equity - total_capital, 2),
                "net_pnl_pct": round((total_equity - total_capital) / total_capital * 100, 2) if total_capital > 0 else 0,
                "agents_alive": sum(1 for a in agent_list if a["alive"]),
                "agents_total": len(agent_list),
                "total_trades": sum(a["trades"] for a in agent_list),
                "total_fees": round(sum(a["fees"] for a in agent_list), 2),
                "total_tds": round(sum(a["tds"] for a in agent_list), 2)
            },
            "agents": agent_list,
            "ledger": ledger_list
        }
        
        conn.close()
        return data
        
    except Exception as e:
        print(f"Error exporting data: {e}")
        return None

if __name__ == "__main__":
    data = export_data()
    if data:
        with open("data.json", "w") as f:
            json.dump(data, f, indent=2)
        print(f"✓ Exported {len(data['agents'])} agents, {len(data['ledger'])} ledger entries")
        print(f"  Total equity: ₹{data['summary']['total_equity']:,.2f}")
    else:
        print("✗ Export failed")
        sys.exit(1)
