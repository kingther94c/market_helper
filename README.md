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


Generate an HTML risk report (historical vol + estimate vol + correlation-based portfolio risk):

```bash
conda run -n py313 python -m market_helper.cli.main risk-html-report \
  --positions-csv outputs/reports/live_ibkr_position_report.csv \
  --returns data/processed/returns.json \
  --proxy data/processed/risk_proxy.json \
  --duration-map data/processed/duration_map.json \
  --futures-dv01-map data/processed/futures_dv01_map.json \
  --strict-futures-dv01 \
  --output outputs/reports/portfolio_risk_report.html
```

- `--returns` expects JSON: `{"INTERNAL_ID": [daily_return_1, ...]}`
- `--proxy` is optional JSON for estimate-vol inputs (e.g. `VIX`, `MOVE`, `GVZ`, `OVX`).
- `--duration-map` is optional JSON for duration overrides (key by `internal_id` or `symbol`), e.g. `{"IBKR:497222760": 6.8, "IEF": 7.1}`.
- `--futures-dv01-map` is optional JSON for CTD/conversion-factor based dynamic DV01. Example:
  `{"tenor_dv01_per_1mm": 85.0, "rows": {"IBKR:497222760": {"conversion_factor": 0.79, "ctd_duration": 7.4, "contract_multiplier": 1000}}}`
- `--strict-futures-dv01` will fail the report if rates-futures rows miss CTD/CF specs.
- CTD/CF 数据来源建议：
  1) `contract_multiplier` 从 IBKR/TWS contract details 拿；
  2) `conversion_factor` 与 CTD 对应久期从交易所公告或 Bloomberg CTD 页拿；
  3) 汇总后落到 `futures_dv01_map` 供报表读取。
- 如果未提供 `--duration-map`，当前实现会对 `FI` 资产先用保守默认值 `7.0`，其他资产为 `0.0`。
- 如果未提供 `--futures-dv01-map`，futures DV01 默认为 `0`，并等待映射补全。

Script wrapper:

```bash
./scripts/run_report.sh risk-html \
  --positions-csv outputs/reports/live_ibkr_position_report.csv \
  --returns data/processed/returns.json \
  --proxy data/processed/risk_proxy.json \
  --duration-map data/processed/duration_map.json \
  --futures-dv01-map data/processed/futures_dv01_map.json \
  --strict-futures-dv01
```

If `--output` is omitted, the script writes to:
- `outputs/reports/position_report.csv`
- `outputs/reports/ibkr_position_report.csv`
- `outputs/reports/live_ibkr_position_report.csv`
- `outputs/reports/portfolio_risk_report.html`
