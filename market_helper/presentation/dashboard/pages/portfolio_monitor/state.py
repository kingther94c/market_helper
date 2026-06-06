"""Page/form state, constants, IBKR probing, and pure helpers for `/portfolio`.

No NiceGUI rendering and no service orchestration live here — just the data
model (form + page dataclasses), environment/IBKR resolution, the stale-page
cache, small pure helpers, and the initial-state builder. This keeps the bulk of
the surface unit-testable without a UI.
"""
from __future__ import annotations

import os
import socket
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from market_helper.application.portfolio_monitor import (
    GeneratedReportArtifact,
    InMemoryUiProgressSink,
    PortfolioMonitorQueryService,
    PortfolioReportData,
)
from market_helper.config.local_env import read_local_config_value

# `__file__` is `.../pages/portfolio_monitor/state.py`; parents[5] is the repo
# root (portfolio_monitor → pages → dashboard → presentation → market_helper →
# root). Keep this in lock-step with the file's depth if it ever moves.
DEFAULT_CANONICAL_LOCAL_ENV_PATH = (
    Path(__file__).resolve().parents[5] / "configs" / "portfolio_monitor" / "local.env"
)
DEFAULT_IBKR_FLEX_QUERY_ID_ENV_VAR = "IBKR_FLEX_QUERY_ID"
DEFAULT_IBKR_FLEX_TOKEN_ENV_VAR = "IBKR_FLEX_TOKEN"
DEFAULT_PROD_ACCOUNT_ID_ENV_VAR = "DEFAULT_PROD_ACCOUNT_ID"
DEFAULT_DEV_ACCOUNT_ID_ENV_VAR = "DEFAULT_DEV_ACCOUNT_ID"
IBKR_PORT_ENV_VAR = "IBKR_PORT"
IBKR_HOST_ENV_VAR = "IBKR_HOST"
DEFAULT_IBKR_PORT = "7497"  # TWS paper. IB Gateway uses 4001 (live) / 4002 (paper); set IBKR_PORT to override per machine.
DEFAULT_IBKR_HOST = "127.0.0.1"
# Order matters: IB Gateway first (Win users typically run Gateway), then TWS.
# Mac users on TWS paper (7497) pay ~600ms one-time probe latency unless they
# set IBKR_PORT explicitly.
_IBKR_PORT_PROBE_CANDIDATES: tuple[str, ...] = ("4001", "4002", "7496", "7497")
_IBKR_PORT_PROBE_TIMEOUT_S = 0.15


@dataclass
class PortfolioArtifactFormState:
    positions_csv_path: str = ""
    performance_output_dir: str = ""
    performance_history_path: str = ""
    performance_report_csv_path: str = ""
    returns_path: str = ""
    proxy_path: str = ""
    regime_path: str = ""
    security_reference_path: str = ""
    risk_config_path: str = ""
    allocation_policy_path: str = ""
    vol_method: str = "geomean_1m_3m"
    inter_asset_corr: str = "historical"


@dataclass
class LiveActionFormState:
    output_path: str = ""
    host: str = DEFAULT_IBKR_HOST
    port: str = DEFAULT_IBKR_PORT
    client_id: str = "1"
    account_id: str = ""
    timeout: str = "4.0"
    as_of: str = ""


@dataclass
class FlexActionFormState:
    output_dir: str = ""
    flex_xml_path: str = ""
    query_id: str = ""
    token: str = ""
    from_date: str = ""
    to_date: str = ""
    period: str = ""
    xml_output_path: str = ""


@dataclass
class RegimeActionFormState:
    output_regime_path: str = "data/artifacts/regime_detection/regime_snapshots.json"
    output_html_path: str = "data/artifacts/regime_detection/regime_report.html"
    max_age_days: str = "7"
    force_refresh: bool = False
    latest_only: bool = False


@dataclass
class ExportActionFormState:
    output_path: str = ""


