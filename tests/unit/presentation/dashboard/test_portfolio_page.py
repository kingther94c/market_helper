from __future__ import annotations

from market_helper.application.portfolio_monitor import GenerateCombinedReportInputs, PortfolioReportInputs
from market_helper.presentation.dashboard.pages.portfolio import (
    ExportActionFormState,
    FlexActionFormState,
    LiveActionFormState,
    PortfolioArtifactFormState,
    PortfolioPageState,
    ReferenceActionFormState,
    _build_initial_state,
    _artifact_inputs_from_form,
    _combined_inputs_from_form,
    _etf_inputs_from_form,
    _flex_inputs_from_form,
    _live_inputs_from_form,
    _positions_csv_ready_for_autoload,
)


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

    assert live.port == 7497
    assert live.client_id == 9
    assert live.timeout == 5.5
    assert flex.output_dir == "data/flex"
    assert etf.symbols == ["DBMF", "QQQ"]


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
        export_form=ExportActionFormState(output_path="outputs/combined.html"),
        reference_form=ReferenceActionFormState(),
    )

    combined = _combined_inputs_from_form(state)

    assert isinstance(combined, GenerateCombinedReportInputs)
    assert combined.positions_csv_path == "data/positions.csv"
    assert combined.performance_output_dir == "data/flex"
    assert combined.output_path == "outputs/combined.html"
    assert combined.vol_method == "5y_realized"


def test_build_initial_state_normalizes_internal_vol_method_key_for_select() -> None:
    class QueryService:
        def resolve_inputs(self, inputs: PortfolioReportInputs | None = None) -> PortfolioReportInputs:
            return PortfolioReportInputs(
                positions_csv_path="data/positions.csv",
                performance_output_dir="data/flex",
                vol_method="geomean_1m_3m",
            )

    state = _build_initial_state(QueryService())

    assert state.artifact_form.vol_method == "Fast"


def test_positions_csv_ready_for_autoload_requires_existing_file(tmp_path) -> None:
    existing = tmp_path / "positions.csv"
    existing.write_text("as_of\n", encoding="utf-8")

    assert _positions_csv_ready_for_autoload(str(existing)) is True
    assert _positions_csv_ready_for_autoload(str(tmp_path / "missing.csv")) is False
    assert _positions_csv_ready_for_autoload("") is False
