"""engine.py — Simulation engine: tick loop, snapshot-once-per-tick,
no-lookahead enforcement, cohort orchestration, equity-curve + benchmark
recording.

Key safety properties:
  * Market data is fetched ONCE per tick into market_snapshots; every
    agent in every cohort reads from that same stored row. No agent
    polls CoinDCX individually (this module is the only caller of
    market_data.get_candles / live_snapshot).
  * NO-LOOKAHEAD: strategies are handed price history truncated to
    `closes[:tick_index+1]` — never anything beyond the current tick.
  * Emergency pause is checked before every tick and before every
    simulated order; if tripped, the run halts immediately.
  * Every decision/fill/rejection/death/reproduction is appended to the
    ledger (never updated/deleted).
"""
from __future__ import annotations
from dataclasses import dataclass
import json

from core import db
from core.broker import PaperBroker, Economics, MarketRules, FillResult
from core.strategy import build_strategy
from core.agent import AgentState, LifecycleChecker
from core.safety import RiskConfig, EmergencyPause, LookaheadError


@dataclass
class TickWindow:
    """A no-lookahead view: only data up to (and including) `tick_index`."""
    closes: list[float]
    tick_index: int

    def as_of(self, i: int) -> list[float]:
        if i > self.tick_index:
            raise LookaheadError(f"Requested index {i} beyond current tick {self.tick_index}")
        return self.closes[: i + 1]


