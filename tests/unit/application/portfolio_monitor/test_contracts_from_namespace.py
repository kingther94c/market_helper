from __future__ import annotations

"""Tests for the `from_namespace` classmethods on the portfolio-report input
contracts. These are exercised end-to-end by `tests/unit/cli/test_main.py`,
but a dedicated test file pins their contract independently of the CLI so
future contract changes are caught at the dataclass layer.
"""

import argparse
from pathlib import Path

from market_helper.application.portfolio_monitor.contracts import (
    GenerateCombinedReportInputs,
    PortfolioReportInputs,
)


def _full_namespace(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        positions_csv=str(tmp_path / "positions.csv"),
        performance_history=str(tmp_path / "nav_cashflow_history.feather"),
        performance_output_dir=str(tmp_path / "flex"),
        performance_report_csv=str(tmp_path / "performance_report.csv"),
        returns=str(tmp_path / "returns.json"),
        proxy=str(tmp_path / "proxy.json"),
        regime=str(tmp_path / "regime.json"),
        security_reference=str(tmp_path / "security_reference.csv"),
        risk_config=str(tmp_path / "report_config.yaml"),
        allocation_policy=str(tmp_path / "allocation_policy.yaml"),
        vol_method="ewma",
        inter_asset_corr="corr_0",
        output=str(tmp_path / "combined_report.html"),
    )


def test_portfolio_report_inputs_from_namespace_populates_all_paths(tmp_path: Path) -> None:
    inputs = PortfolioReportInputs.from_namespace(_full_namespace(tmp_path))

    assert inputs.positions_csv_path == tmp_path / "positions.csv"
    assert inputs.performance_history_path == tmp_path / "nav_cashflow_history.feather"
    assert inputs.performance_output_dir == tmp_path / "flex"
    assert inputs.performance_report_csv_path == tmp_path / "performance_report.csv"
    assert inputs.returns_path == tmp_path / "returns.json"
    assert inputs.proxy_path == tmp_path / "proxy.json"
    assert inputs.regime_path == tmp_path / "regime.json"
    assert inputs.security_reference_path == tmp_path / "security_reference.csv"
    assert inputs.risk_config_path == tmp_path / "report_config.yaml"
    assert inputs.allocation_policy_path == tmp_path / "allocation_policy.yaml"
    assert inputs.vol_method == "ewma"
    assert inputs.inter_asset_corr == "corr_0"
    # Regime mode is not in the CLI namespace today — falls back to the
    # dataclass default so cron + dashboard get the "always fresh" behavior.
    assert inputs.regime_mode == "refresh-if-stale"


def test_portfolio_report_inputs_from_namespace_handles_missing_optional_paths(
    tmp_path: Path,
) -> None:
    # Build a namespace that omits every optional flag — risk-html-report
    # allows almost everything to default. None values must propagate through
    # so the workflow facade sees None rather than Path('None').
    args = argparse.Namespace(
        positions_csv=str(tmp_path / "positions.csv"),
        performance_history=None,
        performance_output_dir=None,
        performance_report_csv=None,
        returns=None,
        proxy=None,
        regime=None,
        security_reference=None,
        risk_config=None,
        allocation_policy=None,
        vol_method="geomean_1m_3m",
        inter_asset_corr="historical",
    )

    inputs = PortfolioReportInputs.from_namespace(args)

    assert inputs.positions_csv_path == tmp_path / "positions.csv"
    assert inputs.performance_history_path is None
    assert inputs.performance_output_dir is None
    assert inputs.performance_report_csv_path is None
    assert inputs.returns_path is None
    assert inputs.proxy_path is None
    assert inputs.regime_path is None
    assert inputs.security_reference_path is None
    assert inputs.risk_config_path is None
    assert inputs.allocation_policy_path is None


def test_portfolio_report_inputs_from_namespace_uses_dataclass_defaults_when_attr_missing() -> None:
    # Namespace with no vol_method / inter_asset_corr at all — common in
    # tests that pass a minimal Namespace. The classmethod must not blow up;
    # it should fall back to the dataclass defaults.
    args = argparse.Namespace(positions_csv="x.csv")
    inputs = PortfolioReportInputs.from_namespace(args)
    assert inputs.vol_method == "geomean_1m_3m"
    assert inputs.inter_asset_corr == "historical"


def test_generate_combined_report_inputs_adds_output_path(tmp_path: Path) -> None:
    inputs = GenerateCombinedReportInputs.from_namespace(_full_namespace(tmp_path))

    # Inherits all PortfolioReportInputs fields...
    assert inputs.positions_csv_path == tmp_path / "positions.csv"
    assert inputs.vol_method == "ewma"
    # ...plus output_path.
    assert inputs.output_path == tmp_path / "combined_report.html"


def test_generate_combined_report_inputs_output_path_none_when_missing(tmp_path: Path) -> None:
    args = argparse.Namespace(
        positions_csv=str(tmp_path / "positions.csv"),
        output=None,
    )
    inputs = GenerateCombinedReportInputs.from_namespace(args)
    assert inputs.output_path is None
