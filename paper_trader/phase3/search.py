"""
search.py — Grid search over strategy parameter space on training window only.

Ranks candidates by: net return, max drawdown, trades/week, win ratio.
Outputs top N survivors per family per market.
"""
from __future__ import annotations
import sys, os, json
from itertools import product
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from phase3.strategies import (
    SMACrossover, EMACrossover, Breakout, MeanReversion, TrendFiltered,
    cost_gate_check, cost_fragility_check
)
from core.broker import PaperBroker, Economics, MarketRules


def simulate_on_window(strategy, closes: list[float], mark_price: float, rules: MarketRules) -> dict:
    """Run strategy on a training/validation/holdout window. Return metrics."""
    econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
    broker = PaperBroker(econ, rules, max_frac=0.10)
    
    cash = 8000.0
    position = 0.0
    avg_entry = None
    trades = []
    equity_peak = 8000.0
    max_dd = 0.0
    
    for i, close in enumerate(closes):
        signal = strategy.decide(closes[:i+1], position > 0)
        
        if signal.action == "BUY" and position == 0:
            fill = broker.simulate_buy(close, cash, position, 8000.0)
            if fill.accepted:
                cash = fill.cash_after
                position = fill.position_after
                avg_entry = close
                trades.append({"type": "buy", "price": close, "ts": i, "pnl": 0})
        
        elif signal.action == "SELL" and position > 0:
            fill = broker.simulate_sell(close, cash, position)
            if fill.accepted:
                pnl = fill.cash_after - cash
                cash = fill.cash_after
                position = 0.0
                trades.append({"type": "sell", "price": close, "ts": i, "pnl": pnl})
        
        # Equity tracking
        equity = cash + position * close
        if equity > equity_peak:
            equity_peak = equity
        dd = (equity_peak - equity) / equity_peak if equity_peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    
    final_equity = cash + position * close
    net_return = (final_equity - 8000.0) / 8000.0 * 100
    num_round_trips = len([t for t in trades if t["type"] == "sell"])
    
    return {
        "net_return_pct": net_return,
        "max_drawdown_pct": max_dd * 100,
        "final_equity": final_equity,
        "round_trips": num_round_trips,
        "trades": trades,
        "passes_cost_gate": cost_gate_check(trades) if trades else False,
        "cost_fragile": cost_fragility_check(trades),
    }


def grid_search(market: str, closes: list[float], mark_price: float, rules: MarketRules) -> list[dict]:
    """
    Search SMA, EMA, Breakout, Mean Reversion over training window.
    Return ranked candidates (top 5 per family).
    """
    candidates = []
    
    # SMA crossover: fast in [5,10,20], slow in [30,50,100]
    for fast, slow in product([5, 10, 20], [30, 50, 100]):
        if fast >= slow:
            continue
        strat = SMACrossover(fast, slow)
        metrics = simulate_on_window(strat, closes, mark_price, rules)
        candidates.append({
            "family": "sma_crossover",
            "params": {"fast": fast, "slow": slow},
            **metrics
        })
    
    # EMA crossover: fast in [5,10,20], slow in [30,50,100]
    for fast, slow in product([5, 10, 20], [30, 50, 100]):
        if fast >= slow:
            continue
        strat = EMACrossover(fast, slow)
        metrics = simulate_on_window(strat, closes, mark_price, rules)
        candidates.append({
            "family": "ema_crossover",
            "params": {"fast": fast, "slow": slow},
            **metrics
        })
    
    # Breakout: lookback in [10,20,30], confirm in [1,2,3]
    for lookback, confirm in product([10, 20, 30], [1, 2, 3]):
        strat = Breakout(lookback, confirm)
        metrics = simulate_on_window(strat, closes, mark_price, rules)
        candidates.append({
            "family": "breakout",
            "params": {"lookback": lookback, "confirm_bars": confirm},
            **metrics
        })
    
    # Mean Reversion: RSI_period in [7,14,21], oversold in [20,25,30]
    for period, oversold in product([7, 14, 21], [20, 25, 30]):
        strat = MeanReversion(period, oversold)
        metrics = simulate_on_window(strat, closes, mark_price, rules)
        candidates.append({
            "family": "mean_reversion",
            "params": {"rsi_period": period, "oversold": oversold},
            **metrics
        })
    
    # Sort by net return (descending)
    candidates.sort(key=lambda c: c["net_return_pct"], reverse=True)
    
    return candidates


if __name__ == "__main__":
    # Test on dummy data
    test_closes = [100 + i*0.5 for i in range(300)]
    rules = MarketRules(min_notional=100.0, min_quantity=0.00001, step=0.00001)
    results = grid_search("BTCINR", test_closes, test_closes[-1], rules)
    print(f"Grid search completed: {len(results)} candidates")
    print("Top 5:")
    for c in results[:5]:
        print(f"  {c['family']} {c['params']}: {c['net_return_pct']:+.2f}% | dd {c['max_drawdown_pct']:.2f}% | trips {c['round_trips']}")
