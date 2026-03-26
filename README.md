# market_helper

A scaffolded market research and workflow project organized for data, regime detection, signal generation, backtesting, reporting, and UI workflows.

## Environment

Create or verify the project environment:

```bash
./scripts/setup_python_env.sh
conda activate py313
```

## Project structure

This repository follows a domain-first layout:

- `configs/` for environment and runtime config
- `data/` for raw/interim/processed/external datasets
- `outputs/` for generated artifacts
- `notebooks/` for exploratory and research work
- `market_helper/` for package code by domain (`data_library`, `regimes`, `suggest`, `backtest`, `reporting`, `ui`, `workflows`, `cli`)
- `scripts/` for executable workflow entrypoints
- `tests/` for unit and e2e tests
- `docs/` for architecture and strategy notes

## Quick test

```bash
conda run -n py313 python -m unittest discover -s tests
```

## IBKR Web API Setup

Use [`configs/settings.example.json`](configs/settings.example.json) as the local config template for the read-only Web API path.

- Put your IBKR username in `provider.username`.
- Keep the password in an env var such as `IBKR_CP_PASSWORD`, referenced by `provider.password_env_var`.
- For most individual-account setups, start with username/password plus the local gateway session rather than looking for an API key first.

More detail is in [`docs/ibkr_web_api_auth.md`](docs/ibkr_web_api_auth.md).

## Position report

Generate a CSV position report from local normalized snapshot files:

```bash
conda run -n py313 python -m market_helper.cli.main position-report \
  --positions positions.json \
  --prices prices.json \
  --output outputs/position_report.csv
```

Or use the workflow wrapper script:

```bash
./scripts/run_report.sh snapshot \
  --positions positions.json \
  --prices prices.json
```

Generate a CSV position report directly from raw IBKR payload files:

```bash
conda run -n py313 python -m market_helper.cli.main ibkr-position-report \
  --ibkr-positions ibkr_positions.json \
  --ibkr-prices ibkr_prices.json \
  --output outputs/ibkr_position_report.csv
```

Or use the workflow wrapper script:

```bash
./scripts/run_report.sh ibkr-json \
  --ibkr-positions ibkr_positions.json \
  --ibkr-prices ibkr_prices.json
```

Generate a CSV position report directly from a live TWS / IB Gateway session via `ib_async`:

```bash
conda run -n py313 python -m market_helper.cli.main ibkr-live-position-report \
  --output outputs/live_ibkr_position_report.csv \
  --host 127.0.0.1 \
  --port 7497 \
  --client-id 7 \
  --account U12345
```

Before running the live command, launch TWS or IB Gateway, enable API access, and confirm the host/port/client-id match your local API settings. The defaults are `127.0.0.1:7497` with `client_id=1`.

The script wrapper also supports the live path:

```bash
./scripts/run_report.sh ibkr-live \
  --host 127.0.0.1 \
  --port 7497 \
  --client-id 7 \
  --account U12345
```

If `--account` is omitted, `./scripts/run_report.sh ibkr-live` now defaults to:
- `ACCOUNT_ENV=prod` -> `DEFAULT_PROD_ACCOUNT_ID`
- `ACCOUNT_ENV=dev` -> `DEFAULT_DEV_ACCOUNT_ID`

Keep those defaults in the local-only file `configs/report_accounts.local.env`, which is gitignored. A tracked template lives at `configs/report_accounts.example.env`.

Example:

```bash
ACCOUNT_ENV=dev ./scripts/run_report.sh ibkr-live --client-id 7
```

If `--output` is omitted, the script writes to:
- `outputs/reports/position_report.csv`
- `outputs/reports/ibkr_position_report.csv`
- `outputs/reports/live_ibkr_position_report.csv`