@dataclass
class ReferenceActionFormState:
    security_reference_output_path: str = ""
    etf_symbols: str = ""
    etf_output_path: str = ""
    api_key: str = ""


@dataclass
class ActionStatusState:
    status: str = "idle"
    message: str = "Not run yet"
    progress_summary: str = "No recent progress"
    last_output_path: str = "n/a"


@dataclass(frozen=True)
class JobHistoryEntry:
    """One past run of a top-level action — for the drawer's history panel (P8)."""
    action_name: str
    started_at: datetime
    finished_at: datetime
    status: str  # "success" | "error"
    message: str
    output_path: str
    duration_seconds: float


_JOB_HISTORY_MAX_ENTRIES = 10


@dataclass
class PortfolioPageState:
    artifact_form: PortfolioArtifactFormState
    live_form: LiveActionFormState
    flex_form: FlexActionFormState
    regime_form: RegimeActionFormState
    export_form: ExportActionFormState
    reference_form: ReferenceActionFormState
    report_data: PortfolioReportData | None = None
    generated_report: GeneratedReportArtifact | None = None
    warnings: list[str] = field(default_factory=list)
    is_loading: bool = False
    load_error: str | None = None
    active_job: str | None = None
    active_job_started_at: datetime | None = None
    status_message: str = "Ready"
    selected_top_tab: str = "report"
    progress_sink: InMemoryUiProgressSink = field(default_factory=InMemoryUiProgressSink)
    action_statuses: dict[str, ActionStatusState] = field(
        default_factory=lambda: {
            "refresh": ActionStatusState(message="Not run yet"),
            "live": ActionStatusState(),
            "flex": ActionStatusState(),
            "combined": ActionStatusState(message="Not generated yet"),
            "regime-run": ActionStatusState(message="Not run yet"),
            "regime-refresh": ActionStatusState(message="Not refreshed yet"),
            "security-reference": ActionStatusState(),
            "etf": ActionStatusState(),
            "yahoo": ActionStatusState(),
        }
    )
    # P8: ring buffer of recent runs surfaced in the operate drawer.
    job_history: list[JobHistoryEntry] = field(default_factory=list)


_STALE_PAGE_CACHE: dict[str, Any] | None = None


def _cache_stale_page_state(state: PortfolioPageState) -> None:
    global _STALE_PAGE_CACHE
    _STALE_PAGE_CACHE = {
        "artifact_form": deepcopy(state.artifact_form),
        "live_form": deepcopy(state.live_form),
        "flex_form": deepcopy(state.flex_form),
        "regime_form": deepcopy(state.regime_form),
        "export_form": deepcopy(state.export_form),
        "reference_form": deepcopy(state.reference_form),
        "report_data": deepcopy(state.report_data),
        "generated_report": deepcopy(state.generated_report),
        "warnings": list(state.warnings),
        "status_message": state.status_message,
        "selected_top_tab": state.selected_top_tab,
        "action_statuses": deepcopy(state.action_statuses),
        "job_history": list(state.job_history),
    }


def _restore_stale_page_state(state: PortfolioPageState) -> None:
    if _STALE_PAGE_CACHE is None:
        return
    state.artifact_form = deepcopy(_STALE_PAGE_CACHE["artifact_form"])
    state.live_form = deepcopy(_STALE_PAGE_CACHE["live_form"])
    state.flex_form = deepcopy(_STALE_PAGE_CACHE["flex_form"])
    state.regime_form = deepcopy(_STALE_PAGE_CACHE.get("regime_form", state.regime_form))
    state.export_form = deepcopy(_STALE_PAGE_CACHE["export_form"])
    state.reference_form = deepcopy(_STALE_PAGE_CACHE["reference_form"])
    state.report_data = deepcopy(_STALE_PAGE_CACHE["report_data"])
    state.generated_report = deepcopy(_STALE_PAGE_CACHE["generated_report"])
    state.warnings = list(_STALE_PAGE_CACHE["warnings"])
    state.status_message = str(_STALE_PAGE_CACHE["status_message"])
    state.selected_top_tab = str(_STALE_PAGE_CACHE["selected_top_tab"])
    state.action_statuses = deepcopy(_STALE_PAGE_CACHE["action_statuses"])
    state.job_history = list(_STALE_PAGE_CACHE.get("job_history", []))
    state.load_error = None
    state.is_loading = False
    state.active_job = None
    state.active_job_started_at = None


