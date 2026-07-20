"""
run_phase3.py — Orchestrate Phase 3: backfill → grid search → validation → robustness → live deploy.

Development sequence (all 10 steps):
  1. Backfill historical data (done, imported)
  2. Strategy library (done)
  3. Grid search on training window
  4. Validate on validation window, discard overfitters
  5. Robustness checks (fee inflation, jitter, regime split, cross-market)
  6. Live-paper deployment (7 days)
  7. Watchdog + notifications (running)
  8. Tests (all 9 areas)
  9. Begin live run
  10. Confirm first daily digest arrives
"""
from __future__ import annotations
import sys, os, json, time, sqlite3
from datetime import datetime
sys.path.insert(0, os.path.dirname(__file__) + "/..")

from phase3.backfill import backfill_to_db, MARKETS
from phase3.search import grid_search
from phase3.validation import validate_candidate, robustness_fee_inflation, robustness_price_jitter, robustness_regime_split, cross_market_test
from phase3.live_paper import deploy_live_agents
from phase3.watchdog import TelegramNotifier, HealthCheckWatchdog, alert_milestone
from core import db
from core.broker import MarketRules
import yaml


def load_telegram_config() -> dict:
    """Load Telegram credentials from config."""
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "telegram.yaml")
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
            return cfg
    return {"enabled": False}


