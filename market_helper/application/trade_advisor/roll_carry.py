"""Fetch + cache the held-futures roll yield (the carry slice of Roll & Carry).

The domain service (`futures_roll_yield`) is pure with an injectable quote
fetcher; this wrapper supplies the Yahoo fetcher, the live book, and the
artifact cache — so the dashboard can show cached carry **without any network
in the render path** and refresh it only on an explicit user action.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from market_helper.app.paths import TRADE_ADVISOR_ARTIFACTS_DIR

DEFAULT_ROLL_YIELD_PATH = TRADE_ADVISOR_ARTIFACTS_DIR / "futures_roll_yield.json"


def _yahoo_last_close(symbol: str) -> "float | None":
    """Last daily close for a Yahoo month-contract symbol (``NGU26.NYM``)."""
    from market_helper.data_sources.yahoo_finance.client import YahooFinanceClient

    payload = YahooFinanceClient(max_attempts=2).fetch_price_history(symbol, period="5d", interval="1d")
    prices = payload.get("prices") or []
    return float(prices[-1]["close"]) if prices else None


def fetch_roll_yields(
    *,
    positions_path: str | Path | None = None,
    artifact_path: str | Path | None = None,
    fetcher=None,
    now: str | None = None,
) -> dict:
    """Compute the held-roots roll yields (network!) and cache them.

    Returns the payload ``{"fetched_at", "rows": [...]}`` that
    :func:`load_roll_yields` will serve afterwards. ``fetcher`` is injectable
    for tests (defaults to the Yahoo last-close fetcher).
    """
    from market_helper.domain.portfolio_monitor.services.futures_roll_calendar import (
        load_futures_roll_config,
    )
    from market_helper.domain.portfolio_monitor.services.futures_roll_yield import compute_roll_yields

    from .portfolio import context_from_positions_csv

    context = context_from_positions_csv(positions_path)
    rows = compute_roll_yields(
        context.held_futures,
        config=load_futures_roll_config(),
        fetcher=fetcher or _yahoo_last_close,
    )
    payload = {
        "fetched_at": now or _dt.datetime.now().isoformat(timespec="seconds"),
        "rows": rows,
    }
    out = Path(artifact_path) if artifact_path else DEFAULT_ROLL_YIELD_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def load_roll_yields(artifact_path: str | Path | None = None, *, now: str | None = None) -> "dict | None":
    """Cached roll-yield payload + ``age_hours``, or ``None`` (missing/corrupt)."""
    src = Path(artifact_path) if artifact_path else DEFAULT_ROLL_YIELD_PATH
    if not src.exists():
        return None
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
        fetched = _dt.datetime.fromisoformat(str(payload.get("fetched_at", "")))
    except Exception:  # noqa: BLE001 — a corrupt cache never breaks the page
        return None
    ref = _dt.datetime.fromisoformat(now) if now else _dt.datetime.now()
    payload["age_hours"] = max((ref - fetched).total_seconds() / 3600.0, 0.0)
    return payload
