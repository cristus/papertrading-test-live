"""broker.py — Paper (simulated) broker. NEVER submits orders to CoinDCX.

Applies, per fill: bid-ask spread, slippage, taker fee, TDS (on sells).
Enforces: 10% capital cap, exchange min-notional/qty rejection (never
relaxes the cap to meet the minimum), one open position per agent,
insufficient-funds rejection.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass
class Economics:
    taker_fee_pct: float
    spread_pct: float
    slippage_pct: float
    tds_pct: float


@dataclass
class MarketRules:
    min_notional: float
    min_quantity: float
    step: float


@dataclass
class FillResult:
    accepted: bool
    side: str
    reason: str
    market_price: float
    exec_price: float
    quantity: float
    gross_amount: float
    fee: float
    tds: float
    slippage_cost: float
    cash_after: float
    position_after: float

    def as_detail(self) -> dict:
        return asdict(self)


class PaperBroker:
    """Simulated fills only. No network, no orders, no auth."""

    def __init__(self, econ: Economics, rules: MarketRules, max_frac: float):
        self.econ = econ
        self.rules = rules
        self.max_frac = max_frac

    def _round_qty(self, qty: float) -> float:
        step = self.rules.step or 0.0
        if step <= 0:
            return qty
        return (int(qty / step)) * step

    def simulate_buy(self, ref_price: float, cash: float, position_qty: float,
                     capital_base: float) -> FillResult:
        if position_qty > 0:
            return self._reject("BUY", ref_price, cash, position_qty,
                                "position already open (max 1)")
        budget = self.max_frac * capital_base
        if budget > cash:
            budget = cash
        exec_price = ref_price * (1 + self.econ.spread_pct + self.econ.slippage_pct)
        slippage_cost_per_unit = exec_price - ref_price
        raw_qty = budget / (exec_price * (1 + self.econ.taker_fee_pct))
        qty = self._round_qty(raw_qty)
        notional = qty * exec_price

        if qty < self.rules.min_quantity or notional < self.rules.min_notional:
            return self._reject(
                "BUY", ref_price, cash, position_qty,
                f"min-order conflict: qty={qty:.8f}<min_qty={self.rules.min_quantity} "
                f"or notional={notional:.2f}<min_notional={self.rules.min_notional} "
                f"at 10% cap (budget={budget:.2f}); trade rejected, 10% rule preserved")

        fee = notional * self.econ.taker_fee_pct
        total_cost = notional + fee
        if total_cost > cash + 1e-9:
            return self._reject("BUY", ref_price, cash, position_qty,
                                f"insufficient funds: need {total_cost:.2f}, have {cash:.2f}")

        cash_after = cash - total_cost
        return FillResult(
            accepted=True, side="BUY", reason="filled", market_price=ref_price,
            exec_price=exec_price, quantity=qty, gross_amount=notional, fee=fee,
            tds=0.0, slippage_cost=slippage_cost_per_unit * qty,
            cash_after=cash_after, position_after=qty)

    def simulate_sell(self, ref_price: float, cash: float, position_qty: float) -> FillResult:
        if position_qty <= 0:
            return self._reject("SELL", ref_price, cash, position_qty,
                                "no open position to sell")
        exec_price = ref_price * (1 - self.econ.spread_pct - self.econ.slippage_pct)
        slippage_cost_per_unit = ref_price - exec_price
        qty = position_qty
        notional = qty * exec_price
        fee = notional * self.econ.taker_fee_pct
        tds = notional * self.econ.tds_pct
        proceeds = notional - fee - tds
        cash_after = cash + proceeds
        return FillResult(
            accepted=True, side="SELL", reason="filled", market_price=ref_price,
            exec_price=exec_price, quantity=qty, gross_amount=notional, fee=fee,
            tds=tds, slippage_cost=slippage_cost_per_unit * qty,
            cash_after=cash_after, position_after=0.0)

    def _reject(self, side, ref_price, cash, position_qty, reason) -> FillResult:
        return FillResult(
            accepted=False, side=side, reason=reason, market_price=ref_price,
            exec_price=ref_price, quantity=0.0, gross_amount=0.0, fee=0.0, tds=0.0,
            slippage_cost=0.0, cash_after=cash, position_after=position_qty)
