# market_helper

A scaffolded market research and workflow project organized for data, regime detection, signal generation, backtesting, reporting, and UI workflows.

## Environment

Create or verify the project environment:

```bash
./scripts/setup_python_env.sh
conda activate py313
```

The shared Conda spec lives in `env.yml`.

Notebook support is included in the environment. To register this env as a Jupyter kernel:

```bash
conda run -n py313 python -m ipykernel install --user --name py313 --display-name "Python (py313)"
```

Then launch either interface:

```bash
conda run -n py313 jupyter lab
# or
conda run -n py313 jupyter notebook
```

For TWS / IB Gateway work, `market_helper` is `ib_async`-first. Standard live lookup and report flows should use the `market_helper.providers.tws_ib_async` adapter rather than `ibapi` directly.

The live single-security lookup notebook lives at `notebooks/dev_lab/derive_sec_table.ipynb` and serves as the DevLab-style entry point for sample-first exploration. It uses `market_helper` plus a local TWS / IB Gateway session to fetch raw IBKR contract details.

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

## Refactor orientation (Portfolio + Regime)

Current architecture direction is a two-engine model:
- **Portfolio Monitor**: IBKR data -> security-reference enrichment -> portfolio risk/allocation reports.
- **Regime Detection**: market/macro data -> regime classification -> dashboard + policy tilt suggestions.

Cross-engine integration lives in `suggest` + `backtest` for scenario stress testing and allocation-adjustment guidance.

Planning docs:
- Master: `DEVPLAN.md`
- Portfolio track: `DEVPLAN.portfolio.md`
- Regime track: `DEVPLAN.regime.md`
- Refactor blueprint: `docs/refactor_blueprint.md`

Shared utility guidance:
- Put **cross-engine, domain-agnostic** functions in `market_helper/utils/`.
- Keep **engine-specific business logic** inside `portfolio/` or `regimes/`.
- Promote to shared utils only after repeated use and dedicated tests.

## Quick test

```bash
conda run -n py313 python -m pytest -q tests/unit
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

The same `ib_async`-first TWS layer is also used by `notebooks/dev_lab/derive_sec_table.ipynb` for live contract lookup and notebook-led provider development.

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
  --output outputs/reports/portfolio_risk_report.html
```

- `--returns` expects JSON: `{"INTERNAL_ID": [daily_return_1, ...]}`
- `--proxy` is optional JSON for estimate-vol inputs (e.g. `VIX`, `MOVE`, `GVZ`, `OVX`).
- `--regime` is optional regime snapshot JSON (from `regime-detect`) to add a top-of-report regime banner and factor scores.

Script wrapper:

```bash
./scripts/run_report.sh risk-html \
  --positions-csv outputs/reports/live_ibkr_position_report.csv \
  --returns data/processed/returns.json \
  --proxy data/processed/risk_proxy.json
```

If `--output` is omitted, the script writes to:
- `outputs/reports/position_report.csv`
- `outputs/reports/ibkr_position_report.csv`
- `outputs/reports/live_ibkr_position_report.csv`
- `outputs/reports/portfolio_risk_report.html`

## Deterministic regime detection (v1)

The repo now includes a rule-based, deterministic regime layer under `market_helper/regimes/`. It computes factor scores (`VOL`, `CREDIT`, `RATES`, `GROWTH`, `TREND`) from proxy + returns inputs, then resolves exactly one active regime label per date with explicit crisis hysteresis and persistence rules.

Supported v1 regime labels:
- `Deflationary Crisis`
- `Inflationary Crisis`
- `Recovery / Pivot`
- `Goldilocks Expansion`
- `Reflation / Tightening-with-growth`
- `Deflationary Slowdown`
- `Stagflation / Supply Shock`

Run full detection:

```bash
conda run -n py313 python -m market_helper.cli.main regime-detect \
  --returns data/processed/regime_returns.json \
  --proxy data/processed/regime_proxies.json \
  --output data/processed/regime_snapshots.json \
  --indicators-output data/processed/indicator_snapshots.json
```

Latest-only snapshot:

```bash
conda run -n py313 python -m market_helper.cli.main regime-detect \
  --returns data/processed/regime_returns.json \
  --proxy data/processed/regime_proxies.json \
  --output data/processed/regime_snapshots.json \
  --latest-only
```

Human-readable summary + policy suggestion:

```bash
conda run -n py313 python -m market_helper.cli.main regime-report \
  --regime data/processed/regime_snapshots.json \
  --policy configs/regime_policy.example.yml
```

Input expectations:
- Proxy JSON keys: `VIX`, `MOVE`, `HY_OAS`, `UST2Y`, `UST10Y`
- Returns JSON keys: `EQ`, `FI`
- Each series can be `{date: value}` or a list form with `{as_of/date, value}` entries.

Outputs:
- `regime_snapshots.json` contains `RegimeSnapshot` rows with scores, flags, and diagnostics.
- `indicator_snapshots.json` contains factor snapshot history for validation and future backtests.

Policy layer (`market_helper/suggest/regime_policy.py`) maps regime -> `vol_multiplier` and asset-class target buckets (`EQ`, `FI`, `GOLD`, `CM`, `CASH`) for read/analyze/report suggestions only (no execution).
