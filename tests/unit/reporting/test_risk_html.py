from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from market_helper.data_sources.yahoo_finance import YahooFinanceClient
import market_helper.domain.portfolio_monitor.services.yahoo_returns as yahoo_returns_module
from market_helper.portfolio import SecurityReference, export_security_reference_csv
import market_helper.reporting.risk_html as risk_html_module
from market_helper.reporting.risk_html import (
    _funded_aum_from_dicts,
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


def test_funded_aum_counts_only_stk_like_and_cash_rows() -> None:
    funded_aum = _funded_aum_from_dicts(
        [
            {"instrument_type": "ETF", "gross_exposure_usd": 5100.0},
            {"instrument_type": "EQ", "gross_exposure_usd": 2200.0},
            {"instrument_type": "Cash", "gross_exposure_usd": 900.0},
            {"instrument_type": "Futures", "gross_exposure_usd": 111000.0},
            {"instrument_type": "Option", "gross_exposure_usd": 3500.0},
            {"instrument_type": "Outside Scope", "gross_exposure_usd": 1200.0},
        ]
    )

    assert funded_aum == 8200.0


def test_build_risk_html_report_renders_summary_and_tables(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.6",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,815824229,ZN,ZNM6,CBOT,USD,ibkr,1,110,111,111000,110000,1000,0.4",
            ]
        ),
        encoding="utf-8",
    )

    returns_payload = {
        "STK:SPY:SMART": [0.001 * ((idx % 7) - 3) for idx in range(90)],
        "FUT:ZN:CBOT": [0.0007 * ((idx % 5) - 2) for idx in range(90)],
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
    assert "Asset Class Summary" in rendered
    assert "EQ Country Breakdown" in rendered
    assert "Regime Snapshot" in rendered
    assert "Goldilocks Expansion" in rendered
    assert "SPY" in rendered
    assert "10Y TF" in rendered


def test_build_risk_html_report_uses_security_reference_for_enrichment(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPYL:LSEETF,663368035,SPYL,SPYL,LSEETF,USD,ibkr,4000,17,16.25,65000,68000,-3000,0.5",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,999001,ZN,ZNM6,CBOT,USD,ibkr,1,110,111,111000,110000,1000,0.5",
            ]
        ),
        encoding="utf-8",
    )

    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps(
            {
                "STK:SPYL:LSEETF": [0.001 * ((idx % 7) - 3) for idx in range(90)],
                "FUT:ZN:CBOT": [0.0007 * ((idx % 5) - 2) for idx in range(90)],
            }
        ),
        encoding="utf-8",
    )

    security_reference_path = tmp_path / "security_reference.csv"
    export_security_reference_csv(
        [
            SecurityReference(
                internal_id="STK:SPYL:LSEETF",
                asset_class="EQ",
                canonical_symbol="SPYL",
                display_ticker="LON:SPYL",
                display_name="US",
                currency="USD",
                primary_exchange="LSEETF",
                multiplier=1.0,
                ibkr_sec_type="STK",
                ibkr_symbol="SPYL",
                ibkr_exchange="LSEETF",
                yahoo_symbol="SPYL.L",
                eq_country="US",
                dir_exposure="L",
                mod_duration=1.0,
                lookup_status="verified",
            ),
            SecurityReference(
                internal_id="FUT:ZN:CBOT",
                asset_class="FI",
                canonical_symbol="ZN",
                display_ticker="ZNW00:CBOT",
                display_name="10Y TF",
                currency="USD",
                primary_exchange="CBOT",
                multiplier=1000.0,
                ibkr_sec_type="FUT",
                ibkr_symbol="ZN",
                ibkr_exchange="CBOT",
                yahoo_symbol="ZN=F",
                dir_exposure="L",
                mod_duration=7.627,
                fi_tenor="7-10Y",
                lookup_status="cached",
            ),
        ],
        security_reference_path,
    )

    output_path = tmp_path / "risk_report.html"
    build_risk_html_report(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        output_path=output_path,
        security_reference_path=security_reference_path,
    )

    rendered = output_path.read_text(encoding="utf-8")
    assert "LON:SPYL" in rendered
    assert "10Y TF" in rendered
    assert "FI Tenor Breakdown" in rendered
    assert "<th>Label</th>" in rendered
    assert "Long belly" in rendered
    assert "mapped" in rendered


def test_annualized_vol_zero_for_short_series() -> None:
    assert annualized_vol([]) == 0.0
    assert annualized_vol([0.01]) == 0.0


