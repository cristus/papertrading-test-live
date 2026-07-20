"""market_data.py — CoinDCX PUBLIC market-data connector. No auth, ever."""
from __future__ import annotations
import time
from typing import Any
import requests

_BASE = "https://api.coindcx.com"
_PUBLIC_DATA = "https://public.coindcx.com"

_ALLOWED_PUBLIC_PATHS = {
    "/exchange/ticker",
    "/exchange/v1/markets_details",
    "/market_data/candles",
}


class PublicMarketData:
    """Read-only public market data. No credentials, no order methods."""

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "paper-trader-public/1.0"})

    def _get(self, base: str, path: str, params: dict | None = None) -> Any:
        if path not in _ALLOWED_PUBLIC_PATHS:
            raise ValueError(f"Refused: '{path}' is not a public market-data path.")
        url = base + path
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_ticker(self, symbol: str | None = None) -> Any:
        data = self._get(_BASE, "/exchange/ticker")
        if symbol is None:
            return data
        for row in data:
            if row.get("market") == symbol:
                return row
        raise KeyError(f"Symbol {symbol} not found in public ticker.")

    def get_market_details(self, symbol: str) -> dict:
        data = self._get(_BASE, "/exchange/v1/markets_details")
        for row in data:
            if row.get("coindcx_name") == symbol or row.get("symbol") == symbol:
                return {
                    "symbol": symbol,
                    "min_notional": float(row.get("min_notional", 0) or 0),
                    "min_quantity": float(row.get("min_quantity", 0) or 0),
                    "step": float(row.get("step", 0) or 0),
                    "base_currency_precision": int(row.get("base_currency_precision", 2)),
                    "target_currency_precision": int(row.get("target_currency_precision", 8)),
                    "pair": row.get("pair"),
                    "status": row.get("status"),
                }
        raise KeyError(f"Market details for {symbol} not found.")

    def get_candles(self, pair: str, interval: str = "5m", limit: int = 300) -> list[dict]:
        raw = self._get(_PUBLIC_DATA, "/market_data/candles",
                        params={"pair": pair, "interval": interval, "limit": limit})
        rows = [
            {
                "time": int(c["time"]),
                "open": float(c["open"]),
                "high": float(c["high"]),
                "low": float(c["low"]),
                "close": float(c["close"]),
                "volume": float(c["volume"]),
            }
            for c in raw
        ]
        rows.sort(key=lambda r: r["time"])
        return rows

    def live_snapshot(self, symbol: str) -> dict:
        t = self.get_ticker(symbol)
        return {
            "ts": int(t.get("timestamp", int(time.time()))) * 1000,
            "last": float(t["last_price"]),
            "bid": float(t["bid"]),
            "ask": float(t["ask"]),
            "volume": float(t.get("volume", 0) or 0),
        }
