"""safety.py — SAFETY-CRITICAL. Immutable risk config + emergency pause."""
from __future__ import annotations
import os
from dataclasses import dataclass
import yaml

_RISK_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "risk.yaml")


class SafetyViolation(Exception):
    pass


class LookaheadError(Exception):
    pass


@dataclass(frozen=True)
class RiskConfig:
    emergency_pause: bool
    max_capital_fraction_per_trade: float
    max_open_positions_per_agent: int
    death_equity_fraction: float
    reproduction_equity_fraction: float
    reproduction_child_fraction: float
    allow_real_orders: bool
    allow_authenticated_endpoints: bool
    allow_margin_futures_leverage: bool
    allow_withdraw_transfer: bool

    def assert_safe(self) -> None:
        if self.allow_real_orders:
            raise SafetyViolation("allow_real_orders must be false — paper trading only.")
        if self.allow_authenticated_endpoints:
            raise SafetyViolation("allow_authenticated_endpoints must be false.")
        if self.allow_margin_futures_leverage:
            raise SafetyViolation("margin/futures/leverage are prohibited.")
        if self.allow_withdraw_transfer:
            raise SafetyViolation("withdraw/transfer are prohibited.")
        if not (0 < self.max_capital_fraction_per_trade <= 0.10):
            raise SafetyViolation("max_capital_fraction_per_trade must be in (0, 0.10].")
        if self.max_open_positions_per_agent != 1:
            raise SafetyViolation("max_open_positions_per_agent must be 1.")


def load_risk_config(path: str | None = None) -> RiskConfig:
    p = path or _RISK_PATH
    with open(p, "r") as f:
        raw = yaml.safe_load(f)
    cfg = RiskConfig(
        emergency_pause=bool(raw["emergency_pause"]),
        max_capital_fraction_per_trade=float(raw["max_capital_fraction_per_trade"]),
        max_open_positions_per_agent=int(raw["max_open_positions_per_agent"]),
        death_equity_fraction=float(raw["death_equity_fraction"]),
        reproduction_equity_fraction=float(raw["reproduction_equity_fraction"]),
        reproduction_child_fraction=float(raw["reproduction_child_fraction"]),
        allow_real_orders=bool(raw["allow_real_orders"]),
        allow_authenticated_endpoints=bool(raw["allow_authenticated_endpoints"]),
        allow_margin_futures_leverage=bool(raw["allow_margin_futures_leverage"]),
        allow_withdraw_transfer=bool(raw["allow_withdraw_transfer"]),
    )
    cfg.assert_safe()
    return cfg


class EmergencyPause:
    def __init__(self, initial: bool = False):
        self._paused = bool(initial)
        self._reason = "risk.yaml emergency_pause=true" if initial else ""

    @property
    def is_paused(self) -> bool:
        return self._paused

    def trip(self, reason: str = "manual") -> None:
        self._paused = True
        self._reason = reason

    def reason(self) -> str:
        return self._reason
