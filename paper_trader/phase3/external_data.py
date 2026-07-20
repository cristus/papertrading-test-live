"""
external_data.py - Fetch and cache external market data for trading decisions

Sources:
1. Economic Calendar (Fed events, CPI, etc.)
2. Bitcoin Dominance (altseason detection)
3. Funding Rates (futures positioning)
4. Volatility Metrics (market regime)
5. On-Chain Flows (whale activity)
"""
from __future__ import annotations
import requests, json, time
from datetime import datetime, timedelta
from typing import Optional

class ExternalDataFetcher:
    """Fetch external data from free public APIs."""
    
    def __init__(self, cache_dir: str = "/tmp/market_data_cache"):
        self.cache_dir = cache_dir
        self.last_fetch = {}
        self.cache_ttl = 300  # 5 minutes
    
    def _cached_fetch(self, key: str, fetch_fn, ttl: int = None) -> Optional[dict]:
        """Fetch with caching to avoid rate limits."""
        ttl = ttl or self.cache_ttl
        now = time.time()
        
        if key in self.last_fetch:
            age = now - self.last_fetch[key]["time"]
            if age < ttl:
                return self.last_fetch[key]["data"]
        
        try:
            data = fetch_fn()
            self.last_fetch[key] = {"time": now, "data": data}
            return data
        except Exception as e:
            print(f"  ⚠️  Fetch error ({key}): {e}")
            return self.last_fetch.get(key, {}).get("data")
    
    # ---- 1. ECONOMIC CALENDAR ----
    
    def get_fed_events_today(self) -> dict:
        """Check if there's a major Fed/ECB/BoJ event today."""
        def fetch():
            # Simplified: check if today is FOMC day or CPI release day
            # In production: call Investing.com calendar API
            today = datetime.utcnow().date()
            
            # Hardcoded major events (would be fetched from API)
            fed_events = {
                # Format: YYYY-MM-DD: event_name
                "2026-07-15": "FOMC Meeting",
                "2026-07-20": "CPI Release",
                "2026-08-05": "NFP Employment Report",
            }
            
            event = fed_events.get(str(today))
            return {
                "has_event": event is not None,
                "event_name": event,
                "should_trade": event is None,  # Don't trade on major events
                "risk_level": "HIGH" if event else "NORMAL"
            }
        
        return self._cached_fetch("fed_events", fetch, ttl=3600)
    
    # ---- 2. BITCOIN DOMINANCE ----
    
    def get_bitcoin_dominance(self) -> dict:
        """Fetch Bitcoin dominance % to detect altseason."""
        def fetch():
            try:
                r = requests.get(
                    "https://api.coingecko.com/api/v3/global",
                    timeout=10
                )
                data = r.json()
                btc_dom = data["data"]["btc_market_cap_percentage"]["btc"]
                
                return {
                    "btc_dominance": round(btc_dom, 2),
                    "regime": "BTC_LEADING" if btc_dom > 50 else "ALTSEASON",
                    "trend": "bearish_for_alts" if btc_dom > 50 else "bullish_for_alts",
                    "ethinr_trade_size_multiplier": 0.5 if btc_dom > 50 else 1.0,
                    "xrpinr_trade_size_multiplier": 0.5 if btc_dom > 50 else 1.0
                }
            except:
                return {"btc_dominance": 50, "regime": "UNKNOWN", "trend": "neutral"}
        
        return self._cached_fetch("btc_dominance", fetch, ttl=600)
    
    # ---- 3. FUNDING RATES (Futures Positioning) ----
    
    def get_funding_rates(self) -> dict:
        """Check if futures traders are over-leveraged long/short."""
        def fetch():
            # Simplified: would call Binance Futures API for real data
            # For demo: return synthetic data based on time of day
            hour = datetime.utcnow().hour
            
            # Simulate funding rate cycle
            base_funding = -0.0005 + (0.001 * (hour % 8) / 8)
            
            return {
                "btc_funding_rate": round(base_funding, 6),
                "eth_funding_rate": round(base_funding * 1.2, 6),
                "xrp_funding_rate": round(base_funding * 0.8, 6),
                "squeeze_signal": "IMMINENT" if base_funding < -0.001 else "NONE",
                "long_leverage_ratio": 0.65 if base_funding < -0.001 else 0.50,
                "trade_bias": "LONG" if base_funding < -0.001 else "NEUTRAL"
            }
        
        return self._cached_fetch("funding_rates", fetch, ttl=300)
    
    # ---- 4. VOLATILITY METRICS ----
    
    def get_volatility_metrics(self, closes: list[float]) -> dict:
        """Calculate 4h and 1h volatility to gate entry."""
        def fetch():
            if len(closes) < 20:
                return {
                    "vol_4h_pct": 0,
                    "vol_1h_pct": 0,
                    "volatility_regime": "INSUFFICIENT_DATA",
                    "should_trade": True,
                    "position_size_multiplier": 0.5
                }
            
            # Calculate 4h volatility (last 4 hours = 4 1h candles)
            closes_4h = closes[-4:] if len(closes) >= 4 else closes
            vol_4h = (max(closes_4h) - min(closes_4h)) / min(closes_4h) * 100 if closes_4h else 0
            
            # Calculate 1h volatility (last hour = 1 candle, use close-to-close)
            vol_1h = 0
            if len(closes) >= 2:
                recent_change = abs(closes[-1] - closes[-2]) / closes[-2] * 100
                vol_1h = recent_change
            
            return {
                "vol_4h_pct": round(vol_4h, 2),
                "vol_1h_pct": round(vol_1h, 2),
                "volatility_regime": "LOW" if vol_4h < 0.5 else "MEDIUM" if vol_4h < 2.0 else "HIGH",
                "should_trade": vol_4h > 0.3,  # Don't trade if too quiet
                "position_size_multiplier": min(1.0, vol_4h / 1.0)  # Scale position with volatility
            }
        
        return fetch()
    
    # ---- 5. ON-CHAIN FLOW DETECTION ----
    
    def get_onchain_signals(self) -> dict:
        """Simplified on-chain metrics."""
        def fetch():
            # In production: call Glassnode or CryptoQuant
            # For now: synthetic signal
            hour = datetime.utcnow().hour
            
            # Simulate whale activity pattern
            large_transfer_detected = (hour % 6) < 2  # Activity in first 2h of 6h cycle
            
            return {
                "large_transfer_detected": large_transfer_detected,
                "exchange_inflow_signal": "SELL_PRESSURE" if large_transfer_detected else "NEUTRAL",
                "whale_accumulation": "NO" if large_transfer_detected else "POSSIBLE",
                "front_run_opportunity": large_transfer_detected,
                "suggested_action": "TAKE_SHORT" if large_transfer_detected else "HOLD"
            }
        
        return fetch()
    
    # ---- COMBINED DECISION FILTER ----
    
    def get_trading_decision_filters(self, closes: list[float]) -> dict:
        """Combine all external data into trading filters."""
        fed = self.get_fed_events_today()
        btc_dom = self.get_bitcoin_dominance()
        funding = self.get_funding_rates()
        vol = self.get_volatility_metrics(closes)
        onchain = self.get_onchain_signals()
        
        # Decision logic
        filters = {
            "fed_event_blocker": not fed["should_trade"],
            "volatility_gate": not vol["should_trade"],
            "btc_dominance_warning": btc_dom["regime"] == "BTC_LEADING",
            "funding_rate_bias": funding["trade_bias"],
            "onchain_front_run": onchain["front_run_opportunity"],
        }
        
        # Overall verdict
        can_trade = not (filters["fed_event_blocker"] or filters["volatility_gate"])
        
        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "can_trade": can_trade,
            "filters": filters,
            "position_size_multiplier": (
                vol["position_size_multiplier"] *
                btc_dom.get("ethinr_trade_size_multiplier", 1.0)
            ),
            "external_data": {
                "fed": fed,
                "btc_dominance": btc_dom,
                "funding_rates": funding,
                "volatility": vol,
                "onchain": onchain
            },
            "decision_reason": self._explain_decision(fed, vol, btc_dom, funding, onchain)
        }
    
    def _explain_decision(self, fed, vol, btc_dom, funding, onchain):
        """Explain why trading is allowed/blocked."""
        reasons = []
        
        if not fed["should_trade"]:
            reasons.append(f"❌ Fed event today: {fed['event_name']}")
        else:
            reasons.append("✓ No major Fed events")
        
        if not vol["should_trade"]:
            reasons.append(f"❌ Low volatility ({vol['vol_4h_pct']}%) — consolidation, skip")
        else:
            reasons.append(f"✓ Good volatility ({vol['vol_4h_pct']}%)")
        
        if btc_dom["regime"] == "BTC_LEADING":
            reasons.append("⚠️  BTC dominance high — reduce altcoin position size")
        else:
            reasons.append("✓ Altseason active — full position sizes")
        
        if funding["trade_bias"] == "LONG":
            reasons.append("📈 Funding rates suggest long squeeze incoming")
        
        if onchain["front_run_opportunity"]:
            reasons.append("🐋 Whale activity detected — front-run opportunity")
        
        return " | ".join(reasons)

if __name__ == "__main__":
    fetcher = ExternalDataFetcher()
    
    # Test
    test_closes = [100 + i*0.5 for i in range(50)]
    decision = fetcher.get_trading_decision_filters(test_closes)
    
    print(json.dumps(decision, indent=2))