def _clear_stale_page_cache() -> None:
    global _STALE_PAGE_CACHE
    _STALE_PAGE_CACHE = None


def _report_data_matches_current_local_date(report_data: Any) -> bool:
    as_of = str(getattr(report_data, "as_of", "") or "").strip()
    if not as_of:
        return True
    try:
        report_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError:
        return True
    if report_dt.tzinfo is not None:
        report_dt = report_dt.astimezone()
    return report_dt.date() == datetime.now().astimezone().date()


_TOP_TAB_KEYS = {"report", "artifacts"}


def _resolve_top_tab_key(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "": "report",
        "html": "report",
        "performance": "report",
        "risk": "report",
    }
    if normalized in _TOP_TAB_KEYS:
        return normalized
    return aliases.get(normalized, "report")


def _update_top_tab(state: PortfolioPageState, value: str) -> None:
    mapping = {"Report": "report", "Artifacts": "artifacts"}
    key = mapping.get(str(value or "").strip())
    if key is not None:
        state.selected_top_tab = key


def _positions_csv_ready_for_autoload(value: str) -> bool:
    normalized = value.strip()
    return bool(normalized) and Path(normalized).exists()


def _initial_dashboard_status(positions_csv_path: str) -> str:
    if _positions_csv_ready_for_autoload(positions_csv_path):
        return "Ready. Load report data or generate the HTML report from current artifacts."
    return "Positions CSV not found. Run Live Refresh or enter a valid artifact path."


def _resolve_local_env_value(key: str) -> str:
    normalized_key = str(key).strip()
    if not normalized_key:
        return ""
    from_process_env = str(os.environ.get(normalized_key, "")).strip()
    if from_process_env:
        return from_process_env
    return read_local_config_value(normalized_key, default_path=DEFAULT_CANONICAL_LOCAL_ENV_PATH)


def _resolve_default_live_account_id() -> str:
    return _resolve_local_env_value(DEFAULT_PROD_ACCOUNT_ID_ENV_VAR) or _resolve_local_env_value(
        DEFAULT_DEV_ACCOUNT_ID_ENV_VAR
    )


def _probe_local_ibkr_port(
    *,
    host: str = DEFAULT_IBKR_HOST,
    candidates: tuple[str, ...] = _IBKR_PORT_PROBE_CANDIDATES,
    timeout: float = _IBKR_PORT_PROBE_TIMEOUT_S,
) -> str | None:
    """TCP-probe candidate IBKR ports; return first one that accepts a
    connection, or None if none responds. A successful TCP connect only proves
    *something* is listening — it does not authenticate ib_async — so the
    actual Live action can still fail if Gateway is mid-startup. This is a
    best-effort default-picker, not a health check.
    """
    for port in candidates:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, int(port)))
        except (OSError, ValueError):
            continue
        else:
            return port
        finally:
            try:
                sock.close()
            except OSError:
                pass
    return None


def _resolve_default_ibkr_port() -> str:
    """Pick the dashboard's default IBKR port.

    Priority order:

    1. ``IBKR_PORT`` env var (process env, then local.env) — explicit user
       choice always wins, no probing.
    2. TCP probe of local IB Gateway (4001/4002) then TWS (7496/7497) — auto-
       picks whichever is running. Useful when one machine runs Gateway and
       the other runs TWS off the same local.env.
    3. ``DEFAULT_IBKR_PORT`` (7497, TWS paper) as final fallback.
    """
    explicit = _resolve_local_env_value(IBKR_PORT_ENV_VAR)
    if explicit:
        return explicit
    probed = _probe_local_ibkr_port(host=_resolve_default_ibkr_host())
    if probed:
        return probed
    return DEFAULT_IBKR_PORT


