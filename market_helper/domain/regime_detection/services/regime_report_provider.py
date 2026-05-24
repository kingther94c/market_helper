"""Provider that owns the *combined-report* view of the regime artifact.

Before this module the combined report read whatever regime snapshot happened to
be on disk; if it was missing or stale, the regime section silently disappeared
and the user had to remember to run a separate refresh action. This provider
turns regime data into a first-class part of the combined-report pipeline by
encapsulating three modes:

- ``cached`` — load whatever is on disk, tag freshness.
- ``refresh-if-stale`` — refresh when missing or when the latest snapshot's
  ``as_of`` lags the expected T-1 trading day; otherwise reuse the cache.
- ``force-refresh`` — always run the engine first.

Failures during engine refresh are converted to an ``engine_error`` state so the
caller can still render the report instead of crashing on a cron failure.

Staleness uses the **same trading-day predicate** that drives the report's
top-of-page freshness note (``compute_as_of_freshness_note``) — sharing
``market_helper.common.datetime_display.is_as_of_stale`` means the regime
section's stale flag and the report's overall freshness note can never disagree
about what ‟stale" means.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from market_helper.common.datetime_display import is_as_of_stale
from market_helper.reporting.regime_html import (
    RegimeHtmlViewModel,
    build_regime_html_view_model,
)


logger = logging.getLogger(__name__)


RegimeMode = Literal["cached", "refresh-if-stale", "force-refresh"]


@dataclass(frozen=True)
class RegimeArtifactState:
    """Tagged result of trying to provide a regime view-model to the report.

    The combined report always renders a regime section; this state tells the
    renderer which presentation to use (full body / stale banner / unavailable
    card) without scattering ``is None`` checks across the render tree.
    """

    state: Literal["ok", "stale", "missing", "engine_error"]
    mode_used: RegimeMode
    view_model: RegimeHtmlViewModel | None
    regime_as_of: str | None
    last_run_at: datetime | None
    error_message: str | None

    @property
    def is_renderable(self) -> bool:
        """True when the view-model is populated enough to render the full body."""
        return self.view_model is not None and self.state in {"ok", "stale"}


# Hook seam for tests — production calls the real workflow.
RefreshCallable = Callable[..., object]


def _default_refresh_callable() -> RefreshCallable:
    # Import lazily so loading the provider doesn't pull the whole workflow
    # graph (FRED + Yahoo clients) into modules that only consume cached data.
    from market_helper.workflows.run_regime_report import (
        refresh_data_and_run_regime_report,
    )

    return refresh_data_and_run_regime_report


def provide_regime_view_model(
    *,
    regime_path: Path,
    mode: RegimeMode = "refresh-if-stale",
    policy_path: str | Path | None = None,
    refresh_callable: RefreshCallable | None = None,
    now: Callable[[], datetime] | None = None,
) -> RegimeArtifactState:
    """Resolve the regime view-model for the combined report per ``mode``.

    The function never raises on engine failure — the report always renders.
    Engine exceptions are caught and surfaced as ``state="engine_error"`` with
    the original message, after which we still try to load any pre-existing
    snapshot so the user gets *some* data rather than none.
    """
    resolved_now = now or (lambda: datetime.now(timezone.utc))
    refresh = refresh_callable or _default_refresh_callable()

    should_refresh = False
    if mode == "force-refresh":
        should_refresh = True
    elif mode == "refresh-if-stale":
        should_refresh = _needs_refresh(regime_path, now=resolved_now())

    refresh_error: str | None = None
    if should_refresh:
        try:
            refresh(output_regime_path=regime_path)
        except Exception as exc:  # noqa: BLE001 — engine failure must not break the report
            logger.warning(
                "Regime refresh (mode=%s) failed for %s: %s", mode, regime_path, exc
            )
            refresh_error = str(exc)

    return _load_state(
        regime_path=regime_path,
        mode=mode,
        policy_path=policy_path,
        now=resolved_now,
        refresh_error=refresh_error,
    )


def _needs_refresh(regime_path: Path, *, now: datetime) -> bool:
    """Refresh trigger for ``refresh-if-stale``.

    Refresh when the artifact is missing OR its latest snapshot's date lags
    the expected T-1 trading day. We peek at the file's last row's ``date``
    field rather than building the full view-model — keeps the trigger cheap
    when the artifact turns out to be fresh.
    """
    if not regime_path.exists():
        return True
    latest_as_of = _peek_latest_as_of(regime_path)
    if latest_as_of is None:
        # Malformed file — let the load path handle it via engine_error.
        return False
    return is_as_of_stale(latest_as_of, now=now)


def _peek_latest_as_of(regime_path: Path) -> str | None:
    """Return the latest snapshot's ``date`` field, or None on read failure."""
    try:
        payload = json.loads(regime_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list) or not payload:
        return None
    last = payload[-1]
    if not isinstance(last, dict):
        return None
    value = last.get("date")
    if value is None:
        return None
    return str(value)


def _load_state(
    *,
    regime_path: Path,
    mode: RegimeMode,
    policy_path: str | Path | None,
    now: Callable[[], datetime],
    refresh_error: str | None,
) -> RegimeArtifactState:
    if not regime_path.exists():
        return RegimeArtifactState(
            state="engine_error" if refresh_error else "missing",
            mode_used=mode,
            view_model=None,
            regime_as_of=None,
            last_run_at=None,
            error_message=refresh_error
            or f"Regime artifact not found at {regime_path}",
        )

    last_run_at = datetime.fromtimestamp(regime_path.stat().st_mtime, tz=timezone.utc)

    try:
        view_model = build_regime_html_view_model(
            regime_path=regime_path,
            policy_path=policy_path,
        )
    except Exception as exc:  # noqa: BLE001 — parse failure becomes engine_error
        logger.warning("Failed to build regime view-model from %s: %s", regime_path, exc)
        return RegimeArtifactState(
            state="engine_error",
            mode_used=mode,
            view_model=None,
            regime_as_of=None,
            last_run_at=last_run_at,
            error_message=refresh_error
            or f"Regime artifact at {regime_path} could not be parsed ({exc})",
        )

    # File loaded fine, but the engine may have failed *during* a refresh attempt
    # and we fell back to the prior snapshot. Surface that as engine_error so the
    # UI can warn while still showing whatever data we have.
    if refresh_error is not None:
        return RegimeArtifactState(
            state="engine_error",
            mode_used=mode,
            view_model=view_model,
            regime_as_of=view_model.as_of or None,
            last_run_at=last_run_at,
            error_message=refresh_error,
        )

    state: Literal["ok", "stale"]
    if is_as_of_stale(view_model.as_of, now=now()):
        state = "stale"
    else:
        state = "ok"

    return RegimeArtifactState(
        state=state,
        mode_used=mode,
        view_model=view_model,
        regime_as_of=view_model.as_of or None,
        last_run_at=last_run_at,
        error_message=None,
    )


__all__ = [
    "RegimeArtifactState",
    "RegimeMode",
    "provide_regime_view_model",
]
