"""strategy.py — Deterministic baseline strategy: SMA crossover.

NO-LOOKAHEAD BY CONSTRUCTION: the strategy is only ever handed a list of
CLOSED candles up to and including the current tick. It never receives
future data — the engine is responsible for slicing the window before
calling decide(), and this module has no way to reach back into the
raw data source itself (no market_data import here at all).
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyParams:
    fast_window: int
    slow_window: int


def _sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


class SmaCrossoverStrategy:
    """
    Deterministic rule:
      - BUY when fast SMA crosses above slow SMA (golden cross) and agent is flat.
      - SELL when fast SMA crosses below slow SMA (death cross) and agent holds a position.
      - Otherwise HOLD.
    Fully deterministic given the same price history and params — no
    randomness, no hidden state beyond the immutable params.
    """
    name = "sma_crossover"

    def __init__(self, params: StrategyParams):
        self.params = params

    def decide(self, closes_so_far: list[float], has_position: bool) -> str:
        """
        `closes_so_far` MUST already be truncated by the caller (engine) to
        only include ticks up to "now" — this function performs no I/O and
        cannot look beyond what it's given.
        Returns one of: "BUY", "SELL", "HOLD".
        """
        fast = _sma(closes_so_far, self.params.fast_window)
        slow = _sma(closes_so_far, self.params.slow_window)
        if fast is None or slow is None:
            return "HOLD"  # not enough history yet

        # need previous-tick SMAs to detect a crossover, not just current level
        prev_closes = closes_so_far[:-1]
        prev_fast = _sma(prev_closes, self.params.fast_window)
        prev_slow = _sma(prev_closes, self.params.slow_window)
        if prev_fast is None or prev_slow is None:
            return "HOLD"

        golden_cross = prev_fast <= prev_slow and fast > slow
        death_cross = prev_fast >= prev_slow and fast < slow

        if not has_position and golden_cross:
            return "BUY"
        if has_position and death_cross:
            return "SELL"
        return "HOLD"


def build_strategy(name: str, params: dict) -> SmaCrossoverStrategy:
    if name != "sma_crossover":
        raise ValueError(f"Unknown baseline strategy: {name}")
    return SmaCrossoverStrategy(StrategyParams(
        fast_window=int(params["fast_window"]),
        slow_window=int(params["slow_window"]),
    ))
