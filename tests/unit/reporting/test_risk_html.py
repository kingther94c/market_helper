from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.error import HTTPError

import pandas as pd
import pytest

from market_helper.data_sources.yahoo_finance import YahooFinanceClient
import market_helper.domain.portfolio_monitor.services.yahoo_returns as yahoo_returns_module
from market_helper.portfolio import SecurityReference, export_security_reference_csv
import market_helper.reporting.risk_html as risk_html_module
from market_helper.reporting.risk_html import (
    RiskInputRow,
    _funded_aum_from_dicts,
    annualized_vol,
    build_risk_report_view_model,
    historical_geomean_vol,
    pairwise_corr,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def _single_price_chart(level: float) -> dict[str, object]:
    return {
        "chart": {
            "result": [
                {
                    "meta": {"currency": "USD"},
                    "timestamp": [1],
                    "indicators": {
                        "quote": [{"close": [level]}],
                        "adjclose": [{"adjclose": [level]}],
                    },
                }
            ]
        }
    }


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


def test_funded_aum_dual_converts_sgd_cash_into_usd_and_sgd_views() -> None:
    funded_aum_usd, funded_aum_sgd = risk_html_module._funded_aum_dual_from_dicts(
        [
            {"instrument_type": "ETF", "gross_exposure_usd": 5100.0, "currency": "USD"},
            {"instrument_type": "Cash", "gross_exposure_usd": 900.0, "currency": "SGD"},
        ],
        usdsgd_rate=1.35,
    )

    assert funded_aum_usd == pytest.approx(5100.0 + (900.0 / 1.35))
    assert funded_aum_sgd == pytest.approx((5100.0 * 1.35) + 900.0)


def test_instrument_type_treats_fop_runtime_contract_as_option() -> None:
    security = SecurityReference(
        internal_id="FOP:MCL:NYMEX",
        asset_class="CM",
        symbol="MCL",
        exchange="NYMEX",
        ibkr_sec_type="FOP",
        ibkr_symbol="MCL",
        ibkr_exchange="NYMEX",
        mapping_status_hint="unmapped",
    )

    assert (
        risk_html_module._instrument_type(
            security=security,
            local_symbol="MCON6 C8525",
            exchange="NYMEX",
        )
        == "Option"
    )


def test_load_proxy_defaults_from_yahoo_and_sets_default_semantics() -> None:
    risk_html_module._YAHOO_PROXY_LEVEL_CACHE.clear()

    def fake_download(url: str) -> dict[str, object]:
        if "%5EVIX" in url:
            return _single_price_chart(19.2)
        if "%5EMOVE" in url:
            return _single_price_chart(104.5)
        if "%5EOVX" in url:
            return _single_price_chart(27.1)
        if "%5EGVZ" in url:
            return _single_price_chart(21.4)
        raise AssertionError(f"Unexpected Yahoo URL: {url}")

    proxy = risk_html_module._load_proxy(
        None,
        yahoo_client=YahooFinanceClient(downloader=fake_download),
    )

    assert proxy["VIX"] == pytest.approx(19.2)
    assert proxy["MOVE"] == pytest.approx(104.5)
    assert proxy["OVX"] == pytest.approx(27.1)
    assert proxy["GVZ"] == pytest.approx(21.4)
    assert proxy["DEFAULT"] == pytest.approx(proxy["VIX"])
    assert risk_html_module.estimated_asset_class_vol("FX", proxy) == 0.0
    assert risk_html_module.estimated_asset_class_vol("MACRO", proxy) == pytest.approx(0.192)


def test_load_proxy_config_resolves_default_alias_to_yahoo_vix(tmp_path: Path) -> None:
    risk_html_module._YAHOO_PROXY_LEVEL_CACHE.clear()
    proxy_json = tmp_path / "proxy.json"
    proxy_json.write_text(
        json.dumps({"DEFAULT": "VIX", "FXVOL": 0}),
        encoding="utf-8",
    )

    proxy = risk_html_module._load_proxy(
        proxy_json,
        yahoo_client=YahooFinanceClient(
            downloader=lambda url: (
                _single_price_chart(17.8)
                if "%5EVIX" in url
                else _single_price_chart(109.0)
                if "%5EMOVE" in url
                else _single_price_chart(24.0)
            )
        ),
    )

    assert proxy["DEFAULT"] == pytest.approx(17.8)
    assert proxy["VIX"] == pytest.approx(17.8)
    assert proxy["MOVE"] == pytest.approx(109.0)


def test_load_proxy_uses_unified_risk_report_config_proxy_section(tmp_path: Path) -> None:
    risk_html_module._YAHOO_PROXY_LEVEL_CACHE.clear()
    risk_config = tmp_path / "report_config.yaml"
    risk_config.write_text(
        "\n".join(
            [
                "risk_report:",
                "  proxy:",
                "    DEFAULT: VIX",
                "    defaults:",
                "      VIX: 21.5",
                "      MOVE: 99.0",
                "    yahoo:",
                "      symbols:",
                "        VIX: ^VIXALT",
                "      period: 3mo",
                "      interval: 1wk",
                "  volatility:",
                "    trading_days: 260",
                "    short_window_days: 22",
                "    long_window_days: 66",
                "    long_term_lookback_years: 4",
                "    cash_vol_override: 0.02",
                "    fx_vol_override: 0.07",
                "  fixed_income:",
                "    fi_10y_eq_mod_duration: 10.0",
                "    move_to_yield_vol_factor: 0.0002",
            ]
        ),
        encoding="utf-8",
    )

    loaded = risk_html_module._load_risk_report_config(
        risk_config_path=risk_config,
        allocation_policy_path=None,
    )
    proxy = risk_html_module._load_proxy(
        None,
        yahoo_client=YahooFinanceClient(
            downloader=lambda url: (
                _single_price_chart(18.4)
                if "%5EVIXALT" in url and "range=3mo" in url and "interval=1wk" in url
                else _single_price_chart(101.0)
            )
        ),
        fallback_payload=loaded.proxy,
        default_levels=loaded.proxy_defaults,
        yahoo_symbols=loaded.proxy_yahoo.symbols,
        yahoo_period=loaded.proxy_yahoo.period,
        yahoo_interval=loaded.proxy_yahoo.interval,
    )

    assert loaded.proxy_defaults["VIX"] == pytest.approx(21.5)
    assert loaded.proxy_defaults["MOVE"] == pytest.approx(99.0)
    assert loaded.proxy_yahoo.symbols["VIX"] == "^VIXALT"
    assert loaded.proxy_yahoo.period == "3mo"
    assert loaded.proxy_yahoo.interval == "1wk"
    assert loaded.volatility.trading_days == 260
    assert loaded.volatility.cash_vol_override == pytest.approx(0.02)
    assert loaded.volatility.fx_vol_override == pytest.approx(0.07)
    assert loaded.fixed_income.fi_10y_eq_mod_duration == pytest.approx(10.0)
    assert loaded.fixed_income.move_to_yield_vol_factor == pytest.approx(0.0002)
    assert proxy["VIX"] == pytest.approx(18.4)
    assert proxy["DEFAULT"] == pytest.approx(18.4)


def test_load_proxy_rejects_legacy_fi_duration_key(tmp_path: Path) -> None:
    proxy_json = tmp_path / "proxy.json"
    proxy_json.write_text(
        json.dumps({"MOVE": 110.0, "FI_10Y_EQ_MOD_DURATION": 10.0}),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="proxy\\.FI_10Y_EQ_MOD_DURATION is no longer supported",
    ):
        risk_html_module._load_proxy(
            proxy_json,
            yahoo_client=YahooFinanceClient(downloader=lambda url: _single_price_chart(17.8)),
        )


def test_load_risk_report_config_rejects_legacy_proxy_fi_duration_key(tmp_path: Path) -> None:
    risk_config = tmp_path / "report_config.yaml"
    risk_config.write_text(
        "\n".join(
            [
                "risk_report:",
                "  proxy:",
                "    FI_10Y_EQ_MOD_DURATION: 10.0",
                "  fixed_income:",
                "    fi_10y_eq_mod_duration: 8.0",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="risk_report\\.proxy\\.FI_10Y_EQ_MOD_DURATION is no longer supported",
    ):
        risk_html_module._load_risk_report_config(
            risk_config_path=risk_config,
            allocation_policy_path=None,
        )


def test_default_eq_country_lookthrough_uses_hierarchical_dm_em_buckets() -> None:
    lookthrough_path = REPO_ROOT / "configs" / "portfolio_monitor" / "eq_country_lookthrough.csv"
    with lookthrough_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    by_key: dict[str, set[str]] = {}
    for row in rows:
        by_key.setdefault(str(row["eq_country"]).upper(), set()).add(str(row["country_bucket"]).upper())

    assert by_key["ACWI"] == {"DM", "EM"}
    assert {"DM-US", "DM-JP", "DM-EU", "DM-OTHER DM"} <= by_key["DM"]
    assert {"EM-CN", "EM-TW", "EM-KR", "EM-IN", "EM-BR", "EM-OTHER EM"} <= by_key["EM"]


def test_default_us_sector_lookthrough_covers_all_us_equity_universe_symbols() -> None:
    lookthrough_path = REPO_ROOT / "configs" / "portfolio_monitor" / "us_sector_lookthrough.json"

    configured_symbols = set(
        risk_html_module._load_weight_table(
            lookthrough_path,
            "canonical_symbol",
            "sector",
        )
    )

    assert {
        "SPY",
        "VOO",
        "SPYL",
        "QQQ",
        "TQQQ",
        "SQQQ",
        "SOXX",
        "SOXL",
        "XLK",
    } <= configured_symbols
    assert "TSLA" not in configured_symbols


def test_expand_us_sector_allocations_prefers_lookthrough_over_security_sector() -> None:
    row = RiskInputRow(
        internal_id="STK:SOXX:SMART",
        symbol="SOXX",
        canonical_symbol="SOXX",
        account="U1",
        market_value=1000.0,
        weight=1.0,
        asset_class="EQ",
        category="EQ",
        display_ticker="SOXX",
        display_name="US Semiconductor",
        instrument_type="ETF",
        quantity=1.0,
        latest_price=1000.0,
        multiplier=1.0,
        exposure_usd=1000.0,
        gross_exposure_usd=1000.0,
        signed_exposure_usd=1000.0,
        dollar_weight=1.0,
        display_exposure_usd=1000.0,
        display_gross_exposure_usd=1000.0,
        display_dollar_weight=1.0,
        duration=None,
        expected_vol=None,
        local_symbol="SOXX",
        exchange="SMART",
        mapping_status="mapped",
        dir_exposure="L",
        eq_country="US",
        eq_sector_proxy="",
        fi_tenor="",
        yahoo_symbol="SOXX",
    )

    allocations = risk_html_module._expand_us_sector_allocations(
        row,
        {"SOXX": [("Technology", 1.0)]},
    )

    assert allocations == [("Technology", 1.0)]


def test_report_us_etf_lookthrough_symbols_uses_proxy_and_existing() -> None:
    def _make_row(symbol: str, *, proxy: str, in_existing: bool = False) -> RiskInputRow:
        return RiskInputRow(
            internal_id=f"STK:{symbol}:SMART",
            symbol=symbol,
            canonical_symbol=symbol,
            account="U1",
            market_value=1000.0,
            weight=0.5,
            asset_class="EQ",
            category="EQ",
            display_ticker=symbol,
            display_name=symbol,
            instrument_type="EQ",
            quantity=1.0,
            latest_price=1000.0,
            multiplier=1.0,
            exposure_usd=1000.0,
            gross_exposure_usd=1000.0,
            signed_exposure_usd=1000.0,
            dollar_weight=0.5,
            display_exposure_usd=1000.0,
            display_gross_exposure_usd=1000.0,
            display_dollar_weight=0.5,
            duration=None,
            expected_vol=None,
            local_symbol=symbol,
            exchange="SMART",
            mapping_status="mapped",
            dir_exposure="L",
            eq_country="US",
            eq_sector_proxy=proxy,
            fi_tenor="",
            yahoo_symbol=symbol,
        )

    existing = {"SPY"}
    rows = [
        _make_row("SPY", proxy=""),       # no proxy, but SPY in existing → include SPY
        _make_row("TSLA", proxy="XLK"),   # proxy=XLK → include XLK
        _make_row("AAPL", proxy=""),      # no proxy, AAPL not in existing → skip
        _make_row("VIX", proxy="NONE"),   # explicit NONE → skip
    ]

    symbols = risk_html_module._report_us_etf_lookthrough_symbols(
        rows,
        existing_symbols=existing,
    )

    assert symbols == ["SPY", "XLK"]


def test_build_risk_report_view_model_renders_summary_and_tables(tmp_path: Path) -> None:
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

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        proxy_path=proxy_json,
        regime_path=regime_json,
    )

    assert view_model.summary.portfolio_vol_geomean_1m_3m > 0
    assert view_model.summary.portfolio_vol_5y_realized > 0
    assert view_model.summary.portfolio_vol_ewma > 0
    assert view_model.allocation_summary
    assert view_model.country_breakdown
    assert view_model.policy_drift_asset_class
    assert view_model.policy_drift_country
    assert view_model.policy_drift_sector
    assert view_model.regime_summary is not None
    assert view_model.regime_summary.regime == "Goldilocks Expansion"
    assert any(row.display_ticker == "SPY" for row in view_model.risk_rows)
    assert any(row.display_name == "10Y US" for row in view_model.risk_rows)
    assert any("svg" in row.sparkline_3m_svg for row in view_model.risk_rows)


def test_build_risk_report_view_model_accepts_configurable_allocation_policy(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:ARCA,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,1.0",
            ]
        ),
        encoding="utf-8",
    )
    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps({"STK:SPY:ARCA": [0.001 * ((idx % 7) - 3) for idx in range(90)]}),
        encoding="utf-8",
    )
    policy_yaml = tmp_path / "allocation_policy.yaml"
    policy_yaml.write_text(
        "\n".join(
            [
                "policy:",
                "  portfolio_asset_class_targets:",
                "    EQ: 1.0",
                "  equity_country_policy_mix:",
                "    DM: 1.0",
                "  us_equity_sector_policy_mix:",
                "    SOXX: 1.0",
            ]
        ),
        encoding="utf-8",
    )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        allocation_policy_path=policy_yaml,
    )
    assert any(row.scope == "PORTFOLIO" for row in view_model.policy_drift_asset_class)
    assert any(row.bucket == "Technology" for row in view_model.policy_drift_sector)
    assert any(row.bucket == "DM-JP" for row in view_model.policy_drift_country)


