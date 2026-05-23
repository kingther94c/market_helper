# Operations (hot memory)

Day-to-day commands, env vars, and runtimes. Updated when these change.

## Environment

Always use the Conda env `py313` (Python 3.13). **Never `conda base`.**

```bash
./scripts/setup_python_env.sh     # one-time
conda activate py313
```

## Per-machine env vars (Windows gotcha)

`MARKET_HELPER_GDRIVE_ROOT` drives report mirroring + `local.env` discovery
(FRED / Alpha Vantage / IBKR Flex secrets live in `<ROOT>/local.env`).
Typically set as a **User-level** Windows env var via `setx`.

**Agent-shell gotcha**: a child process only inherits User env vars that
existed when its *parent* started. Agents launched before `setx` ran will see
`$env:MARKET_HELPER_GDRIVE_ROOT` empty.

**Recovery** — read the registry first, inject before any tool call that
resolves `local.env`:

```powershell
if (-not $env:MARKET_HELPER_GDRIVE_ROOT) {
    $env:MARKET_HELPER_GDRIVE_ROOT = [Environment]::GetEnvironmentVariable("MARKET_HELPER_GDRIVE_ROOT", "User")
}
```

Apply before `fred-macro-sync`, `etf-sector-sync`, `regime-detect`,
`run_report.sh`, dashboard launch. Same pattern for `FRED_API_KEY` /
`IBKR_FLEX_TOKEN` / etc. One injection propagates to subsequent
`python -m ...` calls — `market_helper.config.local_env` reads `os.environ`.

The Python config layer also auto-falls back to the `HKCU\Environment`
registry hive if `os.environ` is empty (Windows only; no-op elsewhere).

Secret resolution order: process env → `<MARKET_HELPER_GDRIVE_ROOT>/local.env`
→ `configs/portfolio_monitor/local.env` (gitignored fallback).

## Common commands

- Tests: `conda run -n py313 python -m pytest -q tests/unit`
- Single test: `conda run -n py313 python -m pytest tests/unit/path/to/test_file.py::test_name -q`
- Live dashboard (NiceGUI at http://127.0.0.1:8080/portfolio):
  `./scripts/launch_ui.sh`
  env overrides: `PORT`, `HOST`, `ENV_NAME`, `AUTO_OPEN`, `OPEN_WAIT_SECONDS`
- Reports / workflows:
  - `./scripts/run_report.sh`
  - `./scripts/run_regime_detection.sh`
  - `./scripts/run_backtest.sh`
  - `./scripts/run_data_update.sh`
- CLI dispatch: `python -m market_helper.cli.main <subcommand>`
  - Key subcommands: `position-report`, `ibkr-position-report`,
    `ibkr-live-position-report`, `ibkr-flex-performance-report`,
    `risk-html-report`, `combined-html-report`, `regime-detect`,
    `regime-report`, `etf-sector-sync`, `security-reference-sync`

## First-run bootstrap helpers

- `scripts/dev/bootstrap_flex_history.py` — runs the Flex performance refresh
  using creds from the resolved local env. Populates
  `data/artifacts/portfolio_monitor/flex/nav_cashflow_history.feather` +
  the dated `performance_report_*.csv` so the dashboard renders without
  missing-history warnings.
- `scripts/dev/verify_ui_report.py` — drives `generate_combined_report` and
  asserts the dashboard's missing-artifact warnings are absent.

## Test workspace

Pytest `--basetemp=.pytest_tmp` (set in `pyproject.toml`). If the dir gets
into a Windows-locked state, override with `--basetemp=$env:TEMP\mh_pytest_tmp`
for an individual run rather than chasing the lock.
