from __future__ import annotations

from datetime import datetime, timedelta

from market_helper.application.portfolio_monitor import (
    GenerateCombinedReportInputs,
    InMemoryUiProgressSink,
    PortfolioReportInputs,
    UiProgressEvent,
)
from market_helper.presentation.dashboard.pages.portfolio import (
    ActionStatusState,
    ExportActionFormState,
    FlexActionFormState,
    LiveActionFormState,
    PortfolioArtifactFormState,
    PortfolioPageState,
    ReferenceActionFormState,
    RegimeActionFormState,
    _action_progress_summary,
    _build_initial_state,
    _cache_stale_page_state,
    _classify_warning,
    _restore_stale_page_state,
    _artifact_inputs_from_form,
    _combined_inputs_from_form,
    _etf_inputs_from_form,
    _flex_inputs_from_form,
    _initial_dashboard_status,
    _live_inputs_from_form,
    _positions_csv_ready_for_autoload,
    _regime_refresh_inputs_from_form,
    _regime_run_inputs_from_form,
    _report_data_matches_current_local_date,
    _existing_cached_position_csv,
    _probe_local_ibkr_port,
    _resolve_default_ibkr_port,
)
import market_helper.presentation.dashboard.pages.portfolio as portfolio_page


def test_artifact_form_converts_strings_to_query_inputs() -> None:
    inputs = _artifact_inputs_from_form(
        PortfolioArtifactFormState(
            positions_csv_path="data/positions.csv",
            performance_output_dir="data/flex",
            performance_history_path="",
            performance_report_csv_path="data/flex/performance.csv",
            returns_path="",
            proxy_path="data/proxy.json",
            regime_path="",
            security_reference_path="data/security_reference.csv",
            risk_config_path="configs/report.yaml",
            allocation_policy_path="",
            vol_method="ewma",
        )
    )

    assert isinstance(inputs, PortfolioReportInputs)
    assert inputs.positions_csv_path == "data/positions.csv"
    assert inputs.performance_history_path is None
    assert inputs.performance_report_csv_path == "data/flex/performance.csv"
    assert inputs.proxy_path == "data/proxy.json"
    assert inputs.vol_method == "ewma"


def test_action_form_converters_validate_numeric_and_symbol_inputs() -> None:
    live = _live_inputs_from_form(
        LiveActionFormState(output_path="data/live.csv", host="127.0.0.1", port="7497", client_id="9", timeout="5.5")
    )
    flex = _flex_inputs_from_form(FlexActionFormState(output_dir="data/flex", flex_xml_path="data/raw.xml"))
    etf = _etf_inputs_from_form(
        ReferenceActionFormState(etf_symbols="DBMF, qqq", etf_output_path="configs/sector.json", api_key="demo")
    )
    regime_run = _regime_run_inputs_from_form(
        RegimeActionFormState(output_regime_path="data/regime.json", output_html_path="data/regime.html")
    )
    regime_refresh = _regime_refresh_inputs_from_form(
        RegimeActionFormState(
            output_regime_path="data/regime.json",
            output_html_path="data/regime.html",
            max_age_days="3",
            force_refresh=True,
            latest_only=True,
        )
    )

    assert live.port == 7497
    assert live.client_id == 9
    assert live.timeout == 5.5
    assert flex.output_dir == "data/flex"
    assert etf.symbols == ["DBMF", "QQQ"]
    assert regime_run.output_html_path == "data/regime.html"
    assert regime_refresh.max_age_days == 3
    assert regime_refresh.force_refresh is True
    assert regime_refresh.latest_only is True


