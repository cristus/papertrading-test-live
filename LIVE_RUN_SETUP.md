# Paper Trading Test Stack — Setup in a New ClawBot Instance

This repository contains the CoinDCX **paper-trading only** system.

## Safety boundaries

- No CoinDCX API keys.
- No authenticated CoinDCX endpoints.
- No real orders.
- No withdrawals, transfers, margin, futures, or leverage.
- All fills are simulated in the paper broker.

## Quick start

```bash
pip install -r requirements.txt
cd paper_trader
python3 run_experiment.py
python3 -m pytest tests/ -v
```

## Phase 3 backfill/search

```bash
cd paper_trader
python3 phase3/run_phase3.py
```

## Telegram setup

```bash
cp paper_trader/config/telegram.example.yaml paper_trader/config/telegram.yaml
# Fill bot_token and chat_id locally. Do not commit config/telegram.yaml.
```

## GitHub Pages dashboard

The repository root contains:

- `index.html` — static dashboard
- `data.json` — exported dashboard data
- `export_live_data.py` — exports current SQLite state into `data.json`

Runtime SQLite databases are intentionally excluded. A new ClawBot instance should regenerate runtime data using the scripts above.

## Live hourly paper tick

In ClawBot, create a scheduled task that periodically instructs the agent to run the live tick using `paper_trader/phase3/live_runner.py` or an equivalent deterministic tick script. For a non-ClawBot server, use normal cron/systemd timers.
