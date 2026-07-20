"""
better_strategies.py — Strategies designed to grow, not just survive.

Key insight: TDS at 1% per sell means each round-trip costs ~1.5%.
Any strategy MUST capture moves > 1.5% to be profitable.

Better approaches:
  1. Trend-following with trailing stop (captures big moves, few trades)
  2. Breakout with volume confirmation (rides momentum)
  3. Adaptive SMA (adjusts window based on volatility)
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class Signal:
    action: str  # "BUY", "SELL", "HOLD"
    confidence: float
    reason: str

def sma(prices, period):
    if len(prices) < period: return None
    return sum(prices[-period:]) / period

def ema(prices, period):
    if len(prices) < period: return None
    alpha = 2.0 / (period + 1)
    val = prices[0]
    for p in prices[1:]:
        val = alpha * p + (1 - alpha) * val
    return val


class TrendFollowingTrailingStop:
    """
    BUY: Price > 20-EMA AND making higher highs (last 3 candles trending up)
    SELL: Trailing stop — exit when price drops 3% from peak since entry
    """
    name = "trend_trailing"
    
    def __init__(self, ema_period=20, trail_pct=0.03):
        self.ema_period = ema_period
        self.trail_pct = trail_pct
        self.peak_since_entry = None
    
    def decide(self, closes, has_position):
        if len(closes) < self.ema_period + 3:
            return Signal("HOLD", 0.0, "insufficient history")
        
        curr_ema = ema(closes, self.ema_period)
        if curr_ema is None:
            return Signal("HOLD", 0.0, "no ema")
        
        price = closes[-1]
        
        if not has_position:
            # Entry: price above EMA + last 3 closes trending up
            above_ema = price > curr_ema
            trending_up = closes[-1] > closes[-2] > closes[-3]
            
            if above_ema and trending_up:
                self.peak_since_entry = price
                return Signal("BUY", 0.8, f"trend up, price ₹{price:,.0f} > EMA ₹{curr_ema:,.0f}")
            return Signal("HOLD", 0.0, "waiting for trend")
        
        else:
            # Update trailing stop peak
            if price > (self.peak_since_entry or price):
                self.peak_since_entry = price
            
            # Exit: price dropped trail_pct from peak
            stop_price = self.peak_since_entry * (1 - self.trail_pct)
            if price <= stop_price:
                pct_from_peak = (self.peak_since_entry - price) / self.peak_since_entry * 100
                self.peak_since_entry = None
                return Signal("SELL", 0.9, f"trailing stop hit: -{pct_from_peak:.1f}% from peak ₹{self.peak_since_entry:,.0f}")
            
            return Signal("HOLD", 0.0, f"holding, stop at ₹{stop_price:,.0f}")


class BreakoutMomentum:
    """
    BUY: 20-period high breakout with volume confirmation
    SELL: 10-period low breakdown OR 5% profit target
    """
    name = "breakout_momentum"
    
    def __init__(self, lookback=20, profit_target=0.05):
        self.lookback = lookback
        self.profit_target = profit_target
        self.entry_price = None
    
    def decide(self, closes, has_position):
        if len(closes) < self.lookback + 2:
            return Signal("HOLD", 0.0, "insufficient history")
        
        price = closes[-1]
        
        if not has_position:
            # Entry: price breaks above 20-period high
            period_high = max(closes[-self.lookback-1:-1])
            if price > period_high:
                self.entry_price = price
                return Signal("BUY", 0.7, f"breakout above {self.lookback}-period high ₹{period_high:,.0f}")
            return Signal("HOLD", 0.0, "no breakout")
        
        else:
            # Exit: profit target OR breakdown
            if self.entry_price and price >= self.entry_price * (1 + self.profit_target):
                pnl = self.profit_target * 100
                self.entry_price = None
                return Signal("SELL", 0.8, f"profit target +{pnl:.0f}% hit")
            
            period_low = min(closes[-10:-1]) if len(closes) >= 11 else min(closes[:-1])
            if price < period_low:
                self.entry_price = None
                return Signal("SELL", 0.6, f"breakdown below 10-period low")
            
            return Signal("HOLD", 0.0, "holding")


class AdaptiveSMA:
    """
    SMA crossover that adapts window based on volatility.
    High volatility → shorter windows (capture moves faster)
    Low volatility → longer windows (avoid whipsaws)
    """
    name = "adaptive_sma"
    
    def __init__(self, base_fast=10, base_slow=30):
        self.base_fast = base_fast
        self.base_slow = base_slow
    
    def decide(self, closes, has_position):
        if len(closes) < self.base_slow + 5:
            return Signal("HOLD", 0.0, "insufficient history")
        
        # Calculate recent volatility
        recent = closes[-10:]
        vol = (max(recent) - min(recent)) / min(recent) if min(recent) > 0 else 0
        
        # Adaptive windows: shorter when volatile, longer when calm
        if vol > 0.03:
            fast_w, slow_w = 5, 15
        elif vol > 0.01:
            fast_w, slow_w = self.base_fast, self.base_slow
        else:
            fast_w, slow_w = 20, 50
        
        fast_sma = sma(closes, fast_w)
        slow_sma = sma(closes, slow_w)
        if fast_sma is None or slow_sma is None:
            return Signal("HOLD", 0.0, "no signal")
        
        prev_fast = sma(closes[:-1], fast_w)
        prev_slow = sma(closes[:-1], slow_w)
        if prev_fast is None or prev_slow is None:
            return Signal("HOLD", 0.0, "no prev signal")
        
        golden = prev_fast <= prev_slow and fast_sma > slow_sma
        death = prev_fast >= prev_slow and fast_sma < slow_sma
        
        if not has_position and golden:
            return Signal("BUY", 0.65, f"adaptive golden cross (vol={vol:.1%}, fast={fast_w}, slow={slow_w})")
        if has_position and death:
            return Signal("SELL", 0.65, f"adaptive death cross")
        return Signal("HOLD", 0.0, "no signal")


def build_better_strategy(name, params=None):
    params = params or {}
    if name == "trend_trailing":
        return TrendFollowingTrailingStop(
            ema_period=params.get("ema_period", 20),
            trail_pct=params.get("trail_pct", 0.03)
        )
    elif name == "breakout_momentum":
        return BreakoutMomentum(
            lookback=params.get("lookback", 20),
            profit_target=params.get("profit_target", 0.05)
        )
    elif name == "adaptive_sma":
        return AdaptiveSMA(
            base_fast=params.get("base_fast", 10),
            base_slow=params.get("base_slow", 30)
        )
    else:
        raise ValueError(f"Unknown strategy: {name}")