def test_asset_class_policy_drift_preserves_non_normalized_targets() -> None:
    drift_rows = risk_html_module._build_asset_class_policy_drift(
        allocation_summary=[],
        asset_class_targets={
            "EQ": 0.80,
            "FI": 1.0,
            "FX": 1.0,
            "CASH": 0.05,
            "CM": 0.10,
            "MACRO": 0.05,
        },
    )

    by_bucket = {row.bucket: row for row in drift_rows}

    assert by_bucket["EQ"].policy_weight == pytest.approx(0.80)
    assert by_bucket["FI"].policy_weight == pytest.approx(1.0)
    assert by_bucket["FX"].policy_weight == pytest.approx(1.0)
    assert sum(row.policy_weight for row in drift_rows) == pytest.approx(3.0)


def test_build_risk_report_view_model_prefixes_policy_drift_equity_country_dm_em_buckets(
    tmp_path: Path,
) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:ACWI:SMART,756733,ACWI,ACWI,ARCA,USD,ibkr,10,100,100,10000,10000,0,1.0",
            ]
        ),
        encoding="utf-8",
    )
    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps({"STK:ACWI:SMART": [0.001 * ((idx % 7) - 3) for idx in range(90)]}),
        encoding="utf-8",
    )
    security_reference_path = tmp_path / "security_reference.csv"
    export_security_reference_csv(
        [
            SecurityReference(
                internal_id="STK:ACWI:SMART",
                asset_class="EQ",
                canonical_symbol="ACWI",
                display_ticker="ACWI",
                display_name="ACWI",
                currency="USD",
                primary_exchange="ARCA",
                multiplier=1.0,
                ibkr_sec_type="STK",
                ibkr_symbol="ACWI",
                ibkr_exchange="SMART",
                yahoo_symbol="ACWI",
                eq_country="ACWI",
                dir_exposure="L",
                lookup_status="verified",
            ),
        ],
        security_reference_path,
    )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        security_reference_path=security_reference_path,
    )
    buckets = [row.bucket for row in view_model.policy_drift_country]
    assert "DM-US" in buckets
    assert "DM-OTHER DM" in buckets
    assert "EM-CN" in buckets
    assert "EM-OTHER EM" in buckets
    assert buckets.index("DM-US") < buckets.index("DM-OTHER DM") < buckets.index("EM-CN") < buckets.index("EM-OTHER EM")


