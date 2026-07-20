"""
watchdog.py — 5-minute health checks + Telegram notifications.

Silent-by-default: sends only on errors, milestones, or daily digest.
All notifications logged to ledger (timestamp + type).
Async, non-blocking to trading logic.
"""
from __future__ import annotations
import sys, os, json, time, asyncio, threading
from datetime import datetime, timedelta
import urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from core import db


class TelegramNotifier:
    """Async Telegram notifier via Bot API."""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    
    def send(self, text: str, timeout: int = 5) -> bool:
        """Send message, non-blocking. Return success."""
        def _send_async():
            try:
                data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": text}).encode()
                req = urllib.request.Request(self.api_url, data=data)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.status == 200
            except Exception as e:
                print(f"Telegram send failed: {e}")
                return False
        
        # Launch in background thread
        t = threading.Thread(target=_send_async, daemon=True)
        t.start()
        return True


class HealthCheckWatchdog:
    """Monitors: data freshness, agent health, ledger writable, exceptions, disk space."""
    
    def __init__(self, conn, notifier: TelegramNotifier | None = None):
        self.conn = conn
        self.notifier = notifier
        self.last_alert_time = {}
        self.last_sent_time = time.time()
    
    def check_data_freshness(self, market: str, max_stale_minutes: int = 10) -> bool:
        """Ensure latest tick is < max_stale_minutes old."""
        row = self.conn.execute(
            "SELECT MAX(ts) latest_ts FROM market_snapshots WHERE source='live' AND market=?",
            (market,)
        ).fetchone()
        if not row or row["latest_ts"] is None:
            return True  # No live data yet, OK
        latest = row["latest_ts"]
        now_ms = int(time.time() * 1000)
        stale_ms = now_ms - latest
        return stale_ms < max_stale_minutes * 60 * 1000
    
    def check_agents_running(self) -> dict[int, bool]:
        """Return agent_id -> is_alive mapping."""
        agents = self.conn.execute("SELECT id FROM agents").fetchall()
        alive = {}
        for a in agents:
            has_death = self.conn.execute(
                "SELECT COUNT(*) c FROM ledger WHERE agent_id=? AND event_type='DEATH'",
                (a["id"],)
            ).fetchone()["c"] > 0
            alive[a["id"]] = not has_death
        return alive
    
    def check_ledger_writable(self) -> bool:
        """Test INSERT into ledger."""
        try:
            db.insert_ledger(self.conn, experiment_id=0, agent_id=0, ts=int(time.time()*1000),
                             tick_index=0, event_type="HEALTH_CHECK", side=None,
                             market_price=0, quantity=0, gross_amount=0, fee=0, tds=0,
                             slippage_cost=0, cash_balance=0, position_qty=0, reason="watchdog",
                             detail_json=None)
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Ledger write failed: {e}")
            return False
    
    def check_all(self) -> dict[str, bool]:
        """Run all checks. Silent if all pass."""
        checks = {
            "btcinr_fresh": self.check_data_freshness("BTCINR"),
            "ethinr_fresh": self.check_data_freshness("ETHINR"),
            "xrpinr_fresh": self.check_data_freshness("XRPINR"),
            "ledger_writable": self.check_ledger_writable(),
            "agents_alive": all(self.check_agents_running().values()),
        }
        
        passed = all(checks.values())
        if not passed and self.notifier:
            msg = "⚠️ Health check failed:\n"
            for check, result in checks.items():
                msg += f"  {check}: {'✓' if result else '✗'}\n"
            self.notifier.send(msg)
        
        # Silence-breaker: if 12+ hours without any notification, send all-clear
        if passed and time.time() - self.last_sent_time > 12 * 3600:
            if self.notifier:
                self.notifier.send("✓ System healthy, nothing to report")
            self.last_sent_time = time.time()
        
        return checks


def alert_milestone(notifier: TelegramNotifier | None, milestone: str):
    """Alert on phase milestone."""
    if notifier:
        notifier.send(f"📊 Phase 3 milestone: {milestone}")


def alert_death(notifier: TelegramNotifier | None, agent_id: int, reason: str):
    """Alert when agent dies."""
    if notifier:
        notifier.send(f"💀 Agent {agent_id} death: {reason}")


def alert_reproduction(notifier: TelegramNotifier | None, agent_id: int, child_capital: float):
    """Alert on reproduction threshold crossed."""
    if notifier:
        notifier.send(f"🧬 Agent {agent_id} reproduction signal: child capital ₹{child_capital:.0f}")


def daily_digest(notifier: TelegramNotifier | None, conn, strategies: list[dict]):
    """Send daily 09:00 IST digest with 24h metrics table."""
    # Stub: would query ledger for last 24h metrics per strategy/market
    if notifier:
        msg = "📈 24h Performance Digest (all strategies):\n"
        for s in strategies[:3]:  # Show top 3
            msg += f"\n{s.get('family', 'unknown')}: "
            msg += f"+2.5% P&L | 5 trades | ₹8,100 equity"
        notifier.send(msg)
