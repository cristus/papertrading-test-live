# Phase 3: Strategy Search + Live-Paper Deployment (PROPOSAL)

## Part A: Third Market Selection

**Proposal: XRPINR (XRP/INR)**

Rationale:
- High volume on CoinDCX, different volatility profile than BTC/ETH
- Tradeable at 1h resolution with same API endpoint pattern
- Good for cross-market robustness (alt-coin behavior vs majors)
- CoinDCX public candle endpoint: `/market_data/candles?pair=I-XRP_INR`

**Confirm or propose alternative (ADAINR, DOGEINR, BNBINR)?**

---

## Part B: File Structure Changes (Phase 3 modules)

```
paper_trader/
├── phase3/
│   ├── backfill.py           # download & split historical data (60/20/20)
│   ├── strategies.py         # candidate families + cost-gate logic
│   ├── search.py             # grid search on training window
│   ├── validation.py         # overfitting gate, holdout runner
│   ├── robustness.py         # fee perturbation, price jitter, regime split
│   ├── live_paper.py         # 7-day parallel agent deployment
│   ├── watchdog.py           # 5m health checks, Telegram notifications
│   └── config_phase3.yaml    # strategy ranges, Telegram creds, thresholds
├── config/
│   └── telegram.yaml         # bot_token, chat_id (you provide)
├── tests/
│   └── test_phase3.py        # all 9 test areas for Phase 3
└── data/
    └── phase3_results.json   # aggregated metrics
```

---

## Part C: Telegram Configuration

**How to provide credentials:**
1. Create `config/telegram.yaml` with:
```yaml
enabled: true
bot_token: "YOUR_BOT_TOKEN_HERE"
chat_id: "YOUR_CHAT_ID_HERE"
```
2. I stub the file with placeholders if not provided
3. Watchdog checks at startup; if missing/invalid, logs warning and continues (silent-by-default still works)
4. Sends are async (non-blocking to trading logic)

**Confirm: fail-silent behavior if Telegram credentials missing?** (yes/no)

---

## Part D: Strategy Parameter Ranges

| Family | Parameters | Proposed Range |
|---|---|---|
| **SMA/EMA** | fast, slow | fast ∈ [5,10,20], slow ∈ [30,50,100] |
| **Breakout** | lookback, confirm | lookback ∈ [10,20,30], confirm ∈ [1,2,3] |
| **Mean Reversion** | RSI_period, oversold | RSI_period ∈ [7,14,21], oversold ∈ [20,25,30] |
| **Trend-Filtered** | base_family + 4h_ema | 4h_ema ∈ [12,20,30] (applied to SMA) |

This gives ~3 + 6 + 6 + 3 = 18 parameter combos per family × 3 markets = 54 candidate evaluations in grid search.

**Confirm ranges or propose different?**

---

## Part E: Cost-Gate & Validation Rules

**Cost-gate rule (risk layer, immutable):**
- No entry signal unless: `(avg_win_size / num_trades) >= 0.03` on training window
- Flag trades exceeding 10/week as cost-fragile (log, not auto-discard)

**Validation overfitting gate:**
- Discard if validation net return drops >50% from training
  - E.g., training = +5% → validation must be ≥ +2.5% to survive

**Confirm these thresholds, or adjust?**

---

## Part F: Robustness Checks (Immutable Rules)

1. **Fee inflation (+50%)**: re-run with fee/spread/slippage × 1.5; discard if negative
2. **Price jitter (±0.1%)**: run 10× with random entry perturbations; report outcome spread
3. **Regime split**: classify sub-periods as trending vs ranging (4h EMA slope); report separately
4. **Cross-market check**: run each survivor on all 3 markets; note single-market vs multi-market

**All results held to same gate: must not flip negative, validate output spread <20%, etc.**

**Confirm or modify?**

---

## Part G: Live-Paper Deployment (7 days, ₹8,000 tier)

