"""backfill.py — Download + split historical 1h candles (60/20/20)."""
from __future__ import annotations
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from core.market_data import PublicMarketData
from core import db

MARKETS = {"BTCINR": {"pair": "I-BTC_INR", "interval": "1h"},
           "ETHINR": {"pair": "I-ETH_INR", "interval": "1h"},
           "XRPINR": {"pair": "I-XRP_INR", "interval": "1h"}}

def fetch_all_candles(market: str, pair: str, interval: str, max_limit: int = 500) -> list[dict]:
    md = PublicMarketData(timeout=30)
    try:
        candles = md.get_candles(pair, interval=interval, limit=max_limit)
        print(f"  {market}: fetched {len(candles)} candles")
        return candles
    except Exception as e:
        print(f"  {market}: ERROR — {e}")
        return []

def split_chronologically(candles: list[dict], splits=(0.6, 0.2, 0.2)) -> tuple[list, list, list]:
    candles = sorted(candles, key=lambda c: c["time"])
    n = len(candles)
    i1 = int(n * splits[0])
    i2 = int(n * (splits[0] + splits[1]))
    return candles[:i1], candles[i1:i2], candles[i2:]

def backfill_to_db(experiment_id: int, conn) -> dict:
    print("=" * 70)
    print("PHASE 3 — HISTORICAL BACKFILL")
    print("=" * 70)
    
    summary = {}
    market_offsets = {"BTCINR": 0, "ETHINR": 10000, "XRPINR": 20000}
    
    for market, config in MARKETS.items():
        print(f"\nDownloading {market}...")
        candles = fetch_all_candles(market, config["pair"], config["interval"])
        
        if not candles:
            print(f"  SKIP: no candles retrieved")
            summary[market] = {"error": "no data"}
            continue
        
        train, val, hold = split_chronologically(candles)
        offset = market_offsets[market]
        
        # Insert with market-specific offsets to avoid tick_index conflicts
        for i, c in enumerate(train):
            conn.execute(
                "INSERT INTO market_snapshots "
                "(experiment_id, tick_index, ts, open, high, low, close, volume, bid, ask, last, market, source, window) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (experiment_id, offset + i, c["time"], c["open"], c["high"], c["low"], c["close"], c["volume"],
                 c.get("bid", c["close"]), c.get("ask", c["close"]), c["close"], market, "backfill", "train"))
        
        for i, c in enumerate(val):
            conn.execute(
                "INSERT INTO market_snapshots "
                "(experiment_id, tick_index, ts, open, high, low, close, volume, bid, ask, last, market, source, window) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (experiment_id, offset + 1000 + i, c["time"], c["open"], c["high"], c["low"], c["close"], c["volume"],
                 c.get("bid", c["close"]), c.get("ask", c["close"]), c["close"], market, "backfill", "validation"))
        
        for i, c in enumerate(hold):
            conn.execute(
                "INSERT INTO market_snapshots "
                "(experiment_id, tick_index, ts, open, high, low, close, volume, bid, ask, last, market, source, window) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (experiment_id, offset + 2000 + i, c["time"], c["open"], c["high"], c["low"], c["close"],
                 c["volume"], c.get("bid", c["close"]), c.get("ask", c["close"]), c["close"], market, "backfill", "holdout"))
        
        conn.commit()
        
        summary[market] = {
            "total_candles": len(candles),
            "train": len(train),
            "validation": len(val),
            "holdout": len(hold),
        }
        
        print(f"  ✓ {len(train)} train | {len(val)} validation | {len(hold)} holdout")
    
    print("\n" + "=" * 70)
    print("BACKFILL COMPLETE")
    print("=" * 70)
    
    return summary