def test_combined_export_form_reuses_artifact_form_inputs() -> None:
    state = PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(
            positions_csv_path="data/positions.csv",
            performance_output_dir="data/flex",
            performance_history_path="data/flex/nav.feather",
            performance_report_csv_path="data/flex/report.csv",
            returns_path="data/returns.json",
            proxy_path="data/proxy.json",
            regime_path="data/regime.json",
            security_reference_path="data/security_reference.csv",
            risk_config_path="configs/report.yaml",
            allocation_policy_path="configs/policy.yaml",
            vol_method="5y_realized",
        ),
        live_form=LiveActionFormState(),
        flex_form=FlexActionFormState(),
        regime_form=RegimeActionFormState(),
        export_form=ExportActionFormState(output_path="outputs/combined.html"),
        reference_form=ReferenceActionFormState(),
    )

    combined = _combined_inputs_from_form(state)

    assert isinstance(combined, GenerateCombinedReportInputs)
    assert combined.positions_csv_path == "data/positions.csv"
    assert combined.performance_output_dir == "data/flex"
    assert combined.output_path == "outputs/combined.html"
    assert combined.vol_method == "5y_realized"


def test_build_initial_state_keeps_internal_vol_method_key() -> None:
    class QueryService:
        def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
            return PortfolioReportInputs(
                positions_csv_path="data/positions.csv",
                performance_output_dir="data/flex",
                vol_method="geomean_1m_3m",
            )

    state = _build_initial_state(QueryService())

    assert state.artifact_form.vol_method == "geomean_1m_3m"


def test_positions_csv_ready_for_autoload_requires_existing_file(tmp_path) -> None:
    existing = tmp_path / "positions.csv"
    existing.write_text("as_of\n", encoding="utf-8")

    assert _positions_csv_ready_for_autoload(str(existing)) is True
    assert _positions_csv_ready_for_autoload(str(tmp_path / "missing.csv")) is False
    assert _positions_csv_ready_for_autoload("") is False


def test_initial_dashboard_status_reflects_local_artifact_readiness(tmp_path) -> None:
    existing = tmp_path / "positions.csv"
    existing.write_text("as_of\n", encoding="utf-8")

    assert _initial_dashboard_status(str(existing)) == "Ready. Load report data or generate the HTML report from current artifacts."
    assert _initial_dashboard_status(str(tmp_path / "missing.csv")) == (
        "Positions CSV not found. Run Live Refresh or enter a valid artifact path."
    )


def test_build_initial_state_uses_missing_positions_status_when_default_artifact_absent() -> None:
    class QueryService:
        def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
            return PortfolioReportInputs(
                positions_csv_path="data/missing.csv",
                performance_output_dir="data/flex",
            )

    state = _build_initial_state(QueryService())

    assert state.status_message == "Positions CSV not found. Run Live Refresh or enter a valid artifact path."


