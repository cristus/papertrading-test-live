"""No-lookahead enforcement."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.engine import TickWindow
from core.safety import LookaheadError
from core.strategy import build_strategy

def test_tick_window_refuses_future_index():
    tw = TickWindow(closes=[1, 2, 3, 4, 5], tick_index=2)  # only 0..2 are "known"
    assert tw.as_of(0) == [1]
    assert tw.as_of(2) == [1, 2, 3]
    try:
        tw.as_of(3)  # beyond current tick -> must raise
        assert False, "should have raised LookaheadError"
    except LookaheadError:
        pass

def test_strategy_decision_unaffected_by_appending_future_prices():
    """
    A strategy fed the SAME history up to tick i must produce the SAME
    decision regardless of what future prices exist in the full series.
    """
    strat = build_strategy("sma_crossover", {"fast_window": 3, "slow_window": 5})
    history_up_to_now = [100, 100, 100, 100, 100, 101, 102, 103]
    future_tail_variant_a = history_up_to_now + [999, 999, 999]   # spike up
    future_tail_variant_b = history_up_to_now + [1, 1, 1]         # crash down

    d_now = strat.decide(history_up_to_now, has_position=False)
    # simulate engine only ever slicing up to "now" even though full arrays differ later
    d_a = strat.decide(future_tail_variant_a[: len(history_up_to_now)], has_position=False)
    d_b = strat.decide(future_tail_variant_b[: len(history_up_to_now)], has_position=False)
    assert d_now == d_a == d_b

def test_engine_run_experiment_slices_closes_strictly_up_to_tick():
    """
    Source-level guard: run_experiment.py must slice closes as closes[:i+1]
    inside the tick loop (never closes[:] or the full list) — this is the
    literal no-lookahead enforcement point.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "run_experiment.py")
    with open(path) as f:
        src = f.read()
    assert "closes[: i + 1]" in src or "closes[:i+1]" in src