def test_build_risk_report_view_model_uses_security_reference_for_enrichment(tmp_path: Path) -> None:
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

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        security_reference_path=security_reference_path,
    )
    assert any(row.display_ticker == "LON:SPYL" for row in view_model.risk_rows)
    assert any(row.display_name == "10Y TF" for row in view_model.risk_rows)
    assert any(row.bucket_label == "Long belly" for row in view_model.fi_tenor_breakdown)
    assert any(row.mapping_status == "mapped" for row in view_model.risk_rows)


def test_annualized_vol_zero_for_short_series() -> None:
    assert annualized_vol([]) == 0.0
    assert annualized_vol([0.01]) == 0.0


def test_build_risk_report_view_model_uses_yahoo_cache_when_no_returns_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    risk_html_module._YAHOO_PROXY_LEVEL_CACHE.clear()
    risk_html_module._YAHOO_FX_RATE_CACHE.clear()
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
    client = YahooFinanceClient(downloader=fake_download)

    first = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        security_reference_path=security_reference_path,
        yahoo_client=client,
    )
    second = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        security_reference_path=security_reference_path,
        yahoo_client=client,
    )

    assert calls["count"] == 6
    assert first.summary.funded_aum_usd > 0
    assert first.summary.funded_aum_sgd > 0
    assert any(row.display_ticker == "SPY" for row in first.risk_rows)
    assert second.summary.funded_aum_usd == pytest.approx(first.summary.funded_aum_usd)
    assert (tmp_path / "yahoo_cache" / "SPY.json").exists()


