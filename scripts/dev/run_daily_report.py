"""Daily report orchestrator — intended for use by the Windows scheduled task.

Order of operations:
1. Live IBKR position refresh (mirrors the CSV to <GDRIVE_ROOT>/Portfolio_Report/).
   Failure is non-fatal — the combined report falls back to the cached CSV.
2. Combined HTML report generation (mirrors the HTML to GDrive).

Account ID resolution follows the same chain as ``scripts/run_report.sh``:
process env DEFAULT_PROD_ACCOUNT_ID → local.env → SystemExit if missing.

`MARKET_HELPER_GDRIVE_ROOT` resolution uses Pattern B
(``market_helper.config.local_env.read_gdrive_root``) — no shell injection
needed; the probe handles canonical Mac + Win layouts.

Logs go to ``data/artifacts/scheduled/last_run.log`` (single file, overwritten
each run) plus a timestamped file ``YYYYMMDD-HHMM.log`` next to it.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import sys
import traceback
from pathlib import Path

from market_helper.app.paths import DATA_DIR
from market_helper.application.portfolio_monitor import (
    GenerateCombinedReportInputs,
    LivePortfolioRefreshInputs,
    PortfolioMonitorActionService,
)
from market_helper.config.local_env import read_local_config_value

DEFAULT_POSITIONS_CSV = DATA_DIR / "artifacts" / "portfolio_monitor" / "live_ibkr_position_report.csv"
DEFAULT_COMBINED_HTML = DATA_DIR / "artifacts" / "portfolio_monitor" / "portfolio_dashboard_report.html"
SCHEDULED_LOG_DIR = DATA_DIR / "artifacts" / "scheduled"


def _resolve_account_id() -> str:
    account_env = (os.environ.get("ACCOUNT_ENV", "prod") or "prod").lower()
    key = {
        "prod": "DEFAULT_PROD_ACCOUNT_ID",
        "production": "DEFAULT_PROD_ACCOUNT_ID",
        "dev": "DEFAULT_DEV_ACCOUNT_ID",
        "development": "DEFAULT_DEV_ACCOUNT_ID",
        "paper": "DEFAULT_DEV_ACCOUNT_ID",
        "test": "DEFAULT_DEV_ACCOUNT_ID",
    }.get(account_env, "DEFAULT_PROD_ACCOUNT_ID")
    value = (os.environ.get(key, "") or read_local_config_value(key)).strip()
    if not value:
        raise SystemExit(
            f"Missing {key}. Set it in the process env or in "
            "<MARKET_HELPER_GDRIVE_ROOT>/local.env / configs/portfolio_monitor/local.env."
        )
    return value


def _setup_logging() -> logging.Logger:
    SCHEDULED_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M")
    timestamped = SCHEDULED_LOG_DIR / f"{stamp}.log"
    rolling = SCHEDULED_LOG_DIR / "last_run.log"
    logger = logging.getLogger("scheduled.daily_report")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for path in (timestamped, rolling):
        handler = logging.FileHandler(path, mode="w", encoding="utf-8")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    return logger


def main() -> int:
    logger = _setup_logging()
    logger.info("Daily report run starting (cwd=%s)", os.getcwd())

    service = PortfolioMonitorActionService()
    positions_path = DEFAULT_POSITIONS_CSV
    html_path = DEFAULT_COMBINED_HTML

    # Step 1: live refresh (non-fatal — combined report falls back to cached CSV)
    try:
        account_id = _resolve_account_id()
        live_inputs = LivePortfolioRefreshInputs(
            output_path=positions_path,
            host=os.environ.get("IBKR_HOST", "127.0.0.1"),
            port=int(os.environ.get("IBKR_PORT", "7497")),
            client_id=int(os.environ.get("IBKR_CLIENT_ID", "1")),
            account_id=account_id,
            timeout=float(os.environ.get("IBKR_TIMEOUT", "4.0")),
        )
        logger.info("Live refresh -> %s (account=%s, host=%s:%s)",
                    positions_path, account_id, live_inputs.host, live_inputs.port)
        service.refresh_live_positions(live_inputs)
        logger.info("Live refresh OK")
    except Exception as exc:  # noqa: BLE001 — keep the cron alive
        logger.warning("Live refresh failed; using cached CSV. Detail: %s", exc)
        logger.debug("traceback:\n%s", traceback.format_exc())
        if not positions_path.exists():
            logger.error("Cached positions CSV also missing at %s; aborting.", positions_path)
            return 2

    # Step 2: combined HTML report.
    # regime_mode="refresh-if-stale" ensures the regime engine runs as part of
    # this single cron pass when the snapshot is older than the provider's
    # stale window (72h). This is what restored the regime section in the
    # daily report — previously the cron only refreshed positions + rendered,
    # leaving regime to a separately-triggered manual button that nobody
    # remembered to push.
    try:
        combined_inputs = GenerateCombinedReportInputs(
            positions_csv_path=positions_path,
            output_path=html_path,
            regime_mode="refresh-if-stale",
        )
        logger.info("Combined HTML -> %s", html_path)
        artifact = service.generate_combined_report(combined_inputs)
        logger.info("Combined HTML OK (mirrored=%s, warnings=%d)",
                    artifact.mirrored_output_path, len(artifact.warnings))
        for w in artifact.warnings:
            logger.warning("  warning: %s", w)
    except Exception as exc:  # noqa: BLE001 — log and surface as failure
        logger.error("Combined HTML generation failed: %s", exc)
        logger.debug("traceback:\n%s", traceback.format_exc())
        return 3

    logger.info("Daily report run done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
