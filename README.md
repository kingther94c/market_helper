# market_helper

A scaffolded market research and workflow project organized around data sources, domain services, presentation outputs, and CLI workflows.

## Environment

Create or verify the project environment:

```bash
./scripts/setup_python_env.sh
conda activate py313
```

The shared Conda spec lives in `env.yml`. It defines the development environment only and is not part of the domain runtime-config layout below.

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

For TWS / IB Gateway work, `market_helper` is `ib_async`-first. Standard live lookup and report flows should use the `market_helper.data_sources.ibkr.tws` adapter rather than `ibapi` directly.

`notebooks/dev_lab/` is a local scratch area and should stay out of version control. A reusable IBKR contract lookup notebook lives at `notebooks/portfolio_monitor/derive_sec_table.ipynb`.

## Project structure

This repository follows a domain-first layout:

- `configs/{app,portfolio_monitor,regime_detection,integration}/` for runtime config, templates, and tracked reference inputs
- `data/{raw,interim,processed,cache,artifacts}/` for datasets and generated outputs
- `outputs/` for previews, samples, and scratch artifacts rather than runtime config
- `notebooks/{dev_lab,portfolio_monitor,regime_detection,integration}/` for exploration
- `market_helper/{data_sources,domain,presentation,cli,common,app}/` for package code
- `scripts/` for executable workflow entrypoints
- `tests/` for unit, integration, and e2e coverage
- `docs/` for architecture notes and devplans


### Package organization direction

Within `market_helper/`, the recommended internal layout is:

- `data_sources/` for IBKR / Yahoo / FRED and provider adapters
- `domain/portfolio_monitor/` for portfolio report, security-reference enrichment, allocation/risk logic
- `domain/regime_detection/` for macro/regime/policy/backtester/dashboard domain workflows
- `domain/integration/` for cross-domain stress tests, recommendations, and combined reports
- `presentation/` for HTML/table/chart/dashboard-facing formatting and rendering
- `cli/` for user-facing command entrypoints

Legacy modules (for example `market_helper.ui.*`) remain as compatibility wrappers where needed, but new imports should target the package layout above.

## Quick test

```bash
conda run -n py313 python -m pytest -q tests/unit
```

## ETF sector lookthrough sync

To refresh ETF sector weights in [`configs/portfolio_monitor/us_sector_lookthrough.json`](configs/portfolio_monitor/us_sector_lookthrough.json), put your local secrets in [`configs/portfolio_monitor/local.env`](configs/portfolio_monitor/local.env) and run:

```bash
conda run -n py313 python -m market_helper.cli.main etf-sector-sync \
  --symbol SOXX \
  --symbol QQQ
```

Or via the script wrapper:

```bash
./scripts/run_report.sh etf-sector-sync --symbol SOXX --symbol QQQ
```

- The command fetches ETF sector weights from Financial Modeling Prep and merges just those tickers into `us_sector_lookthrough.json`.
- `--api-key` is optional; if omitted, the command reads `FMP_API_KEY` from the process environment, then falls back to `configs/portfolio_monitor/local.env`.
- FMP sector labels are normalized into the portfolio monitor's existing buckets such as `Financials`, `Health Care`, and `Consumer Discretionary`.
- The JSON store tracks each symbol's `updated_at`, cached sector weights, and the shared daily FMP call count.
- During `risk-html-report`, the report flow now auto-registers newly seen US ETF candidates with `updated_at=2000-01-01`, then refreshes only symbols older than 30 days, subject to the `250` calls/day budget.

## IBKR Web API Setup

Use [`configs/app/settings.example.json`](configs/app/settings.example.json) as the local config template for the read-only Web API path.

This file is a future scaffold for a planned Web API flow. Current CLI reporting workflows do not load it yet.

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
  --output data/artifacts/portfolio_monitor/position_report.csv
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
  --output data/artifacts/portfolio_monitor/ibkr_position_report.csv
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
  --output data/artifacts/portfolio_monitor/live_ibkr_position_report.csv \
  --host 127.0.0.1 \
  --port 7497 \
  --client-id 7 \
  --account U12345
```

Before running the live command, launch TWS or IB Gateway, enable API access, and confirm the host/port/client-id match your local API settings. The defaults are `127.0.0.1:7497` with `client_id=1`.

The same `ib_async`-first TWS layer is also used by `notebooks/portfolio_monitor/derive_sec_table.ipynb` for live contract lookup and notebook-led provider development.

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

Keep those defaults, plus local-only secrets like `FMP_API_KEY`, in the gitignored file `configs/portfolio_monitor/local.env`. A tracked template lives at `configs/portfolio_monitor/local.example.env`.

Example:

```bash
ACCOUNT_ENV=dev ./scripts/run_report.sh ibkr-live --client-id 7
```

End-to-end live position -> HTML risk report:

```bash
./scripts/run_report.sh ibkr-live-html \
  --host 127.0.0.1 \
  --port 7497 \
  --client-id 7 \
  --account U12345