def test_build_risk_report_view_model_accepts_dated_returns_override(tmp_path: Path) -> None:
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

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
    )
    tickers = {row.display_ticker for row in view_model.risk_rows}
    assert {"SPY", "ZN"} <= tickers


def test_build_risk_report_view_model_excludes_eq_options_outside_decomposition(
    tmp_path: Path,
) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.6",
                "2026-03-26T00:00:00+00:00,U1,OPT:SPY_260417C00510000:SMART,999001,SPY,SPY   260417C00510000,SMART,USD,ibkr,1,35,35,3500,3500,0,0.4",
            ]
        ),
        encoding="utf-8",
    )

    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps({"STK:SPY:SMART": [0.001 * ((idx % 7) - 3) for idx in range(90)]}),
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
        ],
        security_reference_path,
    )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        security_reference_path=security_reference_path,
    )
    assert view_model.summary.gross_exposure == pytest.approx(5100.0)
    equity_summary = next(row for row in view_model.allocation_summary if row.asset_class == "EQ")
    assert equity_summary.exposure_usd == pytest.approx(5100.0)
    assert any(row.display_ticker == "SPY 260417C00510000" for row in view_model.risk_rows)
    option_row = next(row for row in view_model.risk_rows if row.internal_id.startswith("OPT:"))
    assert option_row.report_scope == "excluded"


