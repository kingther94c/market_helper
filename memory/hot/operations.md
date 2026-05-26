# Operations (hot memory)

Day-to-day commands, env vars, and runtimes. Updated when these change.

## Environment

Always use the Conda env `py313` (Python 3.13). **Never `conda base`.**

```bash
./scripts/setup_python_env.sh     # one-time
conda activate py313
```

## Per-machine env vars

`MARKET_HELPER_GDRIVE_ROOT` drives report mirroring + `local.env` discovery
(FRED / Alpha Vantage / IBKR Flex secrets live in `<ROOT>/local.env`).

### Zero-config on standard layouts

`market_helper.config.local_env.read_gdrive_root()` resolves the path
automatically by trying, in order:

1. Process env `MARKET_HELPER_GDRIVE_ROOT`.
2. Windows User registry hive (`HKCU\Environment`) — Win-only, handles the
   agent-shell gotcha below.
3. **OS-aware probe** of well-known Google Drive mount paths:
   - Windows: `G:/My Drive/005 Portfolio`
   - macOS: `~/Library/CloudStorage/GoogleDrive-<account>/My Drive/005 Portfolio`
     (also globs `GoogleDrive-*` if the email changes; legacy
     `~/Google Drive/My Drive/005 Portfolio` last).

Result: on a fresh Win or Mac machine with Google Drive mounted at the
canonical path, **no env var setup is required** — Python tools find
`local.env` and the Google Drive report mirror dir automatically. Set the
env var explicitly only to override or use a non-standard location.

### Windows agent-shell gotcha

A child process only inherits User env vars that existed when its *parent*
started. Agents launched before `setx` ran will see
`$env:MARKET_HELPER_GDRIVE_ROOT` empty.

**Recovery for the agent-process itself** (matters when the agent is a
parent-of-parent of `python` and needs the var earlier than `read_gdrive_root`
runs):

```powershell
if (-not $env:MARKET_HELPER_GDRIVE_ROOT) {
    $env:MARKET_HELPER_GDRIVE_ROOT = [Environment]::GetEnvironmentVariable("MARKET_HELPER_GDRIVE_ROOT", "User")
}
```

Same pattern works for any other User-only env var (`FRED_API_KEY`,
`IBKR_FLEX_TOKEN`, etc.). For Claude Code specifically, the project's
`.claude/settings.local.json` `env` block does this once per session.

### Secret resolution order

process env → `<MARKET_HELPER_GDRIVE_ROOT>/local.env` →
`configs/portfolio_monitor/local.env` (gitignored fallback).

## Common commands

- Tests: `conda run -n py313 python -m pytest -q tests/unit`
- Single test: `conda run -n py313 python -m pytest tests/unit/path/to/test_file.py::test_name -q`
- Live dashboard (NiceGUI at http://127.0.0.1:18080/portfolio):
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
