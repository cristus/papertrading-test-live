"""Insufficient-funds rejection and minimum-order rejection."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.broker import PaperBroker, Economics, MarketRules

def make_broker(min_notional=100.0, min_quantity=0.00001, step=0.00001, max_frac=0.10):
    econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
    rules = MarketRules(min_notional=min_notional, min_quantity=min_quantity, step=step)
    return PaperBroker(econ, rules, max_frac=max_frac)

def test_insufficient_funds_rejected():
    b = make_broker()
    # cash is far below what's needed to even meet min_notional after 10% cap
    fill = b.simulate_buy(ref_price=6400000.0, cash=0.50, position_qty=0.0, capital_base=2000.0)
    assert fill.accepted is False
    assert "insufficient" in fill.reason.lower() or "min-order" in fill.reason.lower()

def test_min_order_conflict_rejected_not_relaxed():
    """
    If 10% of capital can't reach the exchange minimum notional, the trade
    must be REJECTED — the 10% cap must never be relaxed to force the trade.
    """
    # tiny capital base: 10% of 500 = 50, but min_notional is 100 -> must reject
    b = make_broker(min_notional=100.0)
    fill = b.simulate_buy(ref_price=6400000.0, cash=500.0, position_qty=0.0, capital_base=500.0)
    assert fill.accepted is False
    assert "min-order conflict" in fill.reason
    # confirm the 10% rule text is present, proving we didn't silently raise the budget
    assert "10% rule preserved" in fill.reason
    assert fill.quantity == 0.0
    assert fill.cash_after == 500.0  # untouched

def test_sell_with_no_position_rejected():
    b = make_broker()
    fill = b.simulate_sell(ref_price=6400000.0, cash=2000.0, position_qty=0.0)
    assert fill.accepted is False
    assert "no open position" in fill.reason

def test_second_buy_rejected_one_position_rule():
    b = make_broker()
    fill1 = b.simulate_buy(ref_price=6400000.0, cash=2000.0, position_qty=0.0, capital_base=2000.0)
    assert fill1.accepted
    fill2 = b.simulate_buy(ref_price=6400000.0, cash=fill1.cash_after, position_qty=fill1.position_after,
                           capital_base=2000.0)
    assert fill2.accepted is False
    assert "position already open" in fill2.reason
