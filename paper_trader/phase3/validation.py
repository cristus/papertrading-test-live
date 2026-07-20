"""
validation.py — Validation gate (discard overfitters), holdout test, robustness.

Overfitting gate: discard if validation return drops >50% from training.
Robustness: fee inflation ×1.5, price jitter ±0.1%, regime split, cross-market.
"""
from __future__ import annotations
import sys, os, random
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from phase3.strategies import build_strategy
from phase3.search import simulate_on_window
from core.broker import MarketRules


def validate_candidate(candidate: dict, train_closes: list[float], val_closes: list[float],
                      mark_price: float, rules: MarketRules) -> dict | None:
    """
    Run candidate on validation window.
    Discard if validation return < 50% of training return.
    """
    train_return = candidate["net_return_pct"]
    
    strat = build_strategy(candidate["family"], candidate["params"])
    val_metrics = simulate_on_window(strat, val_closes, mark_price, rules)
    val_return = val_metrics["net_return_pct"]
    
    overfitting_ratio = val_return / train_return if train_return > 0 else 0.0
    
    if overfitting_ratio < 0.5:
        return None  # Discard
    
    return {
        **candidate,
        "val_return_pct": val_return,
        "overfitting_ratio": overfitting_ratio,
        "survived_validation": True
    }


def robustness_fee_inflation(candidate: dict, closes: list[float], mark_price: float,
                             rules: MarketRules, fee_mult: float = 1.5) -> dict:
    """Re-run with fees × 1.5. Must not flip negative."""
    from core.broker import PaperBroker, Economics
    
    econ = Economics(
        taker_fee_pct=0.001 * fee_mult,
        spread_pct=0.0005 * fee_mult,
        slippage_pct=0.001 * fee_mult,
        tds_pct=0.01
    )
    broker = PaperBroker(econ, rules, max_frac=0.10)
    
    strat = build_strategy(candidate["family"], candidate["params"])
    cash = 8000.0
    position = 0.0
    
    for i, close in enumerate(closes):
        signal = strat.decide(closes[:i+1], position > 0)
        if signal.action == "BUY" and position == 0:
            fill = broker.simulate_buy(close, cash, position, 8000.0)
            if fill.accepted:
                cash = fill.cash_after
                position = fill.position_after
        elif signal.action == "SELL" and position > 0:
            fill = broker.simulate_sell(close, cash, position)
            if fill.accepted:
                cash = fill.cash_after
                position = 0.0
    
    final_equity = cash + position * close
    return {"fee_inflated_return": (final_equity - 8000.0) / 8000.0 * 100}


def robustness_price_jitter(candidate: dict, closes: list[float], mark_price: float,
                            rules: MarketRules, jitter_pct: float = 0.001, runs: int = 10) -> dict:
    """Run 10× with entry prices perturbed ±0.1%. Report outcome spread."""
    from core.broker import PaperBroker, Economics
    
    results = []
    for _ in range(runs):
        econ = Economics(taker_fee_pct=0.001, spread_pct=0.0005, slippage_pct=0.001, tds_pct=0.01)
        broker = PaperBroker(econ, rules, max_frac=0.10)
        
        strat = build_strategy(candidate["family"], candidate["params"])
        cash = 8000.0
        position = 0.0
        
        for i, close in enumerate(closes):
            signal = strat.decide(closes[:i+1], position > 0)
            entry_price = close * (1 + random.uniform(-jitter_pct, jitter_pct))
            
            if signal.action == "BUY" and position == 0:
                fill = broker.simulate_buy(entry_price, cash, position, 8000.0)
                if fill.accepted:
                    cash = fill.cash_after
                    position = fill.position_after
            elif signal.action == "SELL" and position > 0:
                fill = broker.simulate_sell(entry_price, cash, position)
                if fill.accepted:
                    cash = fill.cash_after
                    position = 0.0
        
        final_equity = cash + position * close
        results.append((final_equity - 8000.0) / 8000.0 * 100)
    
    return {
        "jitter_mean": sum(results) / len(results),
        "jitter_std": (sum((r - sum(results)/len(results))**2 for r in results) / len(results))**0.5,
        "jitter_min": min(results),
        "jitter_max": max(results)
    }


def robustness_regime_split(candidate: dict, closes: list[float], mark_price: float,
                            rules: MarketRules, ema_period: int = 20) -> dict:
    """Split into trending vs ranging periods. Report separately."""
    from phase3.strategies import ema
    
    strat = build_strategy(candidate["family"], candidate["params"])
    
    # Classify each tick as trending (EMA up) or ranging
    trending_idxs = []
    ranging_idxs = []
    for i in range(ema_period + 1, len(closes)):
        curr_ema = ema(closes[:i+1], ema_period)
        prev_ema = ema(closes[:i], ema_period)
        if curr_ema and prev_ema:
            if curr_ema > prev_ema:
                trending_idxs.append(i)
            else:
                ranging_idxs.append(i)
    
    # Simulate on each regime
    def sim_regime(idxs):
        if not idxs:
            return 0.0
        cash, position = 8000.0, 0.0
        for i in idxs:
            signal = strat.decide(closes[:i+1], position > 0)
            close = closes[i]
            # simplified fill logic
            if signal.action == "BUY" and position == 0:
                position = min(0.001, 0.1 * 8000.0 / close)
                cash -= position * close * 1.001
            elif signal.action == "SELL" and position > 0:
                cash += position * close * 0.999 * 0.99  # sell cost
                position = 0.0
        return (cash + position * closes[-1] - 8000.0) / 8000.0 * 100
    
    return {
        "trending_return": sim_regime(trending_idxs),
        "ranging_return": sim_regime(ranging_idxs)
    }


def cross_market_test(candidate: dict, markets: dict[str, list[float]], rules: MarketRules) -> dict:
    """Run candidate on all markets. Return market-specific results."""
    results = {}
    strat = build_strategy(candidate["family"], candidate["params"])
    for market, closes in markets.items():
        if len(closes) >= 50:  # minimum data
            metrics = simulate_on_window(strat, closes, closes[-1], rules)
            results[market] = {
                "return": metrics["net_return_pct"],
                "dd": metrics["max_drawdown_pct"],
                "trades": metrics["round_trips"]
            }
    return {"cross_market": results}
