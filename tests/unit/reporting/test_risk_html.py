from __future__ import annotations

import json
from pathlib import Path

from market_helper.reporting.risk_html import (
    annualized_vol,
    build_risk_html_report,
    historical_geomean_vol,
    pairwise_corr,
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
                "2026-03-26T00:00:00+00:00,U1,IBKR:2,2,ZN,ZNM6,CBOT,USD,ibkr,1,110,111,3400,3300,100,0.4",
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

    regime_json = tmp_path / "regime.json"
    regime_json.write_text(
        json.dumps(
            [
                {
                    "as_of": "2026-03-26",
                    "regime": "Goldilocks Expansion",
                    "scores": {
                        "VOL": 0.2,
                        "CREDIT": 0.2,
                        "RATES": -0.1,
                        "GROWTH": 0.6,
                        "TREND": 0.7,
                        "STRESS": 0.2,
                    },
                    "inputs": {},
                    "flags": {},
                }
            ]
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "risk_report.html"
    written = build_risk_html_report(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        output_path=output_path,
        proxy_path=proxy_json,
        regime_path=regime_json,
    )

    assert written == output_path
    rendered = output_path.read_text(encoding="utf-8")
    assert "Portfolio Risk Report" in rendered
    assert "Historical portfolio vol" in rendered
    assert "Allocation Summary" in rendered
    assert "Regime Snapshot" in rendered
    assert "Goldilocks Expansion" in rendered
    assert "SPY" in rendered
    assert "ZN" in rendered


def test_annualized_vol_zero_for_short_series() -> None:
    assert annualized_vol([]) == 0.0
    assert annualized_vol([0.01]) == 0.0