class Engine:
    def __init__(self, conn, experiment_id: int, risk: RiskConfig,
                econ: Economics, rules: MarketRules, strategy_name: str,
                strategy_params: dict, pause: EmergencyPause):
        self.conn = conn
        self.experiment_id = experiment_id
        self.risk = risk
        self.econ = econ
        self.rules = rules
        self.pause = pause
        self.strategy = build_strategy(strategy_name, strategy_params)
        self.lifecycle = LifecycleChecker(
            death_fraction=risk.death_equity_fraction,
            reproduction_fraction=risk.reproduction_equity_fraction,
            child_fraction=risk.reproduction_child_fraction,
        )
        self.broker = PaperBroker(econ, rules, max_frac=risk.max_capital_fraction_per_trade)

    # ---- market snapshot ingestion (ONCE per tick, all agents share it) --

    def store_candles_as_snapshots(self, candles: list[dict]) -> None:
        for i, c in enumerate(candles):
            self.conn.execute(
                "INSERT OR IGNORE INTO market_snapshots "
                "(experiment_id, tick_index, ts, open, high, low, close, volume, bid, ask, last) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (self.experiment_id, i, c["time"], c["open"], c["high"], c["low"],
                 c["close"], c["volume"], c.get("bid", c["close"]), c.get("ask", c["close"]),
                 c["close"]),
            )
        self.conn.commit()

    def load_snapshots(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM market_snapshots WHERE experiment_id=? ORDER BY tick_index",
            (self.experiment_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---- per-agent tick processing --------------------------------------

    def run_agent_tick(self, agent: AgentState, closes_so_far: list[float],
                       tick_index: int, ts: int, mark_price: float) -> None:
        if self.pause.is_paused:
            db.insert_ledger(self.conn, experiment_id=self.experiment_id, agent_id=agent.id,
                             ts=ts, tick_index=tick_index, event_type="PAUSED", side=None,
                             market_price=mark_price, quantity=0, gross_amount=0, fee=0, tds=0,
                             slippage_cost=0, cash_balance=agent.cash, position_qty=agent.position_qty,
                             reason=self.pause.reason(), detail_json=None)
            return
        if not agent.alive:
            return

        has_position = agent.position_qty > 0
        decision = self.strategy.decide(closes_so_far, has_position)

        db.insert_ledger(self.conn, experiment_id=self.experiment_id, agent_id=agent.id,
                         ts=ts, tick_index=tick_index, event_type="DECISION", side=decision,
                         market_price=mark_price, quantity=0, gross_amount=0, fee=0, tds=0,
                         slippage_cost=0, cash_balance=agent.cash, position_qty=agent.position_qty,
                         reason="strategy_signal", detail_json=None)

        fill: FillResult | None = None
        if decision == "BUY" and not self.pause.is_paused:
            fill = self.broker.simulate_buy(mark_price, agent.cash, agent.position_qty,
                                            agent.starting_capital)
        elif decision == "SELL" and not self.pause.is_paused:
            fill = self.broker.simulate_sell(mark_price, agent.cash, agent.position_qty)

        if fill is not None:
            event = "FILL" if fill.accepted else "REJECT"
            db.insert_ledger(self.conn, experiment_id=self.experiment_id, agent_id=agent.id,
                             ts=ts, tick_index=tick_index, event_type=event, side=fill.side,
                             market_price=mark_price, quantity=fill.quantity,
                             gross_amount=fill.gross_amount, fee=fill.fee, tds=fill.tds,
                             slippage_cost=fill.slippage_cost, cash_balance=fill.cash_after,
                             position_qty=fill.position_after, reason=fill.reason,
                             detail_json=fill.as_detail())
            if fill.accepted:
                agent.cash = fill.cash_after
                agent.position_qty = fill.position_after
                agent.avg_entry_price = mark_price if fill.side == "BUY" else agent.avg_entry_price

        # lifecycle checks (equity computed fresh, not from cache)
        equity = agent.equity(mark_price)
        death_reason = self.lifecycle.check_death(agent, equity)
        if death_reason:
            agent.alive = False
            agent.death_reason = death_reason
            self.conn.execute(
                "UPDATE agents SET death_ts=?, death_reason=? WHERE id=?",
                (ts, death_reason, agent.id))
            self.conn.commit()
            db.insert_ledger(self.conn, experiment_id=self.experiment_id, agent_id=agent.id,
                             ts=ts, tick_index=tick_index, event_type="DEATH", side=None,
                             market_price=mark_price, quantity=0, gross_amount=0, fee=0, tds=0,
                             slippage_cost=0, cash_balance=agent.cash, position_qty=agent.position_qty,
                             reason=death_reason, detail_json=None)
            return

        repro_reason = self.lifecycle.check_reproduction(agent, equity)
        if repro_reason:
            agent.reproduced_logged = True
            db.insert_ledger(self.conn, experiment_id=self.experiment_id, agent_id=agent.id,
                             ts=ts, tick_index=tick_index, event_type="REPRODUCE_SIGNAL", side=None,
                             market_price=mark_price, quantity=0, gross_amount=0, fee=0, tds=0,
                             slippage_cost=0, cash_balance=agent.cash, position_qty=agent.position_qty,
                             reason=repro_reason, detail_json=None)

    # ---- equity curve + benchmark recording -----------------------------

    def record_equity(self, agent: AgentState, hour_index: int, ts: int, mark_price: float,
                      peak_tracker: dict) -> None:
        equity = agent.equity(mark_price)
        peak = max(peak_tracker.get(agent.id, equity), equity)
        peak_tracker[agent.id] = peak
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        pos_value = agent.position_qty * mark_price if agent.position_qty else 0.0
        self.conn.execute(
            "INSERT INTO equity_curve (experiment_id, agent_id, hour_index, ts, equity, "
            "peak_equity, drawdown, open_position_value) VALUES (?,?,?,?,?,?,?,?)",
            (self.experiment_id, agent.id, hour_index, ts, equity, peak, drawdown, pos_value))

    def record_benchmark(self, cohort: str, starting_capital: float, tick_index: int,
                         ts: int, first_price: float, current_price: float) -> None:
        qty = starting_capital / first_price
        buy_hold_equity = qty * current_price
        self.conn.execute(
            "INSERT INTO benchmarks (experiment_id, cohort, starting_capital, tick_index, ts, "
            "buy_hold_equity) VALUES (?,?,?,?,?,?)",
            (self.experiment_id, cohort, starting_capital, tick_index, ts, buy_hold_equity))
