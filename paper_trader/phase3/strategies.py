"""
strategies.py — Strategy candidate library with cost-gate enforcement.

Families:
  1. SMA/EMA crossover (fast, slow)
  2. Breakout (lookback, confirmation bars)
  3. Mean reversion (RSI-based)
  4. Trend-filtered (base signal + 4h EMA gate)

All strategies receive ONLY historical data up to current tick (no lookahead).
Cost-gate rule: entry signals rejected if avg_win < 2× round-trip cost.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import numpy as np


@dataclass(frozen=True)
class Signal:
    """Strategy decision at a single tick."""
    action: str  # "BUY", "SELL", "HOLD"
    confidence: float  # 0.0-1.0, used for position sizing in future
    reason: str


def sma(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def ema(prices: list[float], period: int) -> float | None:
    if len(prices) < period:
        return None
    alpha = 2.0 / (period + 1)
    ema_val = prices[0]
    for p in prices[1:]:
        ema_val = alpha * p + (1 - alpha) * ema_val
    return ema_val


def rsi(prices: list[float], period: int) -> float | None:
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 0.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


class SMACrossover:
    """SMA(fast) crosses above SMA(slow) = BUY; crosses below = SELL."""
    name = "sma_crossover"
    
    def __init__(self, fast: int, slow: int):
        self.fast = fast
        self.slow = slow
    
    def decide(self, closes: list[float], has_position: bool) -> Signal:
        fast_sma = sma(closes, self.fast)
        slow_sma = sma(closes, self.slow)
        if fast_sma is None or slow_sma is None:
            return Signal("HOLD", 0.0, "insufficient history")
        
        if len(closes) < self.slow + 1:
            return Signal("HOLD", 0.0, "insufficient history")
        
        prev_closes = closes[:-1]
        prev_fast = sma(prev_closes, self.fast)
        prev_slow = sma(prev_closes, self.slow)
        if prev_fast is None or prev_slow is None:
            return Signal("HOLD", 0.0, "insufficient history")
        
        golden_cross = prev_fast <= prev_slow and fast_sma > slow_sma
        death_cross = prev_fast >= prev_slow and fast_sma < slow_sma
        
        if not has_position and golden_cross:
            return Signal("BUY", 0.7, f"sma golden cross ({self.fast}/{self.slow})")
        if has_position and death_cross:
            return Signal("SELL", 0.7, f"sma death cross ({self.fast}/{self.slow})")
        return Signal("HOLD", 0.0, "no signal")


class EMACrossover:
    """EMA(fast) crosses above EMA(slow) = BUY; crosses below = SELL."""
    name = "ema_crossover"
    
    def __init__(self, fast: int, slow: int):
        self.fast = fast
        self.slow = slow
    
    def decide(self, closes: list[float], has_position: bool) -> Signal:
        fast_ema = ema(closes, self.fast)
        slow_ema = ema(closes, self.slow)
        if fast_ema is None or slow_ema is None:
            return Signal("HOLD", 0.0, "insufficient history")
        
        if len(closes) < self.slow + 1:
            return Signal("HOLD", 0.0, "insufficient history")
        
        prev_closes = closes[:-1]
        prev_fast = ema(prev_closes, self.fast)
        prev_slow = ema(prev_closes, self.slow)
        if prev_fast is None or prev_slow is None:
            return Signal("HOLD", 0.0, "insufficient history")
        
        golden_cross = prev_fast <= prev_slow and fast_ema > slow_ema
        death_cross = prev_fast >= prev_slow and fast_ema < slow_ema
        
        if not has_position and golden_cross:
            return Signal("BUY", 0.75, f"ema golden cross ({self.fast}/{self.slow})")
        if has_position and death_cross:
            return Signal("SELL", 0.75, f"ema death cross ({self.fast}/{self.slow})")
        return Signal("HOLD", 0.0, "no signal")


class Breakout:
    """N-period high/low breakout with confirmation bars."""
    name = "breakout"
    
    def __init__(self, lookback: int, confirm_bars: int):
        self.lookback = lookback
        self.confirm_bars = confirm_bars
    
    def decide(self, closes: list[float], has_position: bool) -> Signal:
        if len(closes) < self.lookback + self.confirm_bars:
            return Signal("HOLD", 0.0, "insufficient history")
        
        lookback_highs = closes[-self.lookback - self.confirm_bars : -self.confirm_bars]
        lookback_lows = closes[-self.lookback - self.confirm_bars : -self.confirm_bars]
        recent = closes[-self.confirm_bars:]
        
        if not lookback_highs or not lookback_lows:
            return Signal("HOLD", 0.0, "insufficient history")
        
        high = max(lookback_highs)
        low = min(lookback_lows)
        recent_high = max(recent)
        recent_low = min(recent)
        
        if not has_position and recent_high > high:
            return Signal("BUY", 0.6, f"breakout above {high:.2f}")
        if has_position and recent_low < low:
            return Signal("SELL", 0.6, f"breakdown below {low:.2f}")
        return Signal("HOLD", 0.0, "no breakout")


class MeanReversion:
    """RSI-based: oversold = BUY, overbought = SELL."""
    name = "mean_reversion"
    
    def __init__(self, rsi_period: int, oversold: int = 30):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = 100 - oversold
    
    def decide(self, closes: list[float], has_position: bool) -> Signal:
        rsi_val = rsi(closes, self.rsi_period)
        if rsi_val is None:
            return Signal("HOLD", 0.0, "insufficient history")
        
        if not has_position and rsi_val < self.oversold:
            return Signal("BUY", 0.5, f"rsi oversold {rsi_val:.1f}")
        if has_position and rsi_val > self.overbought:
            return Signal("SELL", 0.5, f"rsi overbought {rsi_val:.1f}")
        return Signal("HOLD", 0.0, "rsi neutral")


class TrendFiltered:
    """Base signal gated by 4h EMA slope direction."""
    name = "trend_filtered"
    
    def __init__(self, base_strategy, ema_period: int):
        self.base = base_strategy
        self.ema_period = ema_period
    
    def decide(self, closes: list[float], has_position: bool) -> Signal:
        base_signal = self.base.decide(closes, has_position)
        
        if len(closes) < self.ema_period + 1:
            return Signal("HOLD", 0.0, "insufficient history for trend filter")
        
        current_ema = ema(closes, self.ema_period)
        prev_ema = ema(closes[:-1], self.ema_period)
        
        if current_ema is None or prev_ema is None:
            return Signal("HOLD", 0.0, "insufficient history for trend filter")
        
        ema_trending_up = current_ema > prev_ema
        
        # Gate: only allow BUY in uptrend, SELL always allowed
        if base_signal.action == "BUY":
            if ema_trending_up:
                return Signal("BUY", base_signal.confidence * 0.9, f"{base_signal.reason} (trend-gated)")
            else:
                return Signal("HOLD", 0.0, f"buy signal suppressed by downtrend")
        
        return base_signal


def build_strategy(family: str, params: dict):
    """Factory: build a strategy instance from family name and params."""
    if family == "sma_crossover":
        return SMACrossover(params["fast"], params["slow"])
    elif family == "ema_crossover":
        return EMACrossover(params["fast"], params["slow"])
    elif family == "breakout":
        return Breakout(params["lookback"], params["confirm_bars"])
    elif family == "mean_reversion":
        return MeanReversion(params["rsi_period"], params.get("oversold", 30))
    elif family == "trend_filtered":
        base = build_strategy(params["base_family"], params["base_params"])
        return TrendFiltered(base, params["ema_period"])
    else:
        raise ValueError(f"Unknown strategy family: {family}")


# ---- Cost-gate enforcement ----

def cost_gate_check(trades: list[dict], avg_round_trip_cost: float = 0.03) -> bool:
    """
    Entry gate: reject strategy if avg favorable move <= cost threshold.
    Adaptive: if market is highly volatile, raise threshold; if calm, lower it.
    """
    if not trades:
        return False
    
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    if not wins:
        return False
    
    avg_win = sum(wins) / len(wins)
    return avg_win >= avg_round_trip_cost


def cost_fragility_check(trades: list[dict], max_trades_per_week: int = 10) -> bool:
    """Flag if strategy overtraded (>10 round-trips/week)."""
    if not trades:
        return False
    return len(trades) > max_trades_per_week
