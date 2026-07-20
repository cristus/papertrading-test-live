# Evolutionary Crypto Paper-Trading System (BTCINR, CoinDCX public data)

**PAPER TRADING ONLY. No real orders. No API key anywhere in this codebase.**

## Safety rules (non-negotiable, enforced structurally — not just documented)

| Rule | How it's enforced |
|---|---|
| No CoinDCX API key/secret ever requested/stored/used | `core/market_data.py` has no auth parameter, no header-signing code, no credential storage path at all |
| No real orders / no authenticated endpoints | `PublicMarketData._get()` allowlists only 3 public paths; anything else raises `ValueError`. No order-submission code exists anywhere. |
| No withdrawal/transfer/margin/futures/leverage | Not implemented; `risk.yaml` has hard boolean flags (`allow_margin_futures_leverage`, `allow_withdraw_transfer`) that `RiskConfig.assert_safe()` requires to be `false` at load time |
| Strategy/LLM can never modify risk config | `RiskConfig` is a **frozen** dataclass; strategies never receive a reference to it |
| Global emergency-pause flag halts all agents | `EmergencyPause` checked before every tick (`Engine.run_agent_tick`); when tripped, every agent gets a `PAUSED` ledger row and no simulated order is placed |

## Architecture

```
paper_trader/
├── config/config.yaml     # editable: market, fees, cohorts, data window
├── config/risk.yaml       # IMMUTABLE: risk limits + emergency_pause flag
├── core/
│   ├── safety.py          # frozen RiskConfig, EmergencyPause, SafetyViolation
│   ├── market_data.py     # CoinDCX PUBLIC connector only
│   ├── db.py               # SQLite schema, append-only ledger (DB triggers)
│   ├── broker.py           # simulated fills: fee/spread/slippage/TDS/min-order/10%-cap/1-position
│   ├── strategy.py         # deterministic SMA-crossover baseline (no-lookahead)
│   ├── agent.py             # death/reproduction threshold detection
│   └── engine.py            # tick loop, snapshot-once-per-tick, no-lookahead slicing
├── run_experiment.py       # cohort runner (₹2k / ₹8k / ₹20k)
├── dashboard/app.py        # Flask, read-only DB access, 405s any non-GET
├── tests/                  # 26 tests across 8 required areas
└── data/                   # one sqlite file per experiment + manifest.json
```

## Running an experiment

```bash
cd paper_trader
python3 run_experiment.py --config config/config.yaml
```

This fetches BTCINR public candles ONCE, replays them tick-by-tick for all three
cohorts (identical market/window/strategy — only starting capital differs),
and writes results to `data/exp_<id>.sqlite` + appends to `data/manifest.json`.

## Running tests

```bash
pip install --break-system-packages pytest flask pyyaml requests
python3 -m pytest tests/ -v
```

## Running the dashboard (read-only)

```bash
python3 -m flask --app dashboard/app.py run --port 5055
# open http://127.0.0.1:5055/
```

Every dashboard DB connection is opened `mode=ro`; a `before_request` hook
also 405s any non-GET/HEAD/OPTIONS method as a second, independent guard.

## Emergency pause

Set `emergency_pause: true` in `config/risk.yaml` and re-run — every agent's
next tick will log a `PAUSED` ledger row and take no action. This flag is
NOT reachable from strategy code or from the dashboard; only a human editing
`risk.yaml` can flip it.

## Assumed economics (all in `config/config.yaml`, editable, never touched by strategy code)

- Taker fee: 0.1% per fill
- Spread cost: 0.05%
- Slippage: 0.1%
- TDS: 1% of gross sell proceeds (India, estimated)

## Known limitations of this phase

- Single market (BTCINR) — deliberate, per spec, for a clean tier comparison.
- Reproduction is **log-only**: no live agent cloning yet.
- Backtest mode replays historical public candles; this is NOT a claim of
  future profitability — see the experiment report for explicit caveats.