def test_unmapped_rows_do_not_count_toward_vol_contribution(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.5",
                "2026-03-26T00:00:00+00:00,U1,STK:AAPL:SMART,265598,AAPL,AAPL,SMART,USD,ibkr,10,170,175,1750,1700,50,0.5",
            ]
        ),
        encoding="utf-8",
    )
    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps(
            {
                "STK:SPY:SMART": [0.001 * ((idx % 7) - 3) for idx in range(90)],
                "STK:AAPL:SMART": [0.0015 * ((idx % 5) - 2) for idx in range(90)],
            }
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
        ],
        security_reference_path,
    )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        security_reference_path=security_reference_path,
    )

    spy_row = next(row for row in view_model.risk_rows if row.internal_id == "STK:SPY:SMART")
    aapl_row = next(row for row in view_model.risk_rows if row.internal_id == "STK:AAPL:SMART")

    assert spy_row.mapping_status == "mapped"
    assert spy_row.risk_contribution_estimated > 0
    assert aapl_row.mapping_status != "mapped"
    assert aapl_row.report_scope == "included"
    assert aapl_row.risk_contribution_estimated == 0.0

    equity_summary = next(row for row in view_model.allocation_summary if row.asset_class == "EQ")
    assert equity_summary.risk_contribution_estimated == pytest.approx(spy_row.risk_contribution_estimated)