def test_build_risk_html_report_uses_yahoo_cache_when_no_returns_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.8",
                "2026-03-26T00:00:00+00:00,U1,CASH:SGD_CASH_VALUE:MANUAL,,SGD,SGD,IDEALPRO,SGD,ibkr,1,1,1,900,900,0,0.2",
            ]
        ),
        encoding="utf-8",
    )

    security_reference_path = tmp_path / "security_reference.csv"
    export_security_reference_csv(
        [
            SecurityReference(
                internal_id="STK:SPY:SMART",
                asset_class="EQ",
                canonical_symbol="SPY",
                display_ticker="SPY",
                display_name="US",
                currency="USD",
                primary_exchange="ARCA",
                multiplier=1.0,
                ibkr_sec_type="STK",
                ibkr_symbol="SPY",
                ibkr_exchange="SMART",
                yahoo_symbol="SPY",
                eq_country="US",
                dir_exposure="L",
                lookup_status="verified",
            ),
            SecurityReference(
                internal_id="CASH:SGD_CASH_VALUE:MANUAL",
                asset_class="CASH",
                canonical_symbol="SGD_CASH_VALUE",
                display_ticker="SGD CASH",
                display_name="Cash",
                currency="SGD",
                primary_exchange="MANUAL",
                multiplier=1.0,
                ibkr_sec_type="CASH",
                ibkr_symbol="SGD",
                ibkr_exchange="MANUAL",
                dir_exposure="L",
                lookup_status="cached",
            ),
        ],
        security_reference_path,
    )

    calls = {"count": 0}

    def fake_download(_url: str) -> dict[str, object]:
        calls["count"] += 1
        timestamps = [int(ts.timestamp()) for ts in pd.date_range("2024-01-01", periods=90, freq="D")]
        prices = [100.0 + idx for idx in range(90)]
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"currency": "USD"},
                        "timestamp": timestamps,
                        "indicators": {
                            "quote": [{"close": prices}],
                            "adjclose": [{"adjclose": prices}],
                        },
                    }
                ]
            }
        }

    monkeypatch.setattr(risk_html_module, "DEFAULT_YAHOO_RETURNS_CACHE_DIR", tmp_path / "yahoo_cache")
    monkeypatch.setattr(
        yahoo_returns_module,
        "_latest_expected_daily_observation",
        lambda now=None: pd.Timestamp("2024-03-29"),
    )
    output_path = tmp_path / "risk_report.html"
    client = YahooFinanceClient(downloader=fake_download)

    build_risk_html_report(
        positions_csv_path=positions_csv,
        output_path=output_path,
        security_reference_path=security_reference_path,
        yahoo_client=client,
    )
    build_risk_html_report(
        positions_csv_path=positions_csv,
        output_path=output_path,
        security_reference_path=security_reference_path,
        yahoo_client=client,
    )

    rendered = output_path.read_text(encoding="utf-8")
    assert calls["count"] == 1
    assert "Portfolio Risk Report" in rendered
    assert "SPY" in rendered
    assert (tmp_path / "yahoo_cache" / "SPY.json").exists()


def test_build_risk_html_report_accepts_dated_returns_override(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.5",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,815824229,ZN,ZNM6,CBOT,USD,ibkr,1,110,111,111000,110000,1000,0.5",
            ]
        ),
        encoding="utf-8",
    )

    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps(
            {
                "STK:SPY:SMART": {
                    "2024-01-02": 0.01,
                    "2024-01-03": -0.02,
                    "2024-01-04": 0.015,
                },
                "FUT:ZN:CBOT": {
                    "2024-01-03": 0.001,
                    "2024-01-04": -0.002,
                    "2024-01-05": 0.0015,
                },
            }
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "risk_report.html"
    build_risk_html_report(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        output_path=output_path,
    )

    rendered = output_path.read_text(encoding="utf-8")
    assert "Portfolio Risk Report" in rendered
    assert "SPY" in rendered
    assert "ZN" in rendered


def test_build_risk_html_report_raises_for_mapped_row_missing_yahoo_symbol(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,1.0",
            ]
        ),
        encoding="utf-8",
    )

    security_reference_path = tmp_path / "security_reference.csv"
    export_security_reference_csv(
        [
            SecurityReference(
                internal_id="STK:SPY:SMART",
                asset_class="EQ",
                canonical_symbol="SPY",
                display_ticker="SPY",
                display_name="US",
                currency="USD",
                primary_exchange="ARCA",
                multiplier=1.0,
                ibkr_sec_type="STK",
                ibkr_symbol="SPY",
                ibkr_exchange="SMART",
                dir_exposure="L",
                lookup_status="verified",
            )
        ],
        security_reference_path,
    )

    with pytest.raises(ValueError, match="Missing yahoo_symbol"):
        build_risk_html_report(
            positions_csv_path=positions_csv,
            output_path=tmp_path / "risk_report.html",
            security_reference_path=security_reference_path,
            yahoo_client=YahooFinanceClient(downloader=lambda _url: {}),
        )