```

- This first writes the live position CSV, then immediately builds the HTML risk report from that CSV.
- After the HTML is written, the script also tries to open it in your default browser.
- `--output` controls the final HTML path.
- `--positions-output` optionally overrides where the intermediate live position CSV is written.
- If `--proxy` is omitted, the report falls back to the `proxy` block in `configs/portfolio_monitor/report_config.yaml`.


Generate an HTML risk report (historical vol + estimate vol + correlation-based portfolio risk):

```bash
conda run -n py313 python -m market_helper.cli.main risk-html-report \
  --positions-csv data/artifacts/portfolio_monitor/live_ibkr_position_report.csv \
  --returns data/processed/returns.json \
  --output data/artifacts/portfolio_monitor/portfolio_risk_report.html
```

- `--returns` expects JSON: `{"INTERNAL_ID": [daily_return_1, ...]}`
- `--proxy` is optional JSON for estimate-vol inputs.
  If omitted, `risk-html-report` first looks for a `proxy` block in `configs/portfolio_monitor/report_config.yaml`, then fills any missing `VIX`, `MOVE`, `OVX`, and `GVZ` values from Yahoo Finance daily history, sets `FXVOL=0`, and makes `DEFAULT` follow `VIX`.
  If provided, the JSON can also use aliases such as `{"DEFAULT": "VIX", "FXVOL": 0}`.
- `--regime` is optional regime snapshot JSON (from `regime-detect`) to add a top-of-report regime banner and factor scores.
- `--risk-config` is the recommended unified YAML config entrypoint for lookthrough tables, proxy defaults, and policy mixes. If omitted, the report uses `configs/portfolio_monitor/report_config.yaml`.
- `portfolio_asset_class_targets` inside `report_config.yaml` are used as raw policy targets for the portfolio-level drift table and are not auto-normalized. Values above `1.0` are allowed when you want to express gross-exposure style targets.
- `--security-reference` defaults to the generated local cache at `data/artifacts/portfolio_monitor/security_reference.csv`.
- `--allocation-policy` remains available as a deprecated compatibility override for legacy policy-only YAML files.

Script wrapper:

```bash
./scripts/run_report.sh risk-html \
  --positions-csv data/artifacts/portfolio_monitor/live_ibkr_position_report.csv \
  --returns data/processed/returns.json
```

If `--output` is omitted, the script writes to:
- `data/artifacts/portfolio_monitor/position_report.csv`
- `data/artifacts/portfolio_monitor/ibkr_position_report.csv`
- `data/artifacts/portfolio_monitor/live_ibkr_position_report.csv`
- `data/artifacts/portfolio_monitor/portfolio_risk_report.html`

Those files under `data/artifacts/portfolio_monitor/` are generated outputs, not config inputs. The checked-in preview files under `outputs/` are also output artifacts rather than runtime config.
`data/artifacts/portfolio_monitor/live_ibkr_position_report.csv` is a local generated output and should remain gitignored.

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
  --output data/artifacts/regime_detection/regime_snapshots.json \
  --indicators-output data/artifacts/regime_detection/indicator_snapshots.json
```

Optional tuning overrides can be based on `configs/regime_detection/regime_config.example.yml`.

Latest-only snapshot:

```bash
conda run -n py313 python -m market_helper.cli.main regime-detect \
  --returns data/processed/regime_returns.json \
  --proxy data/processed/regime_proxies.json \
  --output data/artifacts/regime_detection/regime_snapshots.json \
  --latest-only
```

Human-readable summary + policy suggestion:

```bash
conda run -n py313 python -m market_helper.cli.main regime-report \
  --regime data/artifacts/regime_detection/regime_snapshots.json \
  --policy configs/regime_detection/regime_policy.example.yml
```

Input expectations:
- Proxy JSON keys: `VIX`, `MOVE`, `HY_OAS`, `UST2Y`, `UST10Y`
- Returns JSON keys: `EQ`, `FI`
- Each series can be `{date: value}` or a list form with `{as_of/date, value}` entries.

Outputs:
- `regime_snapshots.json` contains `RegimeSnapshot` rows with scores, flags, and diagnostics.
- `indicator_snapshots.json` contains factor snapshot history for validation and future backtests.

Policy layer (`market_helper/suggest/regime_policy.py`) maps regime -> `vol_multiplier` and asset-class target buckets (`EQ`, `FI`, `GOLD`, `CM`, `CASH`) for read/analyze/report suggestions only (no execution).
