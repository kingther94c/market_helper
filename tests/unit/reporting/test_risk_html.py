from __future__ import annotations

import json

import pytest
from pathlib import Path

from market_helper.reporting.risk_html import (
    annualized_vol,
    build_risk_html_report,
    historical_geomean_vol,
    pairwise_corr,
    resolve_duration,
    resolve_dynamic_dv01,
)


def test_historical_geomean_vol_uses_1m_3m_windows() -> None:
    returns = [0.001 * ((idx % 5) - 2) for idx in range(80)]
    value = historical_geomean_vol(returns)
    assert value > 0
    assert value == historical_geomean_vol(returns)


def test_pairwise_corr_bounds_output() -> None:
    left = [0.01, -0.02, 0.015, -0.01, 0.008]
    right = [0.005, -0.01, 0.006, -0.004, 0.003]
    corr = pairwise_corr(left, right)
    assert -1.0 <= corr <= 1.0


def test_build_risk_html_report_renders_summary_and_tables(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,IBKR:1,1,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.6",
                "2026-03-26T00:00:00+00:00,U1,IBKR:2,2,ZN,ZNM6,CBOT,USD,ibkr,2,110,111,3400,3300,100,0.4",
            ]
        ),
        encoding="utf-8",
    )

    returns_payload = {
        "IBKR:1": [0.001 * ((idx % 7) - 3) for idx in range(90)],
        "IBKR:2": [0.0007 * ((idx % 5) - 2) for idx in range(90)],
    }
    returns_json = tmp_path / "returns.json"
    returns_json.write_text(json.dumps(returns_payload), encoding="utf-8")

    proxy_json = tmp_path / "proxy.json"
    proxy_json.write_text(json.dumps({"VIX": 20.0, "MOVE": 120.0}), encoding="utf-8")

    duration_json = tmp_path / "duration.json"
    duration_json.write_text(json.dumps({"IBKR:2": 8.6}), encoding="utf-8")

    futures_dv01_json = tmp_path / "futures_dv01.json"
    futures_dv01_json.write_text(
        json.dumps(
            {
                "tenor_dv01_per_1mm": 85.0,
                "rows": {
                    "IBKR:2": {
                        "conversion_factor": 0.8,
                        "ctd_duration": 7.5,
                        "contract_multiplier": 1000,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "risk_report.html"
    written = build_risk_html_report(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        output_path=output_path,
        proxy_path=proxy_json,
        duration_path=duration_json,
        futures_dv01_path=futures_dv01_json,
    )

    assert written == output_path
    rendered = output_path.read_text(encoding="utf-8")
    assert "Portfolio Risk Report" in rendered
    assert "Historical portfolio vol" in rendered
    assert "Allocation Summary" in rendered
    assert "SPY" in rendered
    assert "ZN" in rendered
    assert "10Y Eqv Exposure" in rendered
    assert "DV01" in rendered
    assert "8.60" in rendered
    assert "Missing CTD/CF rows" in rendered


def test_resolve_duration_uses_override_then_defaults() -> None:
    assert resolve_duration(
        internal_id="IBKR:1", symbol="IEF", asset_class="FI", duration_lookup={"IEF": 7.3}
    ) == 7.3
    assert resolve_duration(
        internal_id="IBKR:2", symbol="ZN", asset_class="FI", duration_lookup={}
    ) == 7.0
    assert resolve_duration(
        internal_id="IBKR:3", symbol="SPY", asset_class="EQ", duration_lookup={}
    ) == 0.0


def test_resolve_dynamic_dv01_uses_ctd_and_conversion_factor() -> None:
    dv01 = resolve_dynamic_dv01(
        internal_id="IBKR:2",
        symbol="ZN",
        asset_class="FI",
        quantity=2,
        latest_price=111,
        futures_dv01_lookup={
            "IBKR:2": {
                "conversion_factor": 0.8,
                "ctd_duration": 7.5,
                "contract_multiplier": 1000,
            }
        },
    )
    assert dv01 > 0


def test_annualized_vol_zero_for_short_series() -> None:
    assert annualized_vol([]) == 0.0
    assert annualized_vol([0.01]) == 0.0


def test_build_risk_html_report_strict_dv01_requires_ctd_map(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,IBKR:2,2,ZN,ZNM6,CBOT,USD,ibkr,2,110,111,3400,3300,100,1.0",
            ]
        ),
        encoding="utf-8",
    )
    returns_json = tmp_path / "returns.json"
    returns_json.write_text(json.dumps({"IBKR:2": [0.001, -0.001, 0.002]}), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing CTD/conversion-factor"):
        build_risk_html_report(
            positions_csv_path=positions_csv,
            returns_path=returns_json,
            output_path=tmp_path / "risk_report.html",
            strict_futures_dv01=True,
        )