def test_fx_and_cash_do_not_count_toward_portfolio_vol_contribution(tmp_path: Path) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,5100,5000,100,0.4",
                "2026-03-26T00:00:00+00:00,U1,FX:EURUSD:IDEALPRO,,EUR.USD,EUR.USD,IDEALPRO,USD,ibkr,1,1,1,4000,4000,0,0.3",
                "2026-03-26T00:00:00+00:00,U1,CASH:USD_CASH_VALUE:MANUAL,,USD,USD,MANUAL,USD,ibkr,1,1,1,3000,3000,0,0.3",
            ]
        ),
        encoding="utf-8",
    )
    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps(
            {
                "STK:SPY:SMART": [0.001 * ((idx % 7) - 3) for idx in range(90)],
                "FX:EURUSD:IDEALPRO": [0.0005 * ((idx % 5) - 2) for idx in range(90)],
            }
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
                internal_id="FX:EURUSD:IDEALPRO",
                asset_class="FX",
                canonical_symbol="EURUSD",
                display_ticker="EURUSD",
                display_name="EURUSD",
                currency="USD",
                primary_exchange="IDEALPRO",
                multiplier=1.0,
                ibkr_sec_type="CASH",
                ibkr_symbol="EUR",
                ibkr_exchange="IDEALPRO",
                yahoo_symbol="EURUSD=X",
                dir_exposure="L",
                lookup_status="verified",
            ),
            SecurityReference(
                internal_id="CASH:USD_CASH_VALUE:MANUAL",
                asset_class="CASH",
                canonical_symbol="USD_CASH_VALUE",
                display_ticker="USD CASH",
                display_name="Cash",
                currency="USD",
                primary_exchange="MANUAL",
                multiplier=1.0,
                ibkr_sec_type="CASH",
                ibkr_symbol="USD",
                ibkr_exchange="MANUAL",
                dir_exposure="L",
                lookup_status="verified",
            ),
        ],
        security_reference_path,
    )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        security_reference_path=security_reference_path,
    )

    spy_row = next(row for row in view_model.risk_rows if row.asset_class == "EQ")
    fx_row = next(row for row in view_model.risk_rows if row.asset_class == "FX")
    cash_row = next(row for row in view_model.risk_rows if row.asset_class == "CASH")

    assert spy_row.risk_contribution_estimated > 0
    assert fx_row.risk_contribution_estimated == 0.0
    assert cash_row.risk_contribution_estimated == 0.0
    assert view_model.summary.portfolio_vol_geomean_1m_3m == pytest.approx(spy_row.risk_contribution_historical)
    assert view_model.summary.portfolio_vol_5y_realized >= 0
    assert view_model.summary.portfolio_vol_ewma >= 0


def test_fi_10y_equivalent_exposure_values_scale_and_preserve_sign() -> None:
    gross, signed = risk_html_module._fi_10y_equivalent_exposure_values(
        gross_exposure_usd=100.0,
        signed_exposure_usd=-100.0,
        duration=4.0,
        fi_10y_eq_mod_duration=8.0,
    )

    assert gross == pytest.approx(50.0)
    assert signed == pytest.approx(-50.0)


def test_resolve_fi_10y_eq_mod_duration_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="FI_10Y_EQ_MOD_DURATION must be positive"):
        risk_html_module._resolve_fi_10y_eq_mod_duration(0.0)


def test_build_risk_report_view_model_displays_fi_10y_equivalent_exposures_only(
    tmp_path: Path,
) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,10000,5000,100,0.5",
                "2026-03-26T00:00:00+00:00,U1,STK:LQD:SMART,15547816,LQD,LQD,ARCA,USD,ibkr,10,100,100,8000,8000,0,0.1",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZT:CBOT,818615229,ZT,ZTM6,CBOT,USD,ibkr,1,100,100,8000,8000,0,0.1",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZF:CBOT,818615223,ZF,ZFM6,CBOT,USD,ibkr,1,100,100,8000,8000,0,0.1",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,815824229,ZN,ZNM6,CBOT,USD,ibkr,1,100,100,8000,8000,0,0.1",
            ]
        ),
        encoding="utf-8",
    )

    returns_json = tmp_path / "returns.json"
    returns_json.write_text("{}", encoding="utf-8")

    proxy_json = tmp_path / "proxy.json"
    proxy_json.write_text(json.dumps({"VIX": 20.0, "MOVE": 110.0}), encoding="utf-8")

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
                internal_id="STK:LQD:SMART",
                asset_class="FI",
                canonical_symbol="LQD",
                display_ticker="LQD",
                display_name="CR",
                currency="USD",
                primary_exchange="ARCA",
                multiplier=1.0,
                ibkr_sec_type="STK",
                ibkr_symbol="LQD",
                ibkr_exchange="SMART",
                yahoo_symbol="LQD",
                dir_exposure="L",
                mod_duration=8.379,
                fi_tenor="7-10Y",
                lookup_status="verified",
            ),
            SecurityReference(
                internal_id="FUT:ZT:CBOT",
                asset_class="FI",
                canonical_symbol="ZT",
                display_ticker="ZT",
                display_name="2Y TF",
                currency="USD",
                primary_exchange="CBOT",
                multiplier=1000.0,
                ibkr_sec_type="FUT",
                ibkr_symbol="ZT",
                ibkr_exchange="CBOT",
                yahoo_symbol="ZT=F",
                dir_exposure="L",
                mod_duration=1.879,
                fi_tenor="1-3Y",
                lookup_status="verified",
            ),
            SecurityReference(
                internal_id="FUT:ZF:CBOT",
                asset_class="FI",
                canonical_symbol="ZF",
                display_ticker="ZF",
                display_name="5Y TF",
                currency="USD",
                primary_exchange="CBOT",
                multiplier=1000.0,
                ibkr_sec_type="FUT",
                ibkr_symbol="ZF",
                ibkr_exchange="CBOT",
                yahoo_symbol="ZF=F",
                dir_exposure="L",
                mod_duration=4.333,
                fi_tenor="3-5Y",
                lookup_status="verified",
            ),
            SecurityReference(
                internal_id="FUT:ZN:CBOT",
                asset_class="FI",
                canonical_symbol="ZN",
                display_ticker="ZN",
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
                lookup_status="verified",
            ),
        ],
        security_reference_path,
    )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        proxy_path=proxy_json,
        security_reference_path=security_reference_path,
    )
    expected_display = {
        "ZT": 8000.0 * 1.879 / 8.0,
        "ZF": 8000.0 * 4.333 / 8.0,
        "ZN": 8000.0 * 7.627 / 8.0,
        "LQD": 8000.0 * 8.379 / 8.0,
    }
    for ticker, expected_gross in expected_display.items():
        row = next(item for item in view_model.risk_rows if item.display_ticker == ticker)
        assert row.gross_exposure_usd == pytest.approx(expected_gross)

    expected_hybrid_gross = 10000.0 + sum(expected_display.values())
    assert view_model.summary.gross_exposure == pytest.approx(expected_hybrid_gross)
    zn_row = next(item for item in view_model.risk_rows if item.display_ticker == "ZN")
    assert zn_row.gross_exposure_usd == pytest.approx(7627.0)
    assert zn_row.risk_contribution_estimated > 0


