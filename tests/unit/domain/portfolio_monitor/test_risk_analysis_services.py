from __future__ import annotations

"""Unit tests for `domain.portfolio_monitor.services.risk_analysis`.

This module is a thin domain-service wrapper around the heavier risk-report
builder in `reporting/risk_html.py`. It currently has no direct test coverage
— the only thing that exercises it today is the giant render-level golden
test in `tests/unit/reporting/test_risk_html.py`. These tests pin the
wrapper's public contract so a renderer-side refactor cannot silently change
its behaviour.
"""

from pathlib import Path

import pytest

from market_helper.domain.portfolio_monitor.services.risk_analysis import (
    CategorySummaryRow,
    PortfolioRiskSummary,
    RegimeReportSummary,
    RiskInputRow,
    RiskMetricsRow,
    RiskReportBundle,
    estimated_asset_class_vol,
    load_risk_inputs,
    summarize_asset_class_vol,
)


# ---------------------------------------------------------------------------
# Re-export contract: the wrapper's __all__ must expose the symbols its
# downstream callers depend on. Locking this catches an accidental rename in
# the underlying `risk_html.py` that would otherwise only surface as an
# ImportError deep in the dashboard.
# ---------------------------------------------------------------------------


def test_reexport_contract_resolves_to_concrete_symbols() -> None:
    # All public names must be importable from the wrapper module (verified
    # by the import statement at the top of this file). Dataclass identity
    # checks: each is a dataclass with the expected name.
    assert RiskInputRow.__name__ == "RiskInputRow"
    assert RiskMetricsRow.__name__ == "RiskMetricsRow"
    assert CategorySummaryRow.__name__ == "CategorySummaryRow"
    assert PortfolioRiskSummary.__name__ == "PortfolioRiskSummary"
    assert RegimeReportSummary.__name__ == "RegimeReportSummary"


# ---------------------------------------------------------------------------
# summarize_asset_class_vol: thin delegator — must return identical output to
# estimated_asset_class_vol so a future renderer-side rename is caught.
# ---------------------------------------------------------------------------


def test_summarize_asset_class_vol_matches_underlying_for_eq_with_vix_proxy() -> None:
    proxy = {"VIX": 20.0}
    assert summarize_asset_class_vol("EQ", proxy) == estimated_asset_class_vol("EQ", proxy)
    assert summarize_asset_class_vol("EQ", proxy) == pytest.approx(0.20)


def test_summarize_asset_class_vol_matches_underlying_for_fi_with_move_proxy() -> None:
    proxy = {"MOVE": 110.0}
    assert summarize_asset_class_vol("FI", proxy) == estimated_asset_class_vol("FI", proxy)
    assert summarize_asset_class_vol("FI", proxy) == pytest.approx(1.10)


def test_summarize_asset_class_vol_matches_underlying_for_cm_with_gvz_proxy() -> None:
    proxy = {"GVZ": 25.0}
    assert summarize_asset_class_vol("CM", proxy) == estimated_asset_class_vol("CM", proxy)
    assert summarize_asset_class_vol("CM", proxy) == pytest.approx(0.25)


def test_summarize_asset_class_vol_returns_macro_from_proxy() -> None:
    proxy = {"MACRO": 13.0}
    assert summarize_asset_class_vol("MACRO", proxy) == pytest.approx(0.13)


def test_summarize_asset_class_vol_uses_default_when_proxy_missing() -> None:
    # When the proxy dict has no entry for the asset class, the underlying
    # helper falls back to DEFAULT_PROXY_LEVELS (18.0 for VIX → 0.18 for EQ).
    assert summarize_asset_class_vol("EQ", {}) == pytest.approx(0.18)


def test_summarize_asset_class_vol_cash_is_constant_independent_of_proxy() -> None:
    # CASH does not consult the proxy mapping; it returns DEFAULT_CASH_VOL.
    assert summarize_asset_class_vol("CASH", {"VIX": 99.0, "MOVE": 200.0}) == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# load_risk_inputs: happy path + security-reference enrichment branch. We
# write a minimal 2-row positions CSV and assert the loader produces
# RiskInputRow instances with the expected internal_ids. We do not test the
# full enrichment matrix here — that belongs to test_risk_html.py — only that
# the wrapper threads its arguments through correctly.
# ---------------------------------------------------------------------------


_MIN_POSITIONS_CSV_HEADER = (
    "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,"
    "source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight"
)


def _write_minimal_positions_csv(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                _MIN_POSITIONS_CSV_HEADER,
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.6",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,815824229,ZN,ZNM6,CBOT,USD,ibkr,1,110,111,111000,110000,1000,0.4",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_load_risk_inputs_returns_one_row_per_position(tmp_path: Path) -> None:
    csv_path = _write_minimal_positions_csv(tmp_path / "positions.csv")

    rows = load_risk_inputs(positions_csv_path=csv_path)

    assert len(rows) == 2
    assert all(isinstance(row, RiskInputRow) for row in rows)
    internal_ids = {row.internal_id for row in rows}
    assert internal_ids == {"STK:SPY:SMART", "FUT:ZN:CBOT"}


def test_load_risk_inputs_without_security_reference_uses_inferred_metadata(tmp_path: Path) -> None:
    csv_path = _write_minimal_positions_csv(tmp_path / "positions.csv")

    rows = load_risk_inputs(positions_csv_path=csv_path, security_reference_path=None)

    by_id = {row.internal_id: row for row in rows}
    # Without a reference table the loader still classifies known IBKR symbols.
    assert by_id["STK:SPY:SMART"].symbol == "SPY"
    assert by_id["FUT:ZN:CBOT"].symbol == "ZN"
    assert by_id["STK:SPY:SMART"].quantity == pytest.approx(10.0)
    assert by_id["FUT:ZN:CBOT"].quantity == pytest.approx(1.0)


def test_load_risk_inputs_with_missing_csv_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_risk_inputs(positions_csv_path=tmp_path / "nope.csv")


# ---------------------------------------------------------------------------
# RiskReportBundle: dataclass default-factory sanity. Optional fields must
# default to None / empty so partial-construction callsites (e.g. the
# combined-report assembly) don't fail with missing kwargs.
# ---------------------------------------------------------------------------


def test_risk_report_bundle_optional_fields_default_to_none() -> None:
    bundle = RiskReportBundle(
        rows=[],
        historical_correlation={},
        estimated_correlation={},
        historical_vols={},
        estimated_vols={},
        portfolio_summary=PortfolioRiskSummary(
            portfolio_vol_geomean_1m_3m=0.0,
            portfolio_vol_5y_realized=0.0,
            portfolio_vol_ewma=0.0,
            portfolio_vol_forward_looking=0.0,
            funded_aum_usd=0.0,
            funded_aum_sgd=None,
            gross_exposure=0.0,
            net_exposure=0.0,
            mapped_positions=0,
            total_positions=0,
        ),
        allocation_summary=[],
    )
    assert bundle.regime_summary is None
    assert bundle.risk_rows is None
    assert bundle.proxy is None
    assert bundle.returns is None
