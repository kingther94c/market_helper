from __future__ import annotations

"""Thin CLI-facing wrapper for the trade advisory report.

Loads the latest position report CSV + (optional) regime snapshot JSON, asks
the OpenClaw-backed advisor endpoint for analysis, and writes a markdown
advisory artifact. Token resolution mirrors the other workflows
(arg -> env -> local.env). Read-only: never places orders.
"""

import csv
import json
import os
from pathlib import Path
from typing import Any, Optional

from market_helper.config.local_env import read_local_config_value
from market_helper.domain.integration.services.trade_advisor import (
    DEFAULT_ENDPOINT_BASE_URL,
    DEFAULT_MODEL,
    render_advisory_markdown,
    request_advice,
)

_ADVISOR_TOKEN_ENV_VAR = "OPENCLAW_GATEWAY_TOKEN"
_DEFAULT_LOCAL_ENV_PATH = Path("configs/portfolio_monitor/local.env")


def _resolve_advisor_token(token: Optional[str]) -> str:
    direct = (token or "").strip()
    if direct:
        return direct
    from_env = os.environ.get(_ADVISOR_TOKEN_ENV_VAR, "").strip()
    if from_env:
        return from_env
    return read_local_config_value(_ADVISOR_TOKEN_ENV_VAR, default_path=_DEFAULT_LOCAL_ENV_PATH)


def _load_positions(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"position report CSV not found: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_latest_regime(path: Optional[Path]) -> Optional[dict[str, Any]]:
    # Missing regime is tolerated (the default path may not exist yet); the
    # advisory is still produced, just without regime context.
    if path is None or not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data[-1] if data else None
    if isinstance(data, dict):
        return data
    return None


def generate_trade_advisory(
    *,
    positions_csv_path: Path,
    regime_path: Optional[Path],
    output_path: Path,
    endpoint_base_url: str = DEFAULT_ENDPOINT_BASE_URL,
    model: str = DEFAULT_MODEL,
    session_key: Optional[str] = None,
    advisor_token: Optional[str] = None,
) -> Path:
    positions = _load_positions(positions_csv_path)
    if not positions:
        raise ValueError(f"position report CSV is empty: {positions_csv_path}")
    regime_snapshot = _load_latest_regime(regime_path)
    token = _resolve_advisor_token(advisor_token)
    result = request_advice(
        positions=positions,
        regime_snapshot=regime_snapshot,
        endpoint_base_url=endpoint_base_url,
        token=token,
        model=model,
        session_key=session_key,
    )
    markdown = render_advisory_markdown(
        positions=positions,
        regime_snapshot=regime_snapshot,
        result=result,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return output_path


__all__ = ["generate_trade_advisory", "DEFAULT_ENDPOINT_BASE_URL", "DEFAULT_MODEL"]
