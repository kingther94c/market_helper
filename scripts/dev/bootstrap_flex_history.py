"""One-shot helper to populate data/artifacts/portfolio_monitor/flex/ from IBKR Flex.

Reads IBKR_FLEX_QUERY_ID / IBKR_FLEX_TOKEN from the process env first, then
from the local env file resolved by MARKET_HELPER_GDRIVE_ROOT (falls back to
configs/portfolio_monitor/local.env). Triggers the flex-performance refresh
used by the dashboard's "Flex" action. Intended for local first-run setup —
not a production pipeline.
"""

from __future__ import annotations

import os
from pathlib import Path

from market_helper.application.portfolio_monitor.contracts import FlexPerformanceRefreshInputs
from market_helper.application.portfolio_monitor.services import (
    DEFAULT_PERFORMANCE_OUTPUT_DIR,
    PortfolioMonitorActionService,
)
from market_helper.config.local_env import read_local_config_value


def _resolve(key: str) -> str:
    from_env = os.environ.get(key, "").strip()
    if from_env:
        return from_env
    return read_local_config_value(key).strip()


def main() -> int:
    query_id = _resolve("IBKR_FLEX_QUERY_ID")
    token = _resolve("IBKR_FLEX_TOKEN")
    if not query_id or not token:
        raise SystemExit(
            "Missing IBKR_FLEX_QUERY_ID / IBKR_FLEX_TOKEN. Export them as env "
            "vars, or add them to <MARKET_HELPER_GDRIVE_ROOT>/local.env / "
            "configs/portfolio_monitor/local.env."
        )
    inputs = FlexPerformanceRefreshInputs(
        output_dir=str(DEFAULT_PERFORMANCE_OUTPUT_DIR),
        query_id=query_id,
        token=token,
    )
    output_path = PortfolioMonitorActionService().rebuild_flex_performance(inputs)
    print(f"Flex performance refresh wrote: {output_path}")
    feather = Path(output_path).parent / "nav_cashflow_history.feather"
    print(f"nav_cashflow_history.feather exists: {feather.exists()} ({feather})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