def _resolve_default_ibkr_host() -> str:
    return _resolve_local_env_value(IBKR_HOST_ENV_VAR) or DEFAULT_IBKR_HOST


def _existing_cached_position_csv(form_path: str) -> Path | None:
    """Return the cached position CSV if it exists at the form's currently-
    bound path. Used as a graceful fallback when TWS is unreachable so the
    dashboard can at least render the most recent snapshot."""
    cleaned = (form_path or "").strip()
    if not cleaned:
        return None
    candidate = Path(cleaned)
    return candidate if candidate.is_file() else None


def _build_initial_state(query_service: PortfolioMonitorQueryService) -> PortfolioPageState:
    inputs = query_service.resolve_inputs()
    positions_path = str(inputs.positions_csv_path or "")
    performance_output_dir = str(inputs.performance_output_dir or "")
    default_output_path = (
        str(Path(performance_output_dir).parent / "portfolio_dashboard_report.html")
        if performance_output_dir
        else "portfolio_dashboard_report.html"
    )
    return PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(
            positions_csv_path=positions_path,
            performance_output_dir=performance_output_dir,
            performance_history_path=str(inputs.performance_history_path or ""),
            performance_report_csv_path=str(inputs.performance_report_csv_path or ""),
            returns_path=str(inputs.returns_path or ""),
            proxy_path=str(inputs.proxy_path or ""),
            regime_path=str(inputs.regime_path or ""),
            security_reference_path=str(inputs.security_reference_path or ""),
            risk_config_path=str(inputs.risk_config_path or ""),
            allocation_policy_path=str(inputs.allocation_policy_path or ""),
            vol_method=str(inputs.vol_method or "geomean_1m_3m"),
            inter_asset_corr=str(inputs.inter_asset_corr or "historical"),
        ),
        live_form=LiveActionFormState(
            output_path=positions_path,
            host=_resolve_default_ibkr_host(),
            port=_resolve_default_ibkr_port(),
            account_id=_resolve_default_live_account_id(),
        ),
        flex_form=FlexActionFormState(
            output_dir=performance_output_dir,
            query_id=_resolve_local_env_value(DEFAULT_IBKR_FLEX_QUERY_ID_ENV_VAR),
            token=_resolve_local_env_value(DEFAULT_IBKR_FLEX_TOKEN_ENV_VAR),
        ),
        regime_form=RegimeActionFormState(),
        export_form=ExportActionFormState(output_path=default_output_path),
        reference_form=ReferenceActionFormState(
            security_reference_output_path=str(inputs.security_reference_path or "")
        ),
        status_message=_initial_dashboard_status(positions_path),
    )


# ----- small parse helpers (form string -> typed) ---------------------------


def _required_text(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} is required")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_int(value: str, label: str) -> int:
    try:
        return int(_required_text(value, label))
    except ValueError as exc:
        raise ValueError(f"{label} must be an integer") from exc


def _parse_float(value: str, label: str) -> float:
    try:
        return float(_required_text(value, label))
    except ValueError as exc:
        raise ValueError(f"{label} must be a number") from exc


# ----- progress event formatting (pure) -------------------------------------


def _summarize_progress(state: PortfolioPageState) -> str:
    if not state.progress_sink.events:
        return "No progress events"
    latest = state.progress_sink.events[-1]
    progress = _format_progress_event(latest)
    if latest.detail and progress:
        return f"{latest.label}: {progress} {latest.detail}"
    if latest.detail:
        return f"{latest.label}: {latest.detail}"
    if progress:
        return f"{latest.label}: {progress}"
    return latest.label


def _format_progress_event(event: Any) -> str:
    if event.completed is not None and event.total is not None:
        return f"{event.completed} / {event.total}"
    if event.current is not None and event.total is not None:
        return f"{event.current} / {event.total}"
    return event.detail or ""
