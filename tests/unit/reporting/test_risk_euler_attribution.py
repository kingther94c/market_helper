"""Euler (covariance-consistent) risk attribution semantics.

Pins the upgrade from standalone |weight x vol| contribution columns to signed
Euler component contributions: additivity to portfolio vol, negative sign for
hedges, the standalone vol mass kept for the breakdown Vol column, and the
concentration / VaR summary stats derived alongside.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from market_helper.portfolio import SecurityReference, export_security_reference_csv
from market_helper.reporting.risk_html import (
    RiskInputRow,
    _build_breakdown,
    _corr_heat_color,
    build_risk_report_view_model,
)

_CSV_HEADER = (
    "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,"
    "quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight"
)


def _security(internal_id: str, *, symbol: str, asset_class: str, exchange: str = "ARCA") -> SecurityReference:
    return SecurityReference(
        internal_id=internal_id,
        asset_class=asset_class,
        canonical_symbol=symbol,
        display_ticker=symbol,
        display_name=symbol,
        currency="USD",
        primary_exchange=exchange,
        multiplier=1.0,
        ibkr_sec_type="STK",
        ibkr_symbol=symbol,
        ibkr_exchange="SMART",
        yahoo_symbol=symbol,
        dir_exposure="L",
        lookup_status="verified",
    )


def _two_class_view_model(tmp_path: Path):
    """SPY (EQ long) + IEF (FI long) + SH (EQ short) on deterministic returns."""
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                _CSV_HEADER,
                "2026-06-10T00:00:00+00:00,U1,STK:SPY:SMART,1,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,",
                "2026-06-10T00:00:00+00:00,U1,STK:IEF:SMART,2,IEF,IEF,ARCA,USD,ibkr,30,95,100,3000,2850,150,",
                "2026-06-10T00:00:00+00:00,U1,STK:SH:SMART,3,SH,SH,ARCA,USD,ibkr,-50,40,40,-2000,-2000,0,",
            ]
        ),
        encoding="utf-8",
    )
    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps(
            {
                "STK:SPY:SMART": [0.002 * ((idx % 7) - 3) for idx in range(120)],
                "STK:IEF:SMART": [0.001 * ((idx % 5) - 2) for idx in range(120)],
                "STK:SH:SMART": [-0.002 * ((idx % 7) - 3) for idx in range(120)],
            }
        ),
        encoding="utf-8",
    )
    security_reference_path = tmp_path / "security_reference.csv"
    export_security_reference_csv(
        [
            _security("STK:SPY:SMART", symbol="SPY", asset_class="EQ"),
            _security("STK:IEF:SMART", symbol="IEF", asset_class="FI"),
            _security("STK:SH:SMART", symbol="SH", asset_class="EQ"),
        ],
        security_reference_path,
    )
    return build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        security_reference_path=security_reference_path,
    )


def test_euler_contributions_sum_to_portfolio_vol_per_method(tmp_path: Path) -> None:
    view_model = _two_class_view_model(tmp_path)
    summary = view_model.summary
    by_method = {
        "geomean": ("risk_contribution_geomean_1m_3m", summary.portfolio_vol_geomean_1m_3m),
        "5y": ("risk_contribution_5y_realized", summary.portfolio_vol_5y_realized),
        "ewma": ("risk_contribution_ewma", summary.portfolio_vol_ewma),
        "forward": ("risk_contribution_forward_looking", summary.portfolio_vol_forward_looking),
    }
    for field, portfolio_vol in by_method.values():
        total = sum(getattr(row, field) for row in view_model.risk_rows)
        assert total == pytest.approx(portfolio_vol, abs=1e-12), field


def test_short_hedge_contribution_is_negative(tmp_path: Path) -> None:
    view_model = _two_class_view_model(tmp_path)
    spy = next(row for row in view_model.risk_rows if row.symbol == "SPY")
    sh = next(row for row in view_model.risk_rows if row.symbol == "SH")
    # SPY dominates the EQ class loading, so the short SH leg must show a
    # negative component contribution (it reduces portfolio vol).
    assert spy.risk_contribution_geomean_1m_3m > 0
    assert sh.risk_contribution_geomean_1m_3m < 0
    # The allocation summary nets the class internally.
    equity = next(row for row in view_model.allocation_summary if row.asset_class == "EQ")
    assert equity.risk_contribution_geomean_1m_3m == pytest.approx(
        spy.risk_contribution_geomean_1m_3m + sh.risk_contribution_geomean_1m_3m
    )


def test_summary_concentration_and_var_stats(tmp_path: Path) -> None:
    view_model = _two_class_view_model(tmp_path)
    summary = view_model.summary
    # 3 vol-included positions, gross 5100/3000/2000 -> effective N in (1, 3].
    assert summary.effective_positions is not None
    assert 1.0 < summary.effective_positions <= 3.0
    assert summary.top5_gross_share == pytest.approx(1.0)
    assert summary.var_1d_95_usd is not None and summary.var_1d_95_usd > 0


def _input_row(internal_id: str, *, asset_class: str, exposure: float) -> RiskInputRow:
    return RiskInputRow(
        internal_id=internal_id,
        symbol=internal_id,
        canonical_symbol=internal_id,
        account="U1",
        market_value=exposure,
        weight=0.0,
        asset_class=asset_class,
        category=asset_class,
        display_ticker=internal_id,
        display_name=internal_id,
        instrument_type="Stock",
        quantity=1.0,
        latest_price=1.0,
        multiplier=1.0,
        exposure_usd=exposure,
        gross_exposure_usd=abs(exposure),
        signed_exposure_usd=exposure,
        dollar_weight=0.0,
        display_exposure_usd=exposure,
        display_gross_exposure_usd=abs(exposure),
        display_dollar_weight=0.0,
        duration=None,
        expected_vol=None,
        local_symbol=internal_id,
        exchange="ARCA",
        mapping_status="mapped",
        dir_exposure="L",
        eq_sector_proxy="",
        fi_tenor="",
        yahoo_symbol=internal_id,
    )


def test_build_breakdown_keeps_signed_contributions_and_abs_standalones() -> None:
    rows = [
        _input_row("LONG", asset_class="EQ", exposure=600.0),
        _input_row("HEDGE", asset_class="EQ", exposure=-400.0),
    ]
    contributions = {
        "estimated": {"LONG": 0.09, "HEDGE": -0.03},
        "geomean_1m_3m": {"LONG": 0.09, "HEDGE": -0.03},
        "5y_realized": {"LONG": 0.08, "HEDGE": -0.02},
        "forward_looking": {"LONG": 0.07, "HEDGE": -0.01},
    }
    standalones = {
        "estimated": {"LONG": 0.10, "HEDGE": -0.05},
        "geomean_1m_3m": {"LONG": 0.10, "HEDGE": -0.05},
        "5y_realized": {"LONG": 0.09, "HEDGE": -0.04},
        "forward_looking": {"LONG": 0.08, "HEDGE": -0.03},
    }
    breakdown = _build_breakdown(
        rows=rows,
        contributions=contributions,
        standalones=standalones,
        expander=lambda row: [("US", 1.0)],
        parent="EQ",
    )
    assert len(breakdown) == 1
    bucket = breakdown[0]
    # Contributions stay signed and net within the bucket.
    assert bucket.risk_contribution_geomean_1m_3m == pytest.approx(0.06)
    # Standalone mass uses |loading| so the Vol column never nets out.
    assert bucket.standalone_risk_geomean_1m_3m == pytest.approx(0.15)
    assert bucket.standalone_risk_5y_realized == pytest.approx(0.13)


def test_corr_heat_color_diverges_for_negative_correlation() -> None:
    negative = _corr_heat_color(-0.8)
    neutral = _corr_heat_color(0.0)
    positive = _corr_heat_color(0.8)
    assert negative != neutral
    assert positive != neutral
    assert negative != positive