def test_build_risk_report_view_model_respects_fi_10y_eq_mod_duration_override(
    tmp_path: Path,
) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,10000,5000,100,0.5",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,815824229,ZN,ZNM6,CBOT,USD,ibkr,1,100,100,8000,8000,0,0.5",
            ]
        ),
        encoding="utf-8",
    )

    returns_json = tmp_path / "returns.json"
    returns_json.write_text("{}", encoding="utf-8")

    proxy_json = tmp_path / "proxy.json"
    proxy_json.write_text(json.dumps({"MOVE": 110.0}), encoding="utf-8")
    risk_config = tmp_path / "report_config.yaml"
    risk_config.write_text(
        "\n".join(
            [
                "risk_report:",
                "  fixed_income:",
                "    fi_10y_eq_mod_duration: 10.0",
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
                internal_id="FUT:ZN:CBOT",
                asset_class="FI",
                canonical_symbol="ZN",
                display_ticker="ZN",
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
                lookup_status="verified",
            ),
        ],
        security_reference_path,
    )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        proxy_path=proxy_json,
        risk_config_path=risk_config,
        security_reference_path=security_reference_path,
    )
    assert view_model.summary.gross_exposure == pytest.approx(16101.6)


def test_build_risk_report_view_model_fi_display_exposure_falls_back_to_raw_without_duration(
    tmp_path: Path,
) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,STK:SPY:SMART,756733,SPY,SPY,ARCA,USD,ibkr,10,500,510,10000,5000,100,0.5",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,815824229,ZN,ZNM6,CBOT,USD,ibkr,1,100,100,8000,8000,0,0.5",
            ]
        ),
        encoding="utf-8",
    )

    returns_json = tmp_path / "returns.json"
    returns_json.write_text(
        json.dumps(
            {
                "STK:SPY:SMART": [0.001 * ((idx % 7) - 3) for idx in range(90)],
                "FUT:ZN:CBOT": [0.0007 * ((idx % 5) - 2) for idx in range(90)],
            }
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
                internal_id="FUT:ZN:CBOT",
                asset_class="FI",
                canonical_symbol="ZN",
                display_ticker="ZN",
                display_name="10Y TF",
                currency="USD",
                primary_exchange="CBOT",
                multiplier=1000.0,
                ibkr_sec_type="FUT",
                ibkr_symbol="ZN",
                ibkr_exchange="CBOT",
                yahoo_symbol="ZN=F",
                dir_exposure="L",
                fi_tenor="7-10Y",
                lookup_status="verified",
            ),
        ],
        security_reference_path,
    )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        returns_path=returns_json,
        security_reference_path=security_reference_path,
    )
    zn_row = next(row for row in view_model.risk_rows if row.display_ticker == "ZN")
    assert zn_row.gross_exposure_usd == pytest.approx(8000.0)


def test_security_vol_uses_duration_scaled_fi_proxy_when_returns_missing() -> None:
    value = risk_html_module._security_vol(
        returns=pd.Series(dtype=float),
        asset_class="FI",
        duration=7.627,
        proxy={"MOVE": 110.0},
        method="ewma",
    )

    assert value == pytest.approx(0.083897, rel=1e-6)


