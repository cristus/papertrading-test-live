"""agent.py — Agent state + lifecycle (death/reproduction) detection.

Death and reproduction thresholds are expressed as FRACTIONS of the
agent's OWN starting capital (from the immutable RiskConfig), so they
scale proportionally across tiers automatically:
  death_equity   = starting_capital * death_equity_fraction   (0.40)
  reproduce_at   = starting_capital * reproduction_equity_fraction (2.00)

Reproduction is LOG-ONLY in this phase: crossing the threshold is
recorded in the ledger as a REPRODUCE_SIGNAL event (including what the
child's capital would be = parent.starting_capital * child_fraction),
but no live agent is spawned and no capital is actually deducted.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class AgentState:
    id: int
    experiment_id: int
    cohort: str
    starting_capital: float
    cash: float
    position_qty: float
    avg_entry_price: float | None
    alive: bool = True
    reproduced_logged: bool = False  # only log the crossing once
    death_reason: str | None = None
    parent_agent_id: int | None = None

    def equity(self, mark_price: float) -> float:
        pos_value = self.position_qty * mark_price if self.position_qty else 0.0
        return self.cash + pos_value


class LifecycleChecker:
    """Evaluates death/reproduction thresholds against a RiskConfig."""

    def __init__(self, death_fraction: float, reproduction_fraction: float,
                child_fraction: float):
        self.death_fraction = death_fraction
        self.reproduction_fraction = reproduction_fraction
        self.child_fraction = child_fraction

    def death_threshold(self, starting_capital: float) -> float:
        return starting_capital * self.death_fraction

    def reproduction_threshold(self, starting_capital: float) -> float:
        return starting_capital * self.reproduction_fraction

    def child_capital(self, parent_starting_capital: float) -> float:
        return parent_starting_capital * self.child_fraction

    def check_death(self, agent: AgentState, equity: float) -> str | None:
        if not agent.alive:
            return None
        thresh = self.death_threshold(agent.starting_capital)
        if equity <= thresh:
            return f"equity {equity:.2f} <= death threshold {thresh:.2f} " \
                   f"({self.death_fraction:.0%} of starting capital {agent.starting_capital:.2f})"
        return None

    def check_reproduction(self, agent: AgentState, equity: float) -> str | None:
        if not agent.alive or agent.reproduced_logged:
            return None
        thresh = self.reproduction_threshold(agent.starting_capital)
        if equity >= thresh:
            child_cap = self.child_capital(agent.starting_capital)
            return f"equity {equity:.2f} >= reproduction threshold {thresh:.2f} " \
                   f"({self.reproduction_fraction:.0%} of starting capital {agent.starting_capital:.2f}); " \
                   f"would spawn child with capital {child_cap:.2f} (LOG ONLY, not spawned)"
        return None