def test_build_initial_state_prefills_flex_credentials_from_local_env(tmp_path, monkeypatch) -> None:
    local_env = tmp_path / "local.env"
    local_env.write_text(
        "\n".join(
            [
                'IBKR_FLEX_QUERY_ID="demo-query"',
                'IBKR_FLEX_TOKEN="demo-token"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MARKET_HELPER_GDRIVE_ROOT", raising=False)
    monkeypatch.setattr(
        "market_helper.presentation.dashboard.pages.portfolio.DEFAULT_CANONICAL_LOCAL_ENV_PATH",
        local_env,
    )

    class QueryService:
        def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
            return PortfolioReportInputs(
                positions_csv_path="data/positions.csv",
                performance_output_dir="data/flex",
            )

    state = _build_initial_state(QueryService())

    assert state.flex_form.query_id == "demo-query"
    assert state.flex_form.token == "demo-token"


def test_build_initial_state_prefills_ibkr_port_and_host_from_env(tmp_path, monkeypatch) -> None:
    """IB Gateway users (port 4001/4002) shouldn't have to retype the port
    every time they reload the dashboard."""
    local_env = tmp_path / "local.env"
    local_env.write_text(
        "\n".join(
            [
                'IBKR_PORT="4001"',
                'IBKR_HOST="192.168.1.10"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("IBKR_PORT", raising=False)
    monkeypatch.delenv("IBKR_HOST", raising=False)
    monkeypatch.delenv("MARKET_HELPER_GDRIVE_ROOT", raising=False)
    monkeypatch.setattr(
        "market_helper.presentation.dashboard.pages.portfolio.DEFAULT_CANONICAL_LOCAL_ENV_PATH",
        local_env,
    )

    class QueryService:
        def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
            return PortfolioReportInputs(
                positions_csv_path="data/positions.csv",
                performance_output_dir="data/flex",
            )

    state = _build_initial_state(QueryService())

    assert state.live_form.port == "4001"
    assert state.live_form.host == "192.168.1.10"


def test_build_initial_state_defaults_to_tws_paper_port_when_unset(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("IBKR_PORT", raising=False)
    monkeypatch.delenv("IBKR_HOST", raising=False)
    monkeypatch.delenv("MARKET_HELPER_GDRIVE_ROOT", raising=False)
    monkeypatch.setattr(
        "market_helper.presentation.dashboard.pages.portfolio.DEFAULT_CANONICAL_LOCAL_ENV_PATH",
        tmp_path / "no-such.env",
    )
    # Force the probe to find nothing so the fallback path is exercised.
    monkeypatch.setattr(portfolio_page, "_probe_local_ibkr_port", lambda **_: None)

    class QueryService:
        def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
            return PortfolioReportInputs(
                positions_csv_path="data/positions.csv",
                performance_output_dir="data/flex",
            )

    state = _build_initial_state(QueryService())

    assert state.live_form.port == "7497"
    assert state.live_form.host == "127.0.0.1"


def test_probe_local_ibkr_port_returns_first_listening_port(monkeypatch) -> None:
    """Probe walks candidates in order and returns the first one that accepts."""
    listening = {"4002"}  # IB Gateway paper port — second candidate

    class _FakeSock:
        def __init__(self, *_args, **_kwargs):
            self._port: int | None = None
        def settimeout(self, _t): pass
        def connect(self, address):
            self._port = int(address[1])
            if str(self._port) not in listening:
                raise ConnectionRefusedError("refused")
        def close(self): pass

    monkeypatch.setattr(portfolio_page.socket, "socket", _FakeSock)
    assert _probe_local_ibkr_port() == "4002"


def test_probe_local_ibkr_port_returns_none_when_nothing_listens(monkeypatch) -> None:
    class _FakeSock:
        def __init__(self, *_args, **_kwargs): pass
        def settimeout(self, _t): pass
        def connect(self, _address):
            raise ConnectionRefusedError("nothing here")
        def close(self): pass

    monkeypatch.setattr(portfolio_page.socket, "socket", _FakeSock)
    assert _probe_local_ibkr_port() is None


def test_resolve_default_ibkr_port_env_var_skips_probe(monkeypatch, tmp_path) -> None:
    """Explicit env var wins and the probe never runs (so explicit choices are
    instant)."""
    monkeypatch.setenv("IBKR_PORT", "9999")
    probe_called = {"yes": False}

    def _exploding_probe(**_kwargs):
        probe_called["yes"] = True
        return "4001"

    monkeypatch.setattr(portfolio_page, "_probe_local_ibkr_port", _exploding_probe)
    assert _resolve_default_ibkr_port() == "9999"
    assert probe_called["yes"] is False


def test_existing_cached_position_csv_returns_path_when_present(tmp_path) -> None:
    csv = tmp_path / "live_ibkr_position_report.csv"
    csv.write_text("as_of\n2026-05-15\n", encoding="utf-8")
    assert _existing_cached_position_csv(str(csv)) == csv


def test_existing_cached_position_csv_returns_none_when_missing(tmp_path) -> None:
    missing = tmp_path / "no-such.csv"
    assert _existing_cached_position_csv(str(missing)) is None
    assert _existing_cached_position_csv("") is None
    assert _existing_cached_position_csv("   ") is None


def test_build_initial_state_prefills_live_account_id_from_local_env(tmp_path, monkeypatch) -> None:
    local_env = tmp_path / "local.env"
    local_env.write_text(
        'DEFAULT_PROD_ACCOUNT_ID="U0000000"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("MARKET_HELPER_GDRIVE_ROOT", raising=False)
    monkeypatch.setattr(
        "market_helper.presentation.dashboard.pages.portfolio.DEFAULT_CANONICAL_LOCAL_ENV_PATH",
        local_env,
    )

    class QueryService:
        def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
            return PortfolioReportInputs(
                positions_csv_path="data/positions.csv",
                performance_output_dir="data/flex",
            )

    state = _build_initial_state(QueryService())

    assert state.live_form.account_id == "U0000000"


def test_build_initial_state_prefers_gdrive_root_local_env(tmp_path, monkeypatch) -> None:
    default_env = tmp_path / "local.env"
    gdrive_root = tmp_path / "005 Portfolio"
    gdrive_root.mkdir()
    override_env = gdrive_root / "local.env"
    default_env.write_text('IBKR_FLEX_QUERY_ID="default-query"\n', encoding="utf-8")
    override_env.write_text('IBKR_FLEX_QUERY_ID="synced-query"\n', encoding="utf-8")
    monkeypatch.setenv("MARKET_HELPER_GDRIVE_ROOT", str(gdrive_root))
    monkeypatch.setattr(
        "market_helper.presentation.dashboard.pages.portfolio.DEFAULT_CANONICAL_LOCAL_ENV_PATH",
        default_env,
    )

    class QueryService:
        def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
            return PortfolioReportInputs(
                positions_csv_path="data/positions.csv",
                performance_output_dir="data/flex",
            )

    state = _build_initial_state(QueryService())

    assert state.flex_form.query_id == "synced-query"


def test_action_progress_summary_uses_live_x_of_total_while_action_runs() -> None:
    sink = InMemoryUiProgressSink()
    sink.record(UiProgressEvent(kind="stage", label="IBKR Flex report", current=2, total=5))
    state = PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(),
        live_form=LiveActionFormState(),
        flex_form=FlexActionFormState(),
        regime_form=RegimeActionFormState(),
        export_form=ExportActionFormState(),
        reference_form=ReferenceActionFormState(),
        active_job="flex",
        progress_sink=sink,
        action_statuses={
            "live": ActionStatusState(),
            "flex": ActionStatusState(status="running", progress_summary="Starting..."),
            "combined": ActionStatusState(),
            "regime-run": ActionStatusState(),
            "regime-refresh": ActionStatusState(),
            "security-reference": ActionStatusState(),
            "etf": ActionStatusState(),
        },
    )

    assert _action_progress_summary(state, "flex") == "IBKR Flex report: 2 / 5"


def test_restore_stale_page_state_rehydrates_cached_report_data() -> None:
    cached_state = PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(
            positions_csv_path="data/cached_positions.csv",
            performance_output_dir="data/cached_flex",
        ),
        live_form=LiveActionFormState(account_id="U123"),
        flex_form=FlexActionFormState(query_id="cached-query"),
        regime_form=RegimeActionFormState(output_html_path="outputs/regime.html"),
        export_form=ExportActionFormState(output_path="outputs/cached.html"),
        reference_form=ReferenceActionFormState(security_reference_output_path="data/security_reference.csv"),
        report_data="cached report data",  # type: ignore[arg-type]
        warnings=["cached warning"],
        status_message="Loaded cached report data",
        selected_top_tab="artifacts",
        action_statuses={
            "refresh": ActionStatusState(),
            "live": ActionStatusState(status="success", message="Live positions refreshed"),
            "flex": ActionStatusState(),
            "combined": ActionStatusState(),
            "regime-run": ActionStatusState(),
            "regime-refresh": ActionStatusState(),
            "security-reference": ActionStatusState(),
            "etf": ActionStatusState(),
        },
    )
    fresh_state = PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(),
        live_form=LiveActionFormState(),
        flex_form=FlexActionFormState(),
        regime_form=RegimeActionFormState(),
        export_form=ExportActionFormState(),
        reference_form=ReferenceActionFormState(),
    )

    _cache_stale_page_state(cached_state)
    _restore_stale_page_state(fresh_state)

    assert fresh_state.report_data == "cached report data"
    assert fresh_state.warnings == ["cached warning"]
    assert fresh_state.status_message == "Loaded cached report data"
    assert fresh_state.selected_top_tab == "artifacts"
    assert fresh_state.artifact_form.positions_csv_path == "data/cached_positions.csv"
    assert fresh_state.live_form.account_id == "U123"
    assert fresh_state.action_statuses["live"].message == "Live positions refreshed"


def test_restore_stale_page_state_uses_deep_copy() -> None:
    cached_state = PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(positions_csv_path="data/cached_positions.csv"),
        live_form=LiveActionFormState(),
        flex_form=FlexActionFormState(),
        regime_form=RegimeActionFormState(),
        export_form=ExportActionFormState(),
        reference_form=ReferenceActionFormState(),
        report_data={"as_of": "2026-04-21"},  # type: ignore[arg-type]
        warnings=["cached warning"],
    )
    restored_state = PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(),
        live_form=LiveActionFormState(),
        flex_form=FlexActionFormState(),
        regime_form=RegimeActionFormState(),
        export_form=ExportActionFormState(),
        reference_form=ReferenceActionFormState(),
    )

    _cache_stale_page_state(cached_state)
    _restore_stale_page_state(restored_state)

    restored_state.artifact_form.positions_csv_path = "data/modified.csv"
    restored_state.warnings.append("new warning")
    restored_state.report_data["as_of"] = "changed"  # type: ignore[index]

    second_restore = PortfolioPageState(
        artifact_form=PortfolioArtifactFormState(),
        live_form=LiveActionFormState(),
        flex_form=FlexActionFormState(),
        regime_form=RegimeActionFormState(),
        export_form=ExportActionFormState(),
        reference_form=ReferenceActionFormState(),
    )
    _restore_stale_page_state(second_restore)

    assert second_restore.artifact_form.positions_csv_path == "data/cached_positions.csv"
    assert second_restore.warnings == ["cached warning"]
    assert second_restore.report_data["as_of"] == "2026-04-21"  # type: ignore[index]


def test_report_data_matches_current_local_date_accepts_same_local_date() -> None:
    today = datetime.now().astimezone().date().isoformat()

    class ReportData:
        as_of = f"{today}T09:30:00+08:00"

    assert _report_data_matches_current_local_date(ReportData()) is True


def test_report_data_matches_current_local_date_rejects_different_local_date() -> None:
    yesterday = (datetime.now().astimezone().date() - timedelta(days=1)).isoformat()

    class ReportData:
        as_of = f"{yesterday}T23:30:00+08:00"

    assert _report_data_matches_current_local_date(ReportData()) is False


def test_classify_warning_maps_missing_history_to_flex_action() -> None:
    assert _classify_warning(
        "Performance history file not found: /tmp/nav_cashflow_history.feather"
    ) == ("flex", "Run Flex Refresh")
    assert _classify_warning(
        "Performance history file is empty: /tmp/nav_cashflow_history.feather"
    ) == ("flex", "Run Flex Refresh")
    assert _classify_warning(
        "Dated performance report CSV is missing; only history-derived metrics are available."
    ) == ("flex", "Run Flex Refresh")


def test_classify_warning_maps_benchmark_cache_to_yahoo_action() -> None:
    assert _classify_warning(
        "SPY/BIL benchmark return cache is missing or empty; performance benchmark trace and cash-based Sharpe may be omitted."
    ) == ("yahoo", "Refresh Benchmark Cache")


def test_classify_warning_returns_none_for_unrelated_warning() -> None:
    # Path-not-configured is informational — the user must edit the artifact
    # form, no single button can fix it, so it must stay an unclassified
    # muted warning rather than being promoted to a remediation banner.
    assert _classify_warning("Performance history path is not configured.") is None
    assert _classify_warning("") is None


def test_served_artifact_url_uses_pretty_alias_for_canonical_dashboard_report(
    monkeypatch, tmp_path
) -> None:
    """The canonical combined report gets a clean URL —
    /portfolio/portfolio_dashboard_report.html — instead of the
    legacy ?path=<abs-path> form. Lets users bookmark / share the URL
    (e.g. for Tailscale-served access from another device)."""
    # Re-root DATA_DIR + the canonical report path into tmp_path so we don't
    # depend on the developer's actual artifact tree.
    canonical = tmp_path / "artifacts" / "portfolio_monitor" / "portfolio_dashboard_report.html"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("<html><body>fake</body></html>", encoding="utf-8")
    monkeypatch.setattr(portfolio_page, "DATA_DIR", tmp_path)
    monkeypatch.setattr(portfolio_page, "DEFAULT_COMBINED_REPORT_PATH", canonical)

    url = portfolio_page._served_artifact_url(canonical)

    assert url == portfolio_page._DASHBOARD_REPORT_ROUTE
    assert url == "/portfolio/portfolio_dashboard_report.html"
    assert "?path=" not in url


def test_served_artifact_url_falls_back_to_legacy_query_for_other_files(
    monkeypatch, tmp_path
) -> None:
    """Non-canonical artifacts (CSV, JSON, etc.) still flow through the
    generic ?path= route so existing iframe links continue to work."""
    other = tmp_path / "artifacts" / "portfolio_monitor" / "live_ibkr_position_report.csv"
    other.parent.mkdir(parents=True)
    other.write_text("as_of,account\n", encoding="utf-8")
    # Make sure DATA_DIR contains `other` so the sandbox check passes.
    monkeypatch.setattr(portfolio_page, "DATA_DIR", tmp_path)
    # Re-point DEFAULT_COMBINED_REPORT_PATH somewhere else so `other` is NOT
    # the canonical report.
    canonical = tmp_path / "artifacts" / "portfolio_monitor" / "portfolio_dashboard_report.html"
    monkeypatch.setattr(portfolio_page, "DEFAULT_COMBINED_REPORT_PATH", canonical)

    url = portfolio_page._served_artifact_url(other)

    assert url is not None
    assert url.startswith(portfolio_page._GENERATED_HTML_ROUTE + "?path=")
    assert "live_ibkr_position_report.csv" in url


def test_served_artifact_url_returns_none_for_missing_or_outside_paths(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(portfolio_page, "DATA_DIR", tmp_path)
    # Missing file under DATA_DIR.
    assert portfolio_page._served_artifact_url(tmp_path / "absent.html") is None
    # Path outside DATA_DIR (resolves to a different drive root in tests).
    outside = tmp_path.parent / "outside.html"
    outside.write_text("hi", encoding="utf-8")
    try:
        assert portfolio_page._served_artifact_url(outside) is None
    finally:
        outside.unlink(missing_ok=True)
    # None input -> None.
    assert portfolio_page._served_artifact_url(None) is None


def test_module_logger_is_defined() -> None:
    """Regression: the live/refresh TWS-unreachable fallback calls
    ``_logger.warning(...)`` to log that it is using a cached snapshot. The
    module never defined ``_logger`` (only an inline ``logging.getLogger`` at
    one other site), so that graceful-degradation path raised ``NameError`` and
    surfaced as "Action failed" instead of "using cached". Pin the logger so the
    fallback can log without crashing."""
    import logging

    assert isinstance(portfolio_page._logger, logging.Logger)