def test_security_vol_uses_configured_fixed_income_and_cash_fallbacks() -> None:
    volatility = risk_html_module.VolatilityMethodologyConfig(
        trading_days=252,
        short_window_days=21,
        long_window_days=63,
        long_term_lookback_years=5,
        cash_vol_override=0.02,
        fx_vol_override=0.03,
    )

    fi_value = risk_html_module._security_vol(
        returns=pd.Series(dtype=float),
        asset_class="FI",
        duration=7.627,
        proxy={"MOVE": 110.0},
        method="ewma",
        volatility=volatility,
        move_to_yield_vol_factor=0.0002,
    )
    cash_value = risk_html_module._security_vol(
        returns=pd.Series(dtype=float),
        asset_class="CASH",
        duration=None,
        proxy={},
        method="ewma",
        volatility=volatility,
    )

    expected_fi = risk_html_module.yield_vol_to_price_vol(
        yield_vol=risk_html_module.proxy_index_to_yield_vol(110.0, mapping_factor=0.0002),
        modified_duration=7.627,
    )
    assert fi_value == pytest.approx(expected_fi)
    assert cash_value == pytest.approx(0.02)


def test_security_vol_uses_fx_override_with_highest_priority() -> None:
    volatility = risk_html_module.VolatilityMethodologyConfig(
        trading_days=252,
        short_window_days=21,
        long_window_days=63,
        long_term_lookback_years=5,
        cash_vol_override=None,
        fx_vol_override=0.04,
    )

    value = risk_html_module._security_vol(
        returns=pd.Series(dtype=float),
        asset_class="FX",
        duration=None,
        proxy={"FXVOL": 9.0, "DEFAULT": 18.0},
        method="ewma",
        volatility=volatility,
    )

    assert value == pytest.approx(0.04)


def test_security_vol_uses_legacy_fx_proxy_logic_when_override_is_none() -> None:
    volatility = risk_html_module.VolatilityMethodologyConfig(
        trading_days=252,
        short_window_days=21,
        long_window_days=63,
        long_term_lookback_years=5,
        cash_vol_override=None,
        fx_vol_override=None,
    )

    value = risk_html_module._security_vol(
        returns=pd.Series(dtype=float),
        asset_class="FX",
        duration=None,
        proxy={"FXVOL": 9.0, "DEFAULT": 18.0},
        method="ewma",
        volatility=volatility,
    )

    assert value == pytest.approx(0.09)


def test_build_risk_report_view_model_falls_back_to_proxy_when_yahoo_rate_limited(
    tmp_path: Path,
    monkeypatch,
) -> None:
    positions_csv = tmp_path / "positions.csv"
    positions_csv.write_text(
        "\n".join(
            [
                "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight",
                "2026-03-26T00:00:00+00:00,U1,FUT:ZN:CBOT,815824229,ZN,ZNM6,CBOT,USD,ibkr,1,110,111,111000,110000,1000,1.0",
            ]
        ),
        encoding="utf-8",
    )

    security_reference_path = tmp_path / "security_reference.csv"
    export_security_reference_csv(
        [
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
            )
        ],
        security_reference_path,
    )

    proxy_json = tmp_path / "proxy.json"
    proxy_json.write_text(json.dumps({"MOVE": 110.0}), encoding="utf-8")
    monkeypatch.setattr(risk_html_module, "DEFAULT_YAHOO_RETURNS_CACHE_DIR", tmp_path / "yahoo_cache")

    def fake_download(_url: str) -> dict[str, object]:
        raise HTTPError(
            url="https://query1.finance.yahoo.com",
            code=429,
            msg="Too Many Requests",
            hdrs={"Retry-After": "0"},
            fp=None,
        )

    view_model = build_risk_report_view_model(
        positions_csv_path=positions_csv,
        proxy_path=proxy_json,
        security_reference_path=security_reference_path,
        yahoo_client=YahooFinanceClient(
            downloader=fake_download,
            max_attempts=1,
            sleep=lambda _seconds: None,
        ),
    )

    row = next(item for item in view_model.risk_rows if item.display_name == "10Y TF")
    assert row.vol_ewma == pytest.approx(0.083897, rel=1e-5)
    assert row.display_name == "10Y TF"


def test_build_risk_report_view_model_raises_for_mapped_row_missing_yahoo_symbol(tmp_path: Path) -> None:
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
        build_risk_report_view_model(
            positions_csv_path=positions_csv,
            security_reference_path=security_reference_path,
            yahoo_client=YahooFinanceClient(downloader=lambda _url: {}),
        )