**Agent slots (up to 6 strategies × markets):**
- SMA baseline (BTCINR only, control)
- Top 1-2 survivors from search (deployed on their validated market + cross-test others)
- Buy-and-hold benchmark (all 3 markets)

**Architecture:**
- Single market-data fetch per market per tick (no per-agent polling)
- Shared market_snapshots table (source = 'live')
- Each agent: own ledger + death (40%) / reproduction (200%) rules
- TDS tracked as separate line item in ledger

**Confirm deployment plan, or different?**

---

## Part H: Telegram Notifications (Programmatic Only)

**Silent-by-default watchdog (every 5m):**
- Data feed freshness (no tick for >10m per market)
- Agent running (no death ledger row since last check)
- Ledger writable (test INSERT)
- No unhandled exceptions
- Disk space >10% free
- → If all pass: send nothing

**Immediate alerts:**
- Health check fails + recovery
- Emergency-pause activated
- Death/reproduction threshold crossed
- Backfill/grid/validation/holdout/live-run milestones

**Remarkable observations (config-tunable, fired immediately):**
- 24h agent return deviates ±5% from buy-and-hold on its market
- Equity beyond ±10% of starting capital
- Active strategy fires zero trades for 48h

**Daily digest (09:00 IST):**
- One message: strategy × market table (24h metrics)
- Silence-breaker: if no message for 12h, send "system healthy, nothing to report"

**All sends:**
- Logged to ledger (timestamp + type)
- Async (non-blocking to trading)
- Mocked in tests (no real sends)

**Confirm this spec, or different?**

---

## Part I: Testing (9 areas for Phase 3)

1. Train/validation/holdout split integrity (no leakage, dates ordered)
2. Cost-gate enforcement (candidates below threshold auto-rejected)
3. Candidate discard logic (overfitting gate at 50% drop)
4. Robustness perturbation harness (fee × 1.5, price ±0.1%, outcomes reported)
5. Multi-agent isolation (identical shared market data per market)
6. Watchdog check coverage (all 5 health checks + mocked Telegram)
7. Notification trigger conditions (cost-gate, remarkable obs, milestones)
8. TDS line-item separation (recorded in ledger, distinct from fees)
9. Cross-market survival table (rows=strategies, cols=markets, [survive/fail])

**Confirm test areas, or add/remove?**

---

## Part J: Development Sequence (Locked)

1. **Confirm this proposal** (you sign off on A–I)
2. **Backfill & split** (download 1h candles, construct 60/20/20)
3. **Strategy library** (code families + cost-gate)
4. **Grid search** (training window only)
5. **Validation & holdout** (discard overfitters, report survivors)
6. **Robustness suite** (fee inflation, price jitter, regime split, cross-market)
7. **Live-paper deployment** (7 days, top candidates + baselines)
8. **Watchdog & notifications** (5m health checks, daily digests, alerts)
9. **Test suite** (all 9 areas)
10. **Begin 7-day run** (confirm first daily digest arrives at 09:00 IST)

---

## Safety Confirmation (NON-NEGOTIABLE)

All Phase 3 additions **inherit and enforce** Phase 1–2 rules:

- ✅ No CoinDCX API key/secret ever requested/stored/used
- ✅ No authenticated CoinDCX endpoint ever called
- ✅ No real orders, no withdrawal/transfer/margin/futures/leverage code
- ✅ No unreviewed third-party plugins (all strategies authored in-repo)
- ✅ RiskConfig and cost-gate rules **never editable by strategy code**
- ✅ Emergency-pause flag remains global, always checked before tick
- ✅ Telegram notifications async + non-blocking; Telegram outage ≠ trading halt
- ✅ All strategy parameters sourced from config (never hardcoded in strategy logic)

**Strategy code cannot:**
- Modify risk.yaml, config.yaml, telegram.yaml
- Call market_data client directly (engine feeds it snapshots only)
- Access future data (no-lookahead enforced by engine)
- Disable/modify thresholds or health checks

---

## Ready?

Once you confirm A–I and affirm the safety rules, I'll proceed straight to step 1 (backfill).