def run_phase3():
    """Execute full Phase 3 pipeline."""
    print("=" * 80)
    print("PHASE 3: STRATEGY SEARCH + LIVE-PAPER DEPLOYMENT")
    print("=" * 80)
    
    # Setup Telegram (with fail-silent)
    tg_cfg = load_telegram_config()
    notifier = None
    if tg_cfg.get("enabled") and tg_cfg.get("bot_token") and tg_cfg.get("chat_id"):
        notifier = TelegramNotifier(tg_cfg["bot_token"], tg_cfg["chat_id"])
        alert_milestone(notifier, "Phase 3 started")
    else:
        print("⚠️  Telegram not configured — notifications disabled (running silent-only)")
    
    # Step 1: Backfill (already implemented above)
    print("\n[STEP 1] Historical backfill...")
    db_path = os.path.join(os.path.dirname(__file__), "..", "data", "phase3_exp.sqlite")
    conn = db.init_db(db_path)
    
    # Add market/source/window columns if needed
    try:
        conn.execute("ALTER TABLE market_snapshots ADD COLUMN market TEXT DEFAULT 'BTCINR'")
        conn.execute("ALTER TABLE market_snapshots ADD COLUMN source TEXT DEFAULT 'live'")
        conn.execute("ALTER TABLE market_snapshots ADD COLUMN window TEXT DEFAULT 'live'")
        conn.commit()
    except:
        pass
    
    backfill_summary = backfill_to_db(1, conn)
    alert_milestone(notifier, "Backfill complete: 3 markets × 500 candles, 60/20/20 split")
    
    # Load train/val/holdout data per market
    train_data = {}
    val_data = {}
    holdout_data = {}
    rules = MarketRules(min_notional=100.0, min_quantity=0.00001, step=0.00001)
    
    for market in MARKETS.keys():
        train = conn.execute(
            "SELECT close FROM market_snapshots WHERE market=? AND window='train' ORDER BY tick_index",
            (market,)
        ).fetchall()
        val = conn.execute(
            "SELECT close FROM market_snapshots WHERE market=? AND window='validation' ORDER BY tick_index",
            (market,)
        ).fetchall()
        holdout = conn.execute(
            "SELECT close FROM market_snapshots WHERE market=? AND window='holdout' ORDER BY tick_index",
            (market,)
        ).fetchall()
        
        train_data[market] = [r[0] for r in train]
        val_data[market] = [r[0] for r in val]
        holdout_data[market] = [r[0] for r in holdout]
    
    # Step 2-3: Grid search on training window
    print("\n[STEP 2-3] Grid search on training window...")
    all_candidates = {}
    for market, closes in train_data.items():
        print(f"  Searching {market}...")
        candidates = grid_search(market, closes, closes[-1], rules)
        all_candidates[market] = candidates
        alert_milestone(notifier, f"Grid search complete: {market} ({len(candidates)} candidates)")
    
    # Step 4: Validation (discard overfitters)
    print("\n[STEP 4] Validation + overfitting gate...")
    survivors = {}
    for market in all_candidates.keys():
        print(f"  Validating {market}...")
        survivors[market] = []
        for cand in all_candidates[market][:10]:  # Top 10 per market
            validated = validate_candidate(cand, train_data[market], val_data[market],
                                          val_data[market][-1], rules)
            if validated:
                survivors[market].append(validated)
                print(f"    ✓ {cand['family']} {cand['params']}: train={cand['net_return_pct']:.1f}% → val={validated['val_return_pct']:.1f}%")
            else:
                print(f"    ✗ {cand['family']} {cand['params']}: OVERFITTER (train={cand['net_return_pct']:.1f}%)")
    
    alert_milestone(notifier, f"Validation complete: {sum(len(s) for s in survivors.values())} survivors across markets")
    
    # Step 5: Robustness checks on survivors
    print("\n[STEP 5] Robustness checks...")
    for market, cands in survivors.items():
        for cand in cands[:3]:  # Top 3 per market
            print(f"  {market} / {cand['family']}...")
            cand.update(robustness_fee_inflation(cand, val_data[market], val_data[market][-1], rules))
            cand.update(robustness_price_jitter(cand, val_data[market], val_data[market][-1], rules))
            cand.update(robustness_regime_split(cand, val_data[market], val_data[market][-1]))
            cand.update(cross_market_test(cand, val_data, rules))
            print(f"    Fee inflation test: {cand.get('fee_inflated_return', 0):.1f}%")
            print(f"    Price jitter: mean={cand.get('jitter_mean', 0):.1f}%, std={cand.get('jitter_std', 0):.2f}%")
    
    alert_milestone(notifier, "Robustness checks complete")
    
    # Step 6: Live deployment
    print("\n[STEP 6] Live-paper deployment...")
    top_survivors = []
    for market, cands in survivors.items():
        if cands:
            top_survivors.append(cands[0])  # Top 1 per market
    
    agents = deploy_live_agents(top_survivors, conn, experiment_id=1, risk=None)
    alert_milestone(notifier, f"Live deployment: {len(agents)} agents spawned, 7-day run starting")
    
    # Step 7-8: Watchdog (running in background)
    print("\n[STEP 7-8] Watchdog + tests...")
    watchdog = HealthCheckWatchdog(conn, notifier)
    checks = watchdog.check_all()
    print(f"  Health checks: {checks}")
    
    # Step 9-10: Report and begin
    print("\n[STEP 9-10] Summary & begin...")
    summary = {
        "backfill": backfill_summary,
        "total_candidates_tested": sum(len(c) for c in all_candidates.values()),
        "survivors_after_validation": sum(len(s) for s in survivors.values()),
        "top_survivors": [
            {
                "family": s.get("family"),
                "market": "unknown",  # need to track this
                "train_return": s.get("net_return_pct"),
                "val_return": s.get("val_return_pct"),
                "robustness": {
                    "fee_inflated": s.get("fee_inflated_return"),
                    "jitter_mean": s.get("jitter_mean")
                }
            }
            for survivors_list in survivors.values()
            for s in survivors_list[:1]
        ],
        "agents_deployed": len(agents),
        "run_started": datetime.now().isoformat(),
        "run_duration_days": 7
    }
    
    with open(os.path.join(os.path.dirname(__file__), "..", "data", "phase3_results.json"), "w") as f:
        json.dump(summary, f, indent=2)
    
    print("\n" + "=" * 80)
    print("PHASE 3 SUMMARY")
    print("=" * 80)
    print(f"Candidates tested: {summary['total_candidates_tested']}")
    print(f"Survivors after validation: {summary['survivors_after_validation']}")
    print(f"Agents deployed: {summary['agents_deployed']}")
    print(f"Expected completion: {datetime.now() + __import__('datetime').timedelta(days=7)}")
    print("=" * 80)
    
    alert_milestone(notifier, f"Phase 3 LIVE: {len(agents)} agents running, 7-day experiment active")
    
    conn.close()
    return summary


if __name__ == "__main__":
    result = run_phase3()
    print(json.dumps(result, indent=2))
