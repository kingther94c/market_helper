from __future__ import annotations

"""HTML risk-report builder for the universe-first portfolio monitor flow."""

import csv
import html
import json
import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

from market_helper.common.progress import ProgressReporter, resolve_progress_reporter
from market_helper.data_sources.yahoo_finance import YahooFinanceClient
from market_helper.domain.portfolio_monitor.services.etf_sector_lookthrough import (
    load_tracked_us_sector_symbols,
    load_us_sector_weight_table,
    refresh_us_sector_lookthrough_for_report,
)
from market_helper.domain.portfolio_monitor.services.fixed_income_vol import (
    proxy_index_to_yield_vol,
    yield_vol_to_price_vol,
)
from market_helper.domain.portfolio_monitor.services.volatility import (
    DEFAULT_EWMA_LAMBDA,
    align_series,
    ewma_vol as series_ewma_vol,
    geometric_blend_vol,
    historical_vol,
    last_valid_scalar,
    long_term_vol,
    rolling_vol,
)
from market_helper.domain.portfolio_monitor.services.yahoo_returns import (
    DEFAULT_YAHOO_RETURNS_CACHE_DIR,
    build_internal_id_return_series_from_yahoo,
    ensure_symbol_return_cache,
    load_internal_id_return_series_override,
)
from market_helper.data_sources.yahoo_finance import YahooFinanceTransientError
from market_helper.portfolio.security_reference import (
    DEFAULT_SECURITY_REFERENCE_PATH,
    SecurityReference,
    SecurityReferenceTable,
    build_security_reference_table,
)
from market_helper.regimes.taxonomy import REGIME_INTERPRETATIONS


TRADING_DAYS = 252
HIST_1M_DAYS = 21
HIST_3M_DAYS = 63
OPTION_LOCAL_SYMBOL_RE = re.compile(r"\s\d{6}[CP]\d+")
DEFAULT_MOVE_TO_YIELD_VOL_FACTOR = 0.0001
DEFAULT_FI_10Y_EQ_MOD_DURATION = 8.0
DEFAULT_LONG_TERM_LOOKBACK_YEARS = 5
DEFAULT_CASH_VOL = 0.01
DEFAULT_PROXY_LEVELS = {
    "VIX": 18.0,
    "MOVE": 110.0,
    "OVX": 25.0,
    "GVZ": 25.0,
}
ASSET_CLASS_CORR_PROXY_SYMBOLS: dict[str, str | None] = {
    "EQ": "ACWI",
    "FI": "AGG",
    "CM": "GLD",
    "MACRO": None,
    "CASH": None,
}
DEFAULT_PROXY_YAHOO_SYMBOLS = {
    "VIX": "^VIX",
    "MOVE": "^MOVE",
    "OVX": "^OVX",
    "GVZ": "^GVZ",
}
DEFAULT_PROXY_YAHOO_PERIOD = "1mo"
DEFAULT_PROXY_YAHOO_INTERVAL = "1d"
DEFAULT_PROXY_FXVOL = 0.0
_YAHOO_PROXY_LEVEL_CACHE: dict[str, float] = {}
DEFAULT_USDSGD_YAHOO_SYMBOL = "USDSGD=X"
DEFAULT_SGDUSD_YAHOO_SYMBOL = "SGDUSD=X"
_YAHOO_FX_RATE_CACHE: dict[str, float] = {}
DEFAULT_EQ_COUNTRY_LOOKTHROUGH_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "portfolio_monitor" / "eq_country_lookthrough.csv"
)
DEFAULT_US_SECTOR_LOOKTHROUGH_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "portfolio_monitor" / "us_sector_lookthrough.json"
)
DEFAULT_RISK_REPORT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "portfolio_monitor" / "report_config.yaml"
)
FI_TENOR_BUCKET_ORDER = ("0-1Y", "1-3Y", "3-5Y", "5-7Y", "7-10Y", "10-20Y", "20Y+", "UNASSIGNED")
FI_TENOR_BUCKET_LABELS = {
    "0-1Y": "Cash / ultra-short",
    "1-3Y": "Front end",
    "3-5Y": "Short belly",
    "5-7Y": "Belly",
    "7-10Y": "Long belly",
    "10-20Y": "Long end",
    "20Y+": "Ultra-long",
    "UNASSIGNED": "",
}
FI_10Y_EQ_DISPLAY_NOTE = "FI dollar exposures are shown as 10Y-equivalent USD notional."
EQ_COUNTRY_POLICY_REGION_ORDER = ("DM", "EM")
EQ_COUNTRY_OTHER_BUCKETS = {"OTHER", "OTHERS"}
US_SECTOR_BUCKETS = {
    "COMMUNICATION SERVICES",
    "CONSUMER DISCRETIONARY",
    "CONSUMER STAPLES",
    "ENERGY",
    "FINANCIALS",
    "HEALTH CARE",
    "INDUSTRIALS",
    "MATERIALS",
    "REAL ESTATE",
    "TECHNOLOGY",
    "UTILITIES",
}
COMPANY_NAME_HINTS = (
    " INC",
    " INC.",
    " CORP",
    " CORPORATION",
    " CO",
    " CO.",
    " HOLDINGS",
    " GROUP",
    " LTD",
    " LTD.",
    " PLC",
    " N.V",
    " NV",
    " AG",
    " SE",
    " SA",
    " LLC",
    " LP",
)


@dataclass(frozen=True)
class RiskInputRow:
    internal_id: str
    symbol: str
    canonical_symbol: str
    account: str
    market_value: float
    weight: float
    asset_class: str
    category: str
    display_ticker: str
    display_name: str
    instrument_type: str
    quantity: float
    latest_price: float
    multiplier: float
    exposure_usd: float
    gross_exposure_usd: float
    signed_exposure_usd: float
    dollar_weight: float
    display_exposure_usd: float
    display_gross_exposure_usd: float
    display_dollar_weight: float
    duration: float | None
    expected_vol: float | None
    local_symbol: str
    exchange: str
    mapping_status: str
    dir_exposure: str
    eq_country: str
    eq_sector_proxy: str
    fi_tenor: str
    yahoo_symbol: str
    currency: str = "USD"
    cm_sector: str = ""


@dataclass(frozen=True)
class RiskMetricsRow:
    internal_id: str
    display_ticker: str
    display_name: str
    symbol: str
    canonical_symbol: str
    account: str
    asset_class: str
    category: str
    instrument_type: str
    quantity: float
    multiplier: float
    market_value: float
    exposure_usd: float
    gross_exposure_usd: float
    weight: float
    dollar_weight: float
    duration: float | None
    vol_geomean_1m_3m: float
    vol_5y_realized: float
    vol_ewma: float
    sparkline_3m_svg: str
    risk_contribution_historical: float
    risk_contribution_estimated: float
    mapping_status: str
    report_scope: str
    dir_exposure: str
    eq_country: str
    eq_sector_proxy: str
    fi_tenor: str
    cm_sector: str = ""


@dataclass(frozen=True)
class CategorySummaryRow:
    category: str
    asset_class: str
    exposure_usd: float
    gross_exposure_usd: float
    dollar_weight: float
    risk_contribution_estimated: float


@dataclass(frozen=True)
class BreakdownRow:
    bucket: str
    bucket_label: str
    parent: str
    exposure_usd: float
    gross_exposure_usd: float
    dollar_weight: float
    risk_contribution_estimated: float


@dataclass(frozen=True)
class PortfolioRiskSummary:
    portfolio_vol_geomean_1m_3m: float
    portfolio_vol_5y_realized: float
    portfolio_vol_ewma: float
    portfolio_vol_forward_looking: float
    funded_aum_usd: float
    funded_aum_sgd: float | None
    gross_exposure: float
    net_exposure: float
    mapped_positions: int
    total_positions: int


@dataclass(frozen=True)
class RiskReportViewModel:
    as_of: str
    risk_rows: list[RiskMetricsRow]
    summary: PortfolioRiskSummary
    allocation_summary: list[CategorySummaryRow]
    country_breakdown: list[BreakdownRow]
    sector_breakdown: list[BreakdownRow]
    fi_tenor_breakdown: list[BreakdownRow]
    policy_drift_asset_class: list[PolicyDriftRow]
    policy_drift_country: list[PolicyDriftRow]
    policy_drift_sector: list[PolicyDriftRow]
    regime_summary: RegimeReportSummary | None
    vol_method: str
    inter_asset_corr: str


@dataclass(frozen=True)
class RegimeReportSummary:
    as_of: str
    regime: str
    scores: dict[str, float]


@dataclass(frozen=True)
class AllocationPolicyConfig:
    portfolio_asset_class_targets: dict[str, float]
    equity_country_policy_mix: dict[str, float]
    us_equity_sector_policy_mix: dict[str, float]


@dataclass(frozen=True)
class ProxyYahooConfig:
    symbols: dict[str, str]
    period: str
    interval: str


@dataclass(frozen=True)
class VolatilityMethodologyConfig:
    trading_days: int
    short_window_days: int
    long_window_days: int
    long_term_lookback_years: int
    cash_vol: float


@dataclass(frozen=True)
class FixedIncomeMethodologyConfig:
    fi_10y_eq_mod_duration: float
    move_to_yield_vol_factor: float


@dataclass(frozen=True)
class PolicyDriftRow:
    bucket: str
    scope: str
    current_weight: float
    policy_weight: float
    active_weight: float
    current_risk_contribution: float


SUPPORTED_VOL_METHOD_KEYS: tuple[str, ...] = (
    "geomean_1m_3m",
    "5y_realized",
    "ewma",
    "forward_looking",
)
DEFAULT_VOL_METHOD_LABELS: dict[str, str] = {
    "Long-Term": "5y_realized",
    "Fast": "geomean_1m_3m",
    "Forward-Looking": "forward_looking",
}
DEFAULT_FX_EXCLUDED_ASSET_CLASSES: tuple[str, ...] = ("FX",)


@dataclass(frozen=True)
class RiskReportConfig:
    eq_country_lookthrough_path: Path
    us_sector_lookthrough_path: Path
    policy: AllocationPolicyConfig
    proxy: dict[str, Any]
    proxy_defaults: dict[str, float]
    proxy_yahoo: ProxyYahooConfig
    volatility: VolatilityMethodologyConfig
    fixed_income: FixedIncomeMethodologyConfig
    vol_method_labels: dict[str, str]
    fx_excluded_asset_classes: tuple[str, ...]


def resolve_vol_method_key(
    value: str, labels: Mapping[str, str] | None = None
) -> str:
    """Accept either a dashboard label ('Long-Term') or internal key ('5y_realized') and return the internal key."""
    mapping = dict(labels) if labels else DEFAULT_VOL_METHOD_LABELS
    normalized = str(value).strip()
    if normalized in mapping:
        return mapping[normalized]
    lowered = normalized.lower()
    if lowered in {k.lower() for k in SUPPORTED_VOL_METHOD_KEYS}:
        for key in SUPPORTED_VOL_METHOD_KEYS:
            if key.lower() == lowered:
                return key
    raise ValueError(
        f"Unknown vol method '{value}'. Known labels: {sorted(mapping.keys())}; "
        f"known keys: {list(SUPPORTED_VOL_METHOD_KEYS)}"
    )


def build_risk_report_view_model(
    *,
    positions_csv_path: str | Path,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
    risk_config_path: str | Path | None = None,
    allocation_policy_path: str | Path | None = None,
    yahoo_client: YahooFinanceClient | None = None,
    vol_method: str = "geomean_1m_3m",
    inter_asset_corr: str = "historical",
    progress: ProgressReporter | None = None,
) -> RiskReportViewModel:
    reporter = resolve_progress_reporter(progress)
    total_steps = 8
    current_step = 0
    resolved_yahoo_client = yahoo_client or YahooFinanceClient()
    reporter.stage("Risk HTML", current=current_step, total=total_steps)
    reference_table = _load_security_reference_table(security_reference_path)
    risk_report_config = _load_risk_report_config(
        risk_config_path=risk_config_path,
        allocation_policy_path=allocation_policy_path,
    )
    # Accept either configured label ("Long-Term") or internal key ("5y_realized").
    vol_method = resolve_vol_method_key(vol_method, risk_report_config.vol_method_labels)
    current_step += 1
    reporter.stage("Risk HTML: config loaded", current=current_step, total=total_steps)
    proxy = _load_proxy(
        proxy_path,
        yahoo_client=resolved_yahoo_client,
        fallback_payload=risk_report_config.proxy,
        default_levels=risk_report_config.proxy_defaults,
        yahoo_symbols=risk_report_config.proxy_yahoo.symbols,
        yahoo_period=risk_report_config.proxy_yahoo.period,
        yahoo_interval=risk_report_config.proxy_yahoo.interval,
        progress=reporter.child("Proxy"),
    )
    fi_10y_eq_mod_duration = _resolve_fi_10y_eq_mod_duration(
        risk_report_config.fixed_income.fi_10y_eq_mod_duration
    )
    current_step += 1
    reporter.stage("Risk HTML: proxy ready", current=current_step, total=total_steps)
    rows = load_position_rows(
        positions_csv_path,
        security_reference_table=reference_table,
        fi_10y_eq_mod_duration=fi_10y_eq_mod_duration,
    )
    current_step += 1
    reporter.stage("Risk HTML: positions loaded", current=current_step, total=total_steps)
    funded_aum_usd, funded_aum_sgd = _funded_aum_dual(
        rows,
        usdsgd_rate=_resolve_usdsgd_rate(
            yahoo_client=resolved_yahoo_client,
            progress=reporter.child("FX"),
        ),
    )
    _refresh_us_sector_lookthrough_for_report(
        rows=rows,
        lookthrough_path=risk_report_config.us_sector_lookthrough_path,
        progress=reporter.child("Sector lookthrough"),
    )
    current_step += 1
    reporter.stage("Risk HTML: lookthrough refreshed", current=current_step, total=total_steps)
    included_rows = [row for row in rows if _is_report_included(row)]
    vol_included_rows = [row for row in included_rows if _is_vol_included(row)]
    returns = _load_or_build_returns(
        returns_path=returns_path,
        rows=vol_included_rows,
        yahoo_client=resolved_yahoo_client,
        progress=reporter.child("Returns"),
    )
    current_step += 1
    reporter.stage("Risk HTML: returns ready", current=current_step, total=total_steps)
    regime_summary = _load_regime_summary(regime_path)
    allocation_policy = risk_report_config.policy

    vols_geomean_1m_3m = {
        row.internal_id: _security_vol(
            returns=returns.get(row.internal_id, []),
            asset_class=row.asset_class,
            duration=row.duration,
            proxy=proxy,
            method="geomean_1m_3m",
            volatility=risk_report_config.volatility,
            proxy_defaults=risk_report_config.proxy_defaults,
            move_to_yield_vol_factor=risk_report_config.fixed_income.move_to_yield_vol_factor,
            internal_id=row.internal_id,
            display_ticker=row.display_ticker,
        )
        if _is_vol_included(row)
        else 0.0
        for row in rows
    }
    vols_5y_realized = {
        row.internal_id: _security_vol(
            returns=returns.get(row.internal_id, []),
            asset_class=row.asset_class,
            duration=row.duration,
            proxy=proxy,
            method="5y_realized",
            volatility=risk_report_config.volatility,
            proxy_defaults=risk_report_config.proxy_defaults,
            move_to_yield_vol_factor=risk_report_config.fixed_income.move_to_yield_vol_factor,
            internal_id=row.internal_id,
            display_ticker=row.display_ticker,
        )
        if _is_vol_included(row)
        else 0.0
        for row in rows
    }
    vols_ewma = {
        row.internal_id: _security_vol(
            returns=returns.get(row.internal_id, []),
            asset_class=row.asset_class,
            duration=row.duration,
            proxy=proxy,
            method="ewma",
            volatility=risk_report_config.volatility,
            proxy_defaults=risk_report_config.proxy_defaults,
            move_to_yield_vol_factor=risk_report_config.fixed_income.move_to_yield_vol_factor,
            internal_id=row.internal_id,
            display_ticker=row.display_ticker,
        )
        if _is_vol_included(row)
        else 0.0
        for row in rows
    }

    geomean_group_loadings = _build_group_loadings(vol_included_rows, vols_geomean_1m_3m)
    realized_5y_group_loadings = _build_group_loadings(vol_included_rows, vols_5y_realized)
    ewma_group_loadings = _build_group_loadings(vol_included_rows, vols_ewma)
    group_returns = _build_group_returns(vol_included_rows, returns)
    asset_class_keys = set(geomean_group_loadings) | set(realized_5y_group_loadings) | set(ewma_group_loadings)
    proxy_group_returns = _load_asset_class_proxy_returns(
        asset_classes=asset_class_keys,
        yahoo_client=resolved_yahoo_client,
    )
    proxy_realized_5y_vol = _compute_proxy_realized_5y_vols(
        proxy_group_returns=proxy_group_returns,
        methodology=risk_report_config.volatility,
    )
    vols_forward_looking = {
        row.internal_id: _adjusted_proxy_security_vol(
            returns=returns.get(row.internal_id, []),
            asset_class=row.asset_class,
            duration=row.duration,
            proxy=proxy,
            volatility=risk_report_config.volatility,
            proxy_defaults=risk_report_config.proxy_defaults,
            move_to_yield_vol_factor=risk_report_config.fixed_income.move_to_yield_vol_factor,
            proxy_5y_realized=proxy_realized_5y_vol.get(row.asset_class),
            internal_id=row.internal_id,
            display_ticker=row.display_ticker,
        )
        if _is_vol_included(row)
        else 0.0
        for row in rows
    }
    forward_looking_group_loadings = _build_group_loadings(vol_included_rows, vols_forward_looking)
    asset_class_keys = asset_class_keys | set(forward_looking_group_loadings)
    selected_group_corr = _build_group_correlation(
        asset_classes=asset_class_keys,
        group_returns=group_returns,
        proxy_group_returns=proxy_group_returns,
        mode=inter_asset_corr,
    )
    portfolio_vol_geomean_1m_3m = _portfolio_vol_from_group_loadings(geomean_group_loadings, selected_group_corr)
    portfolio_vol_5y_realized = _portfolio_vol_from_group_loadings(realized_5y_group_loadings, selected_group_corr)
    portfolio_vol_ewma = _portfolio_vol_from_group_loadings(ewma_group_loadings, selected_group_corr)
    portfolio_vol_forward_looking = _portfolio_vol_from_group_loadings(
        forward_looking_group_loadings, selected_group_corr
    )

    security_geomean_loadings = _build_security_loadings(vol_included_rows, vols_geomean_1m_3m)
    security_realized_loadings = _build_security_loadings(vol_included_rows, vols_5y_realized)
    security_ewma_loadings = _build_security_loadings(vol_included_rows, vols_ewma)
    security_forward_looking_loadings = _build_security_loadings(vol_included_rows, vols_forward_looking)
    selected_security_loadings = _select_security_loadings(
        vol_method=vol_method,
        geomean=security_geomean_loadings,
        realized_5y=security_realized_loadings,
        ewma=security_ewma_loadings,
        forward_looking=security_forward_looking_loadings,
    )
    risk_rows = [
        RiskMetricsRow(
            internal_id=row.internal_id,
            display_ticker=row.display_ticker,
            display_name=row.display_name,
            symbol=row.symbol,
            canonical_symbol=row.canonical_symbol,
            account=row.account,
            asset_class=row.asset_class,
            category=row.category,
            instrument_type=row.instrument_type,
            quantity=row.quantity,
            multiplier=row.multiplier,
            market_value=row.market_value,
            exposure_usd=row.display_exposure_usd,
            gross_exposure_usd=row.display_gross_exposure_usd,
            weight=row.weight,
            dollar_weight=row.display_dollar_weight,
            duration=row.duration,
            vol_geomean_1m_3m=vols_geomean_1m_3m[row.internal_id],
            vol_5y_realized=vols_5y_realized[row.internal_id],
            vol_ewma=vols_ewma[row.internal_id],
            sparkline_3m_svg=_sparkline_svg_for_returns(returns.get(row.internal_id, [])),
            risk_contribution_historical=abs(security_geomean_loadings.get(row.internal_id, 0.0)),
            risk_contribution_estimated=abs(selected_security_loadings.get(row.internal_id, 0.0)),
            mapping_status=row.mapping_status,
            report_scope=_report_scope_label(row),
            dir_exposure=row.dir_exposure,
            eq_country=row.eq_country,
            eq_sector_proxy=row.eq_sector_proxy,
            fi_tenor=row.fi_tenor,
            cm_sector=row.cm_sector,
        )
        for row in rows
    ]
    included_risk_rows = [row for row in risk_rows if row.report_scope == "included"]
    allocation_summary = build_allocation_summary(included_risk_rows)
    country_breakdown = _build_eq_country_breakdown(
        included_rows,
        selected_security_loadings,
        lookthrough_path=risk_report_config.eq_country_lookthrough_path,
    )
    sector_breakdown = _build_us_sector_breakdown(
        included_rows,
        selected_security_loadings,
        lookthrough_path=risk_report_config.us_sector_lookthrough_path,
    )
    fi_tenor_breakdown = _build_fi_tenor_breakdown(included_rows, selected_security_loadings)
    policy_drift_asset_class = _build_asset_class_policy_drift(
        allocation_summary=allocation_summary,
        asset_class_targets=allocation_policy.portfolio_asset_class_targets,
    )
    eq_country_lookthrough = _load_weight_table(
        risk_report_config.eq_country_lookthrough_path,
        "eq_country",
        "country_bucket",
    )
    policy_drift_country = _build_eq_country_policy_drift(
        breakdown=country_breakdown,
        policy_mix=allocation_policy.equity_country_policy_mix,
        lookthrough=eq_country_lookthrough,
    )
    policy_drift_sector = _build_breakdown_policy_drift(
        breakdown=sector_breakdown,
        scope="US_EQ",
        policy_weights=_expand_policy_mix(
            mix=allocation_policy.us_equity_sector_policy_mix,
            lookthrough=_load_weight_table(risk_report_config.us_sector_lookthrough_path, "canonical_symbol", "sector"),
        ),
    )
    summary = PortfolioRiskSummary(
        portfolio_vol_geomean_1m_3m=portfolio_vol_geomean_1m_3m,
        portfolio_vol_5y_realized=portfolio_vol_5y_realized,
        portfolio_vol_ewma=portfolio_vol_ewma,
        portfolio_vol_forward_looking=portfolio_vol_forward_looking,
        funded_aum_usd=funded_aum_usd,
        funded_aum_sgd=funded_aum_sgd,
        gross_exposure=sum(row.display_gross_exposure_usd for row in included_rows),
        net_exposure=sum(row.display_exposure_usd for row in included_rows),
        mapped_positions=sum(1 for row in included_rows if row.mapping_status == "mapped"),
        total_positions=len(included_rows),
    )
    current_step += 1
    reporter.stage("Risk HTML: risk metrics computed", current=current_step, total=total_steps)

    current_step += 1
    reporter.stage("Risk HTML: HTML rendered", current=current_step, total=total_steps)
    as_of = "n/a"
    reporter.done("Risk HTML", detail="view model built")
    return RiskReportViewModel(
        as_of=as_of,
        risk_rows=risk_rows,
        summary=summary,
        allocation_summary=allocation_summary,
        country_breakdown=country_breakdown,
        sector_breakdown=sector_breakdown,
        fi_tenor_breakdown=fi_tenor_breakdown,
        policy_drift_asset_class=policy_drift_asset_class,
        policy_drift_country=policy_drift_country,
        policy_drift_sector=policy_drift_sector,
        regime_summary=regime_summary,
        vol_method=vol_method,
        inter_asset_corr=inter_asset_corr,
    )


def load_position_rows(
    path: str | Path,
    *,
    security_reference_table: SecurityReferenceTable | None = None,
    fi_10y_eq_mod_duration: float = DEFAULT_FI_10Y_EQ_MOD_DURATION,
) -> list[RiskInputRow]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        loaded = list(reader)

    total_market_value = sum(abs(float(row.get("market_value") or 0.0)) for row in loaded)
    parsed_rows: list[dict[str, object]] = []
    for row in loaded:
        internal_id = str(row.get("internal_id") or "")
        security = (
            security_reference_table.get_security(internal_id)
            if security_reference_table is not None
            else None
        )
        symbol = str(row.get("symbol") or "").upper()
        local_symbol = str(row.get("local_symbol") or "")
        exchange = str(row.get("exchange") or "").upper()
        market_value = float(row.get("market_value") or 0.0)
        latest_price = float(row.get("latest_price") or 0.0)
        quantity = float(row.get("quantity") or 0.0)
        raw_weight = row.get("weight")
        mapping_status = _mapping_status(security)
        instrument_type = _instrument_type(security=security, local_symbol=local_symbol, exchange=exchange)
        multiplier = _multiplier(
            security=security,
            quantity=quantity,
            latest_price=latest_price,
            market_value=market_value,
            local_symbol=local_symbol,
            mapping_status=mapping_status,
        )

        if security is not None and security.mapping_status == "mapped":
            asset_class = security.asset_class or infer_asset_class(symbol, exchange)
            display_ticker = security.display_ticker or infer_display_ticker(symbol, exchange, local_symbol)
            display_name = security.display_name or infer_display_name(symbol, local_symbol, instrument_type)
            duration = security.mod_duration
            eq_country = security.eq_country
            eq_sector_proxy = security.eq_sector_proxy
            dir_exposure = security.dir_exposure or "L"
            fi_tenor = security.fi_tenor
            cm_sector = security.cm_sector
            yahoo_symbol = security.yahoo_symbol
            canonical_symbol = security.canonical_symbol or symbol
        elif security is not None and security.mapping_status == "outside_scope":
            asset_class = "OUTSIDE_SCOPE"
            display_ticker = security.display_ticker or infer_display_ticker(symbol, exchange, local_symbol)
            display_name = security.display_name or infer_display_name(symbol, local_symbol, instrument_type)
            duration = None
            eq_country = ""
            eq_sector_proxy = ""
            dir_exposure = "L"
            fi_tenor = ""
            cm_sector = ""
            yahoo_symbol = ""
            canonical_symbol = security.canonical_symbol or symbol
        else:
            asset_class = infer_asset_class(symbol, exchange)
            display_ticker = infer_display_ticker(symbol, exchange, local_symbol)
            display_name = infer_display_name(symbol, local_symbol, instrument_type)
            duration = None
            eq_country = ""
            eq_sector_proxy = ""
            dir_exposure = "L"
            fi_tenor = ""
            cm_sector = ""
            yahoo_symbol = ""
            canonical_symbol = symbol

        gross_exposure_usd = abs(market_value) if market_value != 0.0 else abs(quantity * multiplier * latest_price)
        signed_exposure_usd = _signed_exposure_usd(
            quantity=quantity,
            gross_exposure_usd=gross_exposure_usd,
            dir_exposure=dir_exposure,
        )
        weight = (
            float(raw_weight)
            if raw_weight not in (None, "")
            else (gross_exposure_usd / total_market_value if total_market_value > 0 else 0.0)
        )
        parsed_rows.append(
            {
                "internal_id": internal_id,
                "symbol": symbol,
                "canonical_symbol": canonical_symbol,
                "account": str(row.get("account") or ""),
                "market_value": market_value,
                "weight": weight,
                "asset_class": asset_class,
                "category": asset_class,
                "display_ticker": display_ticker,
                "display_name": display_name,
                "instrument_type": instrument_type,
                "quantity": quantity,
                "latest_price": latest_price,
                "multiplier": multiplier,
                "gross_exposure_usd": gross_exposure_usd,
                "signed_exposure_usd": signed_exposure_usd,
                "duration": duration,
                "local_symbol": local_symbol,
                "exchange": exchange,
                "mapping_status": mapping_status,
                "dir_exposure": dir_exposure,
                "eq_country": eq_country,
                "eq_sector_proxy": eq_sector_proxy,
                "fi_tenor": fi_tenor,
                "cm_sector": cm_sector,
                "yahoo_symbol": yahoo_symbol,
                "currency": str(row.get("currency") or ""),
            }
        )

    funded_aum = _funded_aum_from_dicts(parsed_rows)
    materialized_rows: list[RiskInputRow] = []
    for row in parsed_rows:
        duration = _optional_float(row.get("duration"))
        display_gross_exposure_usd, display_exposure_usd = _display_exposure_values(
            asset_class=str(row["asset_class"]),
            gross_exposure_usd=float(row["gross_exposure_usd"]),
            signed_exposure_usd=float(row["signed_exposure_usd"]),
            duration=duration,
            fi_10y_eq_mod_duration=fi_10y_eq_mod_duration,
        )
        materialized_rows.append(
            RiskInputRow(
                internal_id=str(row["internal_id"]),
                symbol=str(row["symbol"]),
                canonical_symbol=str(row["canonical_symbol"]),
                account=str(row["account"]),
                market_value=float(row["market_value"]),
                weight=float(row["weight"]),
                asset_class=str(row["asset_class"]),
                category=str(row["category"]),
                display_ticker=str(row["display_ticker"]),
                display_name=str(row["display_name"]),
                instrument_type=str(row["instrument_type"]),
                quantity=float(row["quantity"]),
                latest_price=float(row["latest_price"]),
                multiplier=float(row["multiplier"]),
                exposure_usd=float(row["signed_exposure_usd"]),
                gross_exposure_usd=float(row["gross_exposure_usd"]),
                signed_exposure_usd=float(row["signed_exposure_usd"]),
                dollar_weight=(
                    float(row["gross_exposure_usd"]) / funded_aum if funded_aum > 0 else float(row["weight"])
                ),
                display_exposure_usd=display_exposure_usd,
                display_gross_exposure_usd=display_gross_exposure_usd,
                display_dollar_weight=(
                    display_gross_exposure_usd / funded_aum if funded_aum > 0 else float(row["weight"])
                ),
                duration=duration,
                expected_vol=None,
                local_symbol=str(row["local_symbol"]),
                exchange=str(row["exchange"]),
                mapping_status=str(row["mapping_status"]),
                dir_exposure=str(row["dir_exposure"]),
                eq_country=str(row["eq_country"]),
                eq_sector_proxy=str(row["eq_sector_proxy"]),
                fi_tenor=str(row["fi_tenor"]),
                cm_sector=str(row.get("cm_sector") or ""),
                yahoo_symbol=str(row["yahoo_symbol"]),
                currency=str(row.get("currency") or "USD"),
            )
        )
    return materialized_rows


def infer_asset_class(symbol: str, exchange: str) -> str:
    upper_symbol = symbol.upper()
    upper_exchange = exchange.upper()
    if upper_exchange in {"CBOT", "CFE", "CME", "COMEX", "ICE", "NYMEX"}:
        if upper_symbol in {"AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "MXN", "NZD"}:
            return "FX"
        if upper_symbol in {"ZN", "ZF", "ZT", "TY", "US"}:
            return "FI"
        if upper_exchange == "CFE":
            return "MACRO"
        return "CM"
    if upper_symbol in {"BOXX", "BIL", "CASH", "SGOV", "SHV", "USD"}:
        return "CASH"
    if upper_symbol in {"DBMF", "VIX", "VXM"}:
        return "MACRO"
    if upper_symbol in {"LQD"}:
        return "FI"
    if upper_symbol in {"GLD", "GDX", "IAU", "SLV", "XAUUSD", "COPX"}:
        return "CM"
    return "EQ"


def infer_category(symbol: str, exchange: str, local_symbol: str) -> str:
    return infer_asset_class(symbol, exchange)


def infer_instrument_type(local_symbol: str, exchange: str) -> str:
    if _looks_like_option(local_symbol):
        return "Option"
    if exchange.upper() in {"CBOT", "CFE", "CME", "COMEX", "ICE", "NYMEX"}:
        return "Futures"
    return "ETF"


def infer_multiplier(
    *,
    quantity: float,
    latest_price: float,
    market_value: float,
    local_symbol: str,
) -> float:
    if quantity != 0.0 and latest_price != 0.0:
        implied = abs(market_value / (quantity * latest_price))
        if implied > 0:
            rounded = round(implied)
            if rounded > 0 and abs(implied - rounded) / rounded < 0.01:
                return float(rounded)
            return implied
    if _looks_like_option(local_symbol):
        return 100.0
    return 1.0


def infer_display_ticker(symbol: str, exchange: str, local_symbol: str) -> str:
    if _looks_like_option(local_symbol):
        return " ".join(local_symbol.split())
    if exchange.upper() in {"CBOT", "CFE", "CME", "COMEX", "ICE", "NYMEX"} and local_symbol:
        return f"{local_symbol}:{exchange.upper()}"
    return symbol


def infer_display_name(symbol: str, local_symbol: str, instrument_type: str) -> str:
    if instrument_type == "Option":
        return " ".join(local_symbol.split())
    if instrument_type == "Futures" and local_symbol:
        return local_symbol
    return symbol


def historical_geomean_vol(
    returns: list[float],
    *,
    trading_days: int = TRADING_DAYS,
    short_window_days: int = HIST_1M_DAYS,
    long_window_days: int = HIST_3M_DAYS,
) -> float:
    series = _coerce_return_series(returns)
    if len(series.dropna()) < 2:
        return 0.0
    return _historical_geomean_vol_from_series(
        series,
        trading_days=trading_days,
        short_window_days=short_window_days,
        long_window_days=long_window_days,
    )


def _historical_geomean_vol_from_series(
    series: pd.Series,
    *,
    trading_days: int,
    short_window_days: int,
    long_window_days: int,
) -> float:
    short_vol = rolling_vol(
        returns=series,
        window=short_window_days,
        annualization_factor=trading_days,
        ddof=1,
        min_periods=short_window_days,
    )
    long_vol = rolling_vol(
        returns=series,
        window=long_window_days,
        annualization_factor=trading_days,
        ddof=1,
        min_periods=long_window_days,
    )
    blended = geometric_blend_vol([short_vol, long_vol])
    latest = last_valid_scalar(blended)
    if latest is not None:
        return latest
    return max(last_valid_scalar(short_vol) or 0.0, last_valid_scalar(long_vol) or 0.0)


def annualized_vol(returns: list[float], *, trading_days: int = TRADING_DAYS) -> float:
    return historical_vol(returns=_coerce_return_series(returns), annualization_factor=trading_days, ddof=1)


def ewma_vol(returns: list[float], *, decay: float = 0.94, trading_days: int = TRADING_DAYS) -> float:
    series = series_ewma_vol(
        returns=_coerce_return_series(returns),
        annualization_factor=trading_days,
        lambda_=decay,
        min_periods=20,
        demean=False,
    )
    return last_valid_scalar(series) or 0.0


def estimated_asset_class_vol(
    asset_class: str,
    proxy: Mapping[str, float],
    *,
    proxy_defaults: Mapping[str, float] | None = None,
    cash_vol: float = DEFAULT_CASH_VOL,
) -> float:
    defaults = _merged_proxy_default_levels(proxy_defaults)
    default_vix = defaults["VIX"]
    default_move = defaults["MOVE"]
    default_gvz = defaults["GVZ"]
    name = asset_class.upper()
    if name == "EQ":
        return proxy.get("VIX", default_vix) / 100.0
    if name == "FI":
        return proxy.get("MOVE", default_move) / 100.0
    if name == "CM":
        return proxy.get("OVX", proxy.get("GVZ", default_gvz)) / 100.0
    if name == "CASH":
        return cash_vol
    if name == "FX":
        return proxy.get("FXVOL", DEFAULT_PROXY_FXVOL) / 100.0
    if name == "MACRO":
        return proxy.get("DEFAULT", proxy.get("VIX", default_vix)) / 100.0
    return proxy.get("DEFAULT", proxy.get("VIX", default_vix)) / 100.0


def build_historical_correlation(
    rows: list[RiskInputRow],
    returns: Mapping[str, pd.Series | list[float]],
) -> dict[tuple[str, str], float]:
    corr: dict[tuple[str, str], float] = {}
    for left in rows:
        for right in rows:
            key = (left.internal_id, right.internal_id)
            if left.internal_id == right.internal_id:
                corr[key] = 1.0
                continue
            corr[key] = pairwise_corr(returns.get(left.internal_id, []), returns.get(right.internal_id, []))
    return corr


def build_estimated_correlation(rows: list[RiskInputRow]) -> dict[tuple[str, str], float]:
    corr: dict[tuple[str, str], float] = {}
    for left in rows:
        for right in rows:
            key = (left.internal_id, right.internal_id)
            if left.internal_id == right.internal_id:
                corr[key] = 1.0
            elif "CASH" in {left.asset_class, right.asset_class}:
                corr[key] = 0.0
            elif left.asset_class == right.asset_class:
                corr[key] = 1.0
            else:
                corr[key] = 0.25
    return corr


def pairwise_corr(left: list[float], right: list[float]) -> float:
    left_series = _coerce_return_series(left)
    right_series = _coerce_return_series(right)
    aligned = align_series(left_series, right_series, join="inner")
    if len(aligned) != 2 or len(aligned[0].dropna()) < 2:
        return 0.0
    corr = aligned[0].corr(aligned[1])
    if corr is None or pd.isna(corr):
        return 0.0
    return float(max(-1.0, min(1.0, corr)))


def portfolio_volatility(
    rows: list[RiskInputRow],
    vols: Mapping[str, float],
    corr: Mapping[tuple[str, str], float],
) -> float:
    variance = 0.0
    for left in rows:
        for right in rows:
            variance += (
                left.weight
                * right.weight
                * vols.get(left.internal_id, 0.0)
                * vols.get(right.internal_id, 0.0)
                * corr.get((left.internal_id, right.internal_id), 0.0)
            )
    return math.sqrt(max(variance, 0.0))


def build_allocation_summary(rows: list[RiskMetricsRow]) -> list[CategorySummaryRow]:
    by_bucket: dict[str, CategorySummaryRow] = {}
    for row in rows:
        existing = by_bucket.get(row.asset_class)
        if existing is None:
            by_bucket[row.asset_class] = CategorySummaryRow(
                category=row.asset_class,
                asset_class=row.asset_class,
                exposure_usd=row.exposure_usd,
                gross_exposure_usd=row.gross_exposure_usd,
                dollar_weight=row.dollar_weight,
                risk_contribution_estimated=row.risk_contribution_estimated,
            )
            continue
        by_bucket[row.asset_class] = CategorySummaryRow(
            category=existing.category,
            asset_class=existing.asset_class,
            exposure_usd=existing.exposure_usd + row.exposure_usd,
            gross_exposure_usd=existing.gross_exposure_usd + row.gross_exposure_usd,
            dollar_weight=existing.dollar_weight + row.dollar_weight,
            risk_contribution_estimated=existing.risk_contribution_estimated + row.risk_contribution_estimated,
        )
    return sorted(
        by_bucket.values(),
        key=lambda item: (-item.gross_exposure_usd, item.asset_class),
    )


def render_html_from_view_model(view_model: RiskReportViewModel) -> str:
    return f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <title>Portfolio Risk Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 24px; color: #0f172a; background: #f8fafc; }}
    .card {{ background: white; border-radius: 12px; box-shadow: 0 1px 3px rgba(15,23,42,0.1); padding: 16px; margin-bottom: 16px; }}
    h1,h2 {{ margin: 0 0 12px 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #e2e8f0; padding: 8px; text-align: left; }}
    th {{ background: #f1f5f9; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .metrics {{ display: flex; gap: 12px; flex-wrap: wrap; }}
    .metric {{ background: #f1f5f9; padding: 10px 12px; border-radius: 8px; min-width: 220px; }}
    .metric span {{ display: block; color: #475569; font-size: 12px; }}
    .metric strong {{ font-size: 20px; }}
    .scores {{ display: flex; gap: 12px; flex-wrap: wrap; color: #334155; }}
    .sparkline {{ width: 120px; height: 28px; }}
    .chart {{ display: grid; gap: 8px; margin-bottom: 12px; }}
    .chart-row {{ display: grid; grid-template-columns: 140px 1fr 72px; gap: 10px; align-items: center; }}
    .chart-track {{ position: relative; height: 14px; border-radius: 999px; background: #e2e8f0; overflow: hidden; }}
    .chart-midline {{ position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: #94a3b8; }}
    .chart-fill-pos {{ position: absolute; left: 50%; top: 0; bottom: 0; background: #16a34a; }}
    .chart-fill-neg {{ position: absolute; top: 0; bottom: 0; background: #dc2626; }}
    .chart-value {{ text-align: right; color: #334155; font-size: 12px; font-variant-numeric: tabular-nums; }}
    .excluded-row {{ background: #fff7ed; }}
  </style>
</head>
<body>
  <h1>Portfolio Risk Report</h1>
  {render_risk_tab(view_model)}
</body>
</html>
"""


def render_risk_tab(view_model: RiskReportViewModel) -> str:
    risk_rows = view_model.risk_rows
    summary = view_model.summary
    allocation_summary = view_model.allocation_summary
    country_breakdown = view_model.country_breakdown
    sector_breakdown = view_model.sector_breakdown
    fi_tenor_breakdown = view_model.fi_tenor_breakdown
    policy_drift_asset_class = view_model.policy_drift_asset_class
    policy_drift_country = view_model.policy_drift_country
    policy_drift_sector = view_model.policy_drift_sector
    regime_summary = view_model.regime_summary
    vol_method = view_model.vol_method
    inter_asset_corr = view_model.inter_asset_corr
    position_rows = "\n".join(
        f"<tr class='{'excluded-row' if row.report_scope == 'excluded' else ''}'>"
        f"<td>{html.escape(row.account)}</td>"
        f"<td>{html.escape(row.display_ticker)}</td>"
        f"<td>{html.escape(row.display_name)}</td>"
        f"<td>{html.escape(row.asset_class)}</td>"
        f"<td>{html.escape(row.instrument_type)}</td>"
        f"<td class='num'>{row.quantity:,.2f}</td>"
        f"<td class='num'>{row.gross_exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.dollar_weight:.2%}</td>"
        f"<td class='num'>{row.vol_geomean_1m_3m:.2%}</td>"
        f"<td class='num'>{row.vol_5y_realized:.2%}</td>"
        f"<td class='num'>{row.vol_ewma:.2%}</td>"
        f"<td>{row.sparkline_3m_svg}</td>"
        f"<td class='num'>{row.risk_contribution_estimated:.2%}</td>"
        f"<td>{html.escape(row.mapping_status)}</td>"
        f"<td>{html.escape(row.report_scope)}</td>"
        "</tr>"
        for row in risk_rows
    )
    allocation_rows = _render_allocation_summary_rows(allocation_summary)
    country_rows = _render_breakdown_rows(country_breakdown)
    sector_rows = _render_breakdown_rows(sector_breakdown)
    tenor_rows = _render_breakdown_rows(fi_tenor_breakdown, include_bucket_label=True)
    policy_asset_rows = _render_policy_drift_rows(policy_drift_asset_class)
    policy_country_rows = _render_policy_drift_rows(policy_drift_country)
    policy_sector_rows = _render_policy_drift_rows(policy_drift_sector)
    policy_asset_chart = _render_policy_drift_chart(policy_drift_asset_class)
    policy_country_chart = _render_policy_drift_chart(policy_drift_country)
    policy_sector_chart = _render_policy_drift_chart(policy_drift_sector)

    regime_block = ""
    if regime_summary is not None:
        banner = REGIME_INTERPRETATIONS.get(regime_summary.regime, "Regime-aware view active.")
        score_list = " ".join(
            f"<span><strong>{html.escape(name)}</strong>: {value:.2f}</span>"
            for name, value in sorted(regime_summary.scores.items())
            if name in {"VOL", "CREDIT", "RATES", "GROWTH", "TREND", "STRESS"}
        )
        regime_block = (
            "<div class='card'>"
            "<h2>Regime Snapshot</h2>"
            f"<p><strong>{html.escape(regime_summary.regime)}</strong> as of {html.escape(regime_summary.as_of)}</p>"
            f"<p>{html.escape(banner)}</p>"
            f"<div class='scores'>{score_list}</div>"
            "</div>"
        )

    return f"""
  {regime_block}

  <div class='card'>
    <h2>Portfolio Summary</h2>
    <div class='metrics'>
      <div class='metric'><span>Portfolio vol (1M/3M geomean, {html.escape(inter_asset_corr)})</span><strong>{summary.portfolio_vol_geomean_1m_3m:.2%}</strong></div>
      <div class='metric'><span>Portfolio vol (5Y realized, {html.escape(inter_asset_corr)})</span><strong>{summary.portfolio_vol_5y_realized:.2%}</strong></div>
      <div class='metric'><span>Portfolio vol (EWMA, {html.escape(inter_asset_corr)})</span><strong>{summary.portfolio_vol_ewma:.2%}</strong></div>
      <div class='metric'><span>Portfolio vol (forward-looking, {html.escape(inter_asset_corr)})</span><strong>{summary.portfolio_vol_forward_looking:.2%}</strong></div>
      <div class='metric'><span>Funded AUM (USD)</span><strong>{summary.funded_aum_usd:,.0f}</strong></div>
      <div class='metric'><span>Funded AUM (SGD)</span><strong>{_format_optional_amount(summary.funded_aum_sgd)}</strong></div>
      <div class='metric'><span>Gross exposure (FI 10Y eq)</span><strong>{summary.gross_exposure:,.0f}</strong></div>
      <div class='metric'><span>Net exposure (FI 10Y eq)</span><strong>{summary.net_exposure:,.0f}</strong></div>
      <div class='metric'><span>Mapping coverage (included rows)</span><strong>{summary.mapped_positions}/{summary.total_positions}</strong></div>
    </div>
    <p>{html.escape(FI_10Y_EQ_DISPLAY_NOTE)}</p>
  </div>

  <div class='card'>
    <h2>Asset Class Summary</h2>
    <table>
      <thead><tr><th>Asset Class</th><th class='num'>Net Exposure (FI 10Y Eq)</th><th class='num'>Gross Exposure (FI 10Y Eq)</th><th class='num'>Dollar%</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{allocation_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>Policy Drift - Asset Class (Dollar Weight Active)</h2>
    <p>Active = current dollar weight minus policy weight. Vol contributions shown below use <strong>{html.escape(vol_method)}</strong>.</p>
    <div class='chart'>{policy_asset_chart}</div>
    <table>
      <thead><tr><th>Bucket</th><th>Scope</th><th class='num'>Current Weight</th><th class='num'>Policy Weight</th><th class='num'>Active (OW/UW)</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{policy_asset_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>EQ Country Breakdown</h2>
    <table>
      <thead><tr><th>Country</th><th>Scope</th><th class='num'>Net Exposure</th><th class='num'>Gross Exposure</th><th class='num'>Dollar%</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{country_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>Policy Drift - Equity Country (within EQ scope)</h2>
    <div class='chart'>{policy_country_chart}</div>
    <table>
      <thead><tr><th>Bucket</th><th>Scope</th><th class='num'>Current Weight</th><th class='num'>Policy Weight</th><th class='num'>Active (OW/UW)</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{policy_country_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>US Sector Breakdown</h2>
    <table>
      <thead><tr><th>Sector</th><th>Scope</th><th class='num'>Net Exposure</th><th class='num'>Gross Exposure</th><th class='num'>Dollar%</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{sector_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>Policy Drift - US Sector (within US EQ scope)</h2>
    <div class='chart'>{policy_sector_chart}</div>
    <table>
      <thead><tr><th>Bucket</th><th>Scope</th><th class='num'>Current Weight</th><th class='num'>Policy Weight</th><th class='num'>Active (OW/UW)</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{policy_sector_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>FI Tenor Breakdown</h2>
    <table>
      <thead><tr><th>Tenor</th><th>Label</th><th>Scope</th><th class='num'>Net 10Y Eq Exposure</th><th class='num'>Gross 10Y Eq Exposure</th><th class='num'>Dollar%</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{tenor_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>Position Risk Decomposition</h2>
    <p>Rows marked <strong>excluded</strong> are shown for audit only and do not feed the portfolio summary, allocation breakdowns, or portfolio risk aggregation.</p>
    <table>
      <thead>
        <tr>
          <th>Account</th><th>Ticker</th><th>Name</th><th>Asset Class</th><th>Type</th>
          <th class='num'>Qty</th><th class='num'>Gross Exposure (FI 10Y Eq)</th><th class='num'>Net Exposure (FI 10Y Eq)</th>
          <th class='num'>Dollar%</th><th class='num'>Vol (1M/3M)</th><th class='num'>Vol (5Y)</th><th class='num'>Vol (EWMA)</th><th>3M Trend</th><th class='num'>Vol Contribution</th>
          <th>Mapping</th><th>Report Scope</th>
        </tr>
      </thead>
      <tbody>{position_rows}</tbody>
    </table>
  </div>
"""


def _format_optional_amount(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f}"


def _render_breakdown_rows(
    rows: Iterable[BreakdownRow],
    *,
    include_bucket_label: bool = False,
) -> str:
    materialized = list(rows)
    if not materialized:
        colspan = 7 if include_bucket_label else 6
        return f"<tr><td colspan='{colspan}'>No data</td></tr>"
    rendered_rows: list[str] = []
    for row in materialized:
        label_cell = f"<td>{html.escape(row.bucket_label)}</td>" if include_bucket_label else ""
        rendered_rows.append(
            "<tr>"
            f"<td>{html.escape(row.bucket)}</td>"
            f"{label_cell}"
            f"<td>{html.escape(row.parent)}</td>"
            f"<td class='num'>{row.exposure_usd:,.2f}</td>"
            f"<td class='num'>{row.gross_exposure_usd:,.2f}</td>"
            f"<td class='num'>{row.dollar_weight:.2%}</td>"
            f"<td class='num'>{row.risk_contribution_estimated:.2%}</td>"
            "</tr>"
        )
    return "\n".join(rendered_rows)


def _render_allocation_summary_rows(rows: Iterable[CategorySummaryRow]) -> str:
    materialized = list(rows)
    if not materialized:
        return "<tr><td colspan='5'>No data</td></tr>"
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(row.asset_class)}</td>"
        f"<td class='num'>{row.exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.gross_exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.dollar_weight:.2%}</td>"
        f"<td class='num'>{row.risk_contribution_estimated:.2%}</td>"
        "</tr>"
        for row in materialized
    )


def _is_report_included(row: RiskInputRow | RiskMetricsRow) -> bool:
    if row.mapping_status == "outside_scope":
        return False
    if row.asset_class.upper() == "OUTSIDE_SCOPE":
        return False
    if row.instrument_type in {"Option", "Outside Scope"}:
        return False
    return True


def _report_scope_label(row: RiskInputRow | RiskMetricsRow) -> str:
    return "included" if _is_report_included(row) else "excluded"


def _is_vol_included(row: RiskInputRow | RiskMetricsRow) -> bool:
    return _is_report_included(row) and row.mapping_status == "mapped"


def _render_policy_drift_rows(rows: Iterable[PolicyDriftRow]) -> str:
    materialized = list(rows)
    if not materialized:
        return "<tr><td colspan='6'>No data</td></tr>"
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(row.bucket)}</td>"
        f"<td>{html.escape(row.scope)}</td>"
        f"<td class='num'>{row.current_weight:.2%}</td>"
        f"<td class='num'>{row.policy_weight:.2%}</td>"
        f"<td class='num'>{row.active_weight:+.2%}</td>"
        f"<td class='num'>{row.current_risk_contribution:.2%}</td>"
        "</tr>"
        for row in materialized
    )


def _render_policy_drift_chart(rows: Iterable[PolicyDriftRow]) -> str:
    materialized = list(rows)
    if not materialized:
        return "<div>No data</div>"
    max_abs = max(abs(row.active_weight) for row in materialized) or 1e-9
    chart_rows: list[str] = []
    for row in materialized:
        if row.active_weight >= 0:
            fill = (
                "<span class='chart-fill-pos' "
                f"style='width:{(abs(row.active_weight) / max_abs) * 50:.2f}%;'></span>"
            )
        else:
            left = 50 - (abs(row.active_weight) / max_abs) * 50
            fill = (
                "<span class='chart-fill-neg' "
                f"style='left:{left:.2f}%; width:{(abs(row.active_weight) / max_abs) * 50:.2f}%;'></span>"
            )
        chart_rows.append(
            "<div class='chart-row'>"
            f"<div>{html.escape(row.bucket)}</div>"
            "<div class='chart-track'><span class='chart-midline'></span>"
            f"{fill}"
            "</div>"
            f"<div class='chart-value'>{row.active_weight:+.2%}</div>"
            "</div>"
        )
    return "\n".join(chart_rows)


def _sparkline_svg_for_returns(returns: pd.Series | list[float]) -> str:
    series = _coerce_return_series(returns).dropna()
    if series.empty:
        return "<span>-</span>"
    recent = series.tail(HIST_3M_DAYS)
    if recent.empty:
        return "<span>-</span>"
    curve = (1.0 + recent.astype(float)).cumprod() - 1.0
    values = curve.tolist()
    if len(values) < 2:
        return "<span>-</span>"
    width = 120.0
    height = 28.0
    min_value = min(values)
    max_value = max(values)
    span = max(max_value - min_value, 1e-9)
    points: list[str] = []
    for idx, value in enumerate(values):
        x = (idx / (len(values) - 1)) * width
        y = height - ((value - min_value) / span) * height
        points.append(f"{x:.2f},{y:.2f}")
    stroke = "#16a34a" if values[-1] >= values[0] else "#dc2626"
    points_attr = " ".join(points)
    return (
        "<svg class='sparkline' viewBox='0 0 120 28' preserveAspectRatio='none' role='img' "
        "aria-label='3M cumulative return trend'>"
        f"<polyline fill='none' stroke='{stroke}' stroke-width='1.5' points='{points_attr}' />"
        "</svg>"
    )


def _load_or_build_returns(
    *,
    returns_path: str | Path | None,
    rows: list[RiskInputRow],
    yahoo_client: YahooFinanceClient,
    progress: ProgressReporter | None = None,
) -> dict[str, pd.Series]:
    if returns_path is not None:
        if progress is not None:
            progress.done("Yahoo returns", detail="loaded override file")
        return _load_returns(returns_path)
    return build_internal_id_return_series_from_yahoo(
        rows,
        yahoo_client=yahoo_client,
        cache_dir=DEFAULT_YAHOO_RETURNS_CACHE_DIR,
        progress=progress,
    )


def _build_returns_from_yahoo(
    *,
    rows: list[RiskInputRow],
    yahoo_client: YahooFinanceClient,
) -> dict[str, pd.Series]:
    return build_internal_id_return_series_from_yahoo(
        rows,
        yahoo_client=yahoo_client,
        cache_dir=DEFAULT_YAHOO_RETURNS_CACHE_DIR,
    )


def _security_vol(
    *,
    returns: pd.Series | list[float],
    asset_class: str,
    duration: float | None,
    proxy: Mapping[str, float],
    method: str,
    volatility: VolatilityMethodologyConfig | None = None,
    proxy_defaults: Mapping[str, float] | None = None,
    move_to_yield_vol_factor: float = DEFAULT_MOVE_TO_YIELD_VOL_FACTOR,
    internal_id: str = "",
    display_ticker: str = "",
) -> float:
    methodology = volatility or VolatilityMethodologyConfig(
        trading_days=TRADING_DAYS,
        short_window_days=HIST_1M_DAYS,
        long_window_days=HIST_3M_DAYS,
        long_term_lookback_years=DEFAULT_LONG_TERM_LOOKBACK_YEARS,
        cash_vol=DEFAULT_CASH_VOL,
    )
    series = _coerce_return_series(returns)
    if not series.dropna().empty:
        normalized = method.strip().lower()
        if normalized == "5y_realized":
            return long_term_vol(
                returns=series,
                lookback=methodology.trading_days * methodology.long_term_lookback_years,
                annualization_factor=methodology.trading_days,
                ddof=1,
            )
        if normalized == "ewma":
            ewma_series = series_ewma_vol(
                returns=series,
                annualization_factor=methodology.trading_days,
                lambda_=DEFAULT_EWMA_LAMBDA,
                min_periods=20,
                demean=False,
            )
            return last_valid_scalar(ewma_series) or 0.0
        return _historical_geomean_vol_from_series(
            series,
            trading_days=methodology.trading_days,
            short_window_days=methodology.short_window_days,
            long_window_days=methodology.long_window_days,
        )
    reason = "empty_returns" if _coerce_return_series(returns).empty else "all_nan_returns"
    if str(asset_class).upper() != "CASH":
        logger.warning(
            "Vol fallback to proxy: internal_id=%s ticker=%s asset_class=%s method=%s reason=%s",
            internal_id or "?",
            display_ticker or "?",
            asset_class,
            method,
            reason,
        )
    return _proxy_fallback_security_vol(
        asset_class=asset_class,
        duration=duration,
        proxy=proxy,
        proxy_defaults=proxy_defaults,
        move_to_yield_vol_factor=move_to_yield_vol_factor,
        cash_vol=methodology.cash_vol,
    )


def _compute_proxy_realized_5y_vols(
    *,
    proxy_group_returns: Mapping[str, pd.Series],
    methodology: VolatilityMethodologyConfig | None,
) -> dict[str, float]:
    """Compute realized 5Y vol for each asset-class correlation proxy ticker.

    Used as the denominator in the forward-looking adjusted-proxy formula
    ``fwd = realized_5y(asset) / realized_5y(proxy) * proxy_level``.
    Returns a dict with only positive, finite values.
    """
    config = methodology or VolatilityMethodologyConfig(
        trading_days=TRADING_DAYS,
        short_window_days=HIST_1M_DAYS,
        long_window_days=HIST_3M_DAYS,
        long_term_lookback_years=DEFAULT_LONG_TERM_LOOKBACK_YEARS,
        cash_vol=DEFAULT_CASH_VOL,
    )
    lookback = config.trading_days * config.long_term_lookback_years
    out: dict[str, float] = {}
    for asset_class, series in proxy_group_returns.items():
        coerced = _coerce_return_series(series)
        if coerced.dropna().empty:
            continue
        value = long_term_vol(
            returns=coerced,
            lookback=lookback,
            annualization_factor=config.trading_days,
            ddof=1,
        )
        if value is None or not math.isfinite(value) or value <= 0:
            continue
        out[asset_class] = float(value)
    return out


def _adjusted_proxy_security_vol(
    *,
    returns: pd.Series | list[float],
    asset_class: str,
    duration: float | None,
    proxy: Mapping[str, float],
    volatility: VolatilityMethodologyConfig | None = None,
    proxy_defaults: Mapping[str, float] | None = None,
    move_to_yield_vol_factor: float = DEFAULT_MOVE_TO_YIELD_VOL_FACTOR,
    proxy_5y_realized: float | None = None,
    internal_id: str = "",
    display_ticker: str = "",
) -> float:
    """Forward-looking vol scaled by realized-vol ratio against the asset-class proxy.

    Formula: ``fwd_vol = realized_5Y(asset) / realized_5Y(proxy) * proxy_level(asset_class)``.
    Falls back to :func:`_proxy_fallback_security_vol` (the simple proxy) when the
    asset's or proxy's realized 5Y vol is unavailable, emitting a WARNING.
    MACRO / CASH always use the simple fallback because no correlation proxy
    ticker is defined for them.
    """
    methodology = volatility or VolatilityMethodologyConfig(
        trading_days=TRADING_DAYS,
        short_window_days=HIST_1M_DAYS,
        long_window_days=HIST_3M_DAYS,
        long_term_lookback_years=DEFAULT_LONG_TERM_LOOKBACK_YEARS,
        cash_vol=DEFAULT_CASH_VOL,
    )
    asset_class_key = str(asset_class).upper()
    proxy_symbol = ASSET_CLASS_CORR_PROXY_SYMBOLS.get(asset_class_key)

    simple = _proxy_fallback_security_vol(
        asset_class=asset_class,
        duration=duration,
        proxy=proxy,
        proxy_defaults=proxy_defaults,
        move_to_yield_vol_factor=move_to_yield_vol_factor,
        cash_vol=methodology.cash_vol,
    )
    # Asset classes without a correlation proxy (MACRO, CASH) have no sensible
    # ratio — return the simple proxy vol directly, no warning needed.
    if not proxy_symbol:
        return simple

    series = _coerce_return_series(returns)
    if series.dropna().empty:
        if asset_class_key != "CASH":
            logger.warning(
                "Forward-looking vol fallback: internal_id=%s ticker=%s asset_class=%s reason=no_realized_for_ratio",
                internal_id or "?",
                display_ticker or "?",
                asset_class,
            )
        return simple

    asset_realized = long_term_vol(
        returns=series,
        lookback=methodology.trading_days * methodology.long_term_lookback_years,
        annualization_factor=methodology.trading_days,
        ddof=1,
    )
    if (
        asset_realized is None
        or not math.isfinite(asset_realized)
        or asset_realized <= 0
    ):
        logger.warning(
            "Forward-looking vol fallback: internal_id=%s ticker=%s asset_class=%s reason=no_realized_for_ratio",
            internal_id or "?",
            display_ticker or "?",
            asset_class,
        )
        return simple
    if (
        proxy_5y_realized is None
        or not math.isfinite(proxy_5y_realized)
        or proxy_5y_realized <= 0
    ):
        logger.warning(
            "Forward-looking vol fallback: internal_id=%s ticker=%s asset_class=%s proxy=%s reason=no_proxy_realized",
            internal_id or "?",
            display_ticker or "?",
            asset_class,
            proxy_symbol,
        )
        return simple
    return float((asset_realized / proxy_5y_realized) * simple)


def _proxy_fallback_security_vol(
    *,
    asset_class: str,
    duration: float | None,
    proxy: Mapping[str, float],
    proxy_defaults: Mapping[str, float] | None = None,
    move_to_yield_vol_factor: float = DEFAULT_MOVE_TO_YIELD_VOL_FACTOR,
    cash_vol: float = DEFAULT_CASH_VOL,
) -> float:
    defaults = _merged_proxy_default_levels(proxy_defaults)
    if asset_class.upper() == "FI" and duration is not None and duration > 0:
        yield_vol = proxy_index_to_yield_vol(
            proxy.get("MOVE", defaults["MOVE"]),
            mapping_factor=move_to_yield_vol_factor,
        )
        return float(
            yield_vol_to_price_vol(
                yield_vol=yield_vol,
                modified_duration=duration,
            )
        )
    return estimated_asset_class_vol(
        asset_class,
        proxy,
        proxy_defaults=defaults,
        cash_vol=cash_vol,
    )


def _build_security_loadings(
    rows: list[RiskInputRow],
    vols: Mapping[str, float],
) -> dict[str, float]:
    return {
        row.internal_id: (
            (row.signed_exposure_usd / _funded_aum(rows)) * vols.get(row.internal_id, 0.0)
            if _funded_aum(rows) > 0
            else 0.0
        )
        for row in rows
    }


def _build_group_loadings(
    rows: list[RiskInputRow],
    vols: Mapping[str, float],
) -> dict[str, float]:
    loadings: dict[str, float] = {}
    funded_aum = _funded_aum(rows)
    for row in rows:
        if funded_aum <= 0:
            continue
        loadings[row.asset_class] = loadings.get(row.asset_class, 0.0) + (
            row.signed_exposure_usd / funded_aum
        ) * vols.get(row.internal_id, 0.0)
    return loadings


def _build_group_returns(
    rows: list[RiskInputRow],
    returns: Mapping[str, pd.Series],
) -> dict[str, pd.Series]:
    grouped: dict[str, list[RiskInputRow]] = {}
    for row in rows:
        grouped.setdefault(row.asset_class, []).append(row)

    series: dict[str, pd.Series] = {}
    for asset_class, group_rows in grouped.items():
        candidates = [row for row in group_rows if _has_usable_returns(returns.get(row.internal_id))]
        if not candidates:
            series[asset_class] = pd.Series(dtype=float)
            continue
        aligned_series = align_series(*(returns[row.internal_id] for row in candidates), join="inner")
        if not aligned_series or len(aligned_series[0].dropna()) < 2:
            series[asset_class] = pd.Series(dtype=float)
            continue
        denominator = sum(abs(row.signed_exposure_usd) for row in candidates) or 1.0
        aggregate = pd.Series(0.0, index=aligned_series[0].index, dtype=float)
        for row, asset_returns in zip(candidates, aligned_series):
            aggregate = aggregate + (row.signed_exposure_usd / denominator) * asset_returns.astype(float)
        series[asset_class] = aggregate
    return series


def _load_asset_class_proxy_returns(
    *,
    asset_classes: Iterable[str],
    yahoo_client: YahooFinanceClient,
    cache_dir: str | Path = DEFAULT_YAHOO_RETURNS_CACHE_DIR,
    mapping: Mapping[str, str | None] = ASSET_CLASS_CORR_PROXY_SYMBOLS,
) -> dict[str, pd.Series]:
    """Fetch Yahoo return series for the per-asset-class correlation proxy tickers.

    Returns a dict keyed by asset class (as provided) for classes whose mapping
    resolves to a non-empty symbol and for which the cache fetch succeeds.
    Asset classes with ``None`` mapping (e.g. MACRO, CASH) are intentionally
    omitted so the correlation builder can treat them as zero-correlated.
    """
    resolved: dict[str, pd.Series] = {}
    for asset_class in asset_classes:
        symbol = mapping.get(str(asset_class).upper())
        if not symbol:
            continue
        try:
            cache = ensure_symbol_return_cache(
                symbol,
                yahoo_client=yahoo_client,
                cache_dir=cache_dir,
            )
        except YahooFinanceTransientError:
            logger.warning(
                "Asset-class corr proxy fetch failed (transient): asset_class=%s symbol=%s",
                asset_class,
                symbol,
            )
            continue
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Asset-class corr proxy fetch failed: asset_class=%s symbol=%s err=%s",
                asset_class,
                symbol,
                exc,
            )
            continue
        if not cache.series.dropna().empty:
            resolved[asset_class] = cache.series.copy()
    return resolved


def _build_group_correlation(
    *,
    asset_classes: Iterable[str],
    group_returns: Mapping[str, pd.Series],
    mode: str,
    proxy_group_returns: Mapping[str, pd.Series] | None = None,
    proxy_mapping: Mapping[str, str | None] = ASSET_CLASS_CORR_PROXY_SYMBOLS,
) -> dict[tuple[str, str], float]:
    normalized_mode = mode.strip().lower()
    keys = sorted(set(asset_classes))
    proxy_group_returns = proxy_group_returns or {}
    corr: dict[tuple[str, str], float] = {}
    for left in keys:
        for right in keys:
            if left == right:
                corr[(left, right)] = 1.0
                continue
            if "cash" in {left.lower(), right.lower()}:
                corr[(left, right)] = 0.0
                continue
            if normalized_mode == "corr_1":
                corr[(left, right)] = 1.0
                continue
            if normalized_mode == "corr_0":
                corr[(left, right)] = 0.0
                continue
            # historical: prefer per-asset-class proxy tickers (e.g. ACWI/AGG/GLD)
            # so the inter-asset correlation reflects index-level behavior rather
            # than the current portfolio's idiosyncratic composition. Asset classes
            # without a proxy mapping (e.g. MACRO) are treated as 0 correlation.
            left_no_proxy = proxy_mapping.get(left.upper(), "__UNSET__") is None
            right_no_proxy = proxy_mapping.get(right.upper(), "__UNSET__") is None
            if left_no_proxy or right_no_proxy:
                corr[(left, right)] = 0.0
                continue
            left_series = proxy_group_returns.get(left)
            right_series = proxy_group_returns.get(right)
            if left_series is None or right_series is None:
                # Proxy fetch unavailable; fall back to position-aggregated returns.
                corr[(left, right)] = pairwise_corr(
                    group_returns.get(left, []), group_returns.get(right, [])
                )
                continue
            corr[(left, right)] = pairwise_corr(left_series, right_series)
    return corr


def _portfolio_vol_from_group_loadings(
    loadings: Mapping[str, float],
    corr: Mapping[tuple[str, str], float],
) -> float:
    variance = 0.0
    keys = list(loadings)
    for left in keys:
        for right in keys:
            variance += loadings[left] * loadings[right] * corr.get((left, right), 0.0)
    return math.sqrt(max(variance, 0.0))


def _select_security_loadings(
    *,
    vol_method: str,
    geomean: Mapping[str, float],
    realized_5y: Mapping[str, float],
    ewma: Mapping[str, float],
    forward_looking: Mapping[str, float] | None = None,
) -> Mapping[str, float]:
    normalized = vol_method.strip().lower()
    if normalized == "5y_realized":
        return realized_5y
    if normalized == "ewma":
        return ewma
    if normalized == "forward_looking":
        return forward_looking if forward_looking is not None else geomean
    return geomean


def _load_risk_report_config(
    *,
    risk_config_path: str | Path | None,
    allocation_policy_path: str | Path | None,
) -> RiskReportConfig:
    config_path = Path(risk_config_path) if risk_config_path is not None else DEFAULT_RISK_REPORT_CONFIG_PATH
    payload: dict[str, Any] = {}
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("Risk report config must be a mapping")
        payload = dict(loaded.get("risk_report", loaded))

    lookthrough_payload = dict(payload.get("lookthrough", {}))
    eq_file = str(lookthrough_payload.get("eq_country", DEFAULT_EQ_COUNTRY_LOOKTHROUGH_PATH.name))
    us_file = str(lookthrough_payload.get("us_sector", DEFAULT_US_SECTOR_LOOKTHROUGH_PATH.name))
    base_dir = config_path.parent if config_path.exists() else DEFAULT_RISK_REPORT_CONFIG_PATH.parent
    eq_path = Path(eq_file) if Path(eq_file).is_absolute() else (base_dir / eq_file)
    us_path = Path(us_file) if Path(us_file).is_absolute() else (base_dir / us_file)

    policy = _parse_allocation_policy(dict(payload.get("policy", {})))
    if allocation_policy_path is not None:
        legacy_loaded = yaml.safe_load(Path(allocation_policy_path).read_text(encoding="utf-8")) or {}
        if not isinstance(legacy_loaded, dict):
            raise ValueError("Allocation policy config must be a mapping")
        policy = _parse_allocation_policy(dict(legacy_loaded.get("policy", legacy_loaded)))
    proxy_payload = payload.get("proxy", {})
    if not isinstance(proxy_payload, Mapping):
        raise ValueError("Risk report proxy config must be a mapping")
    _reject_legacy_fixed_income_proxy_keys(proxy_payload, source="risk_report.proxy")
    volatility_payload = payload.get("volatility", {})
    if not isinstance(volatility_payload, Mapping):
        raise ValueError("Risk report volatility config must be a mapping")
    fixed_income_payload = payload.get("fixed_income", {})
    if not isinstance(fixed_income_payload, Mapping):
        raise ValueError("Risk report fixed_income config must be a mapping")
    explicit_proxy_payload = {
        str(key): value
        for key, value in proxy_payload.items()
        if str(key).strip().upper() not in {"DEFAULTS", "YAHOO"}
    }

    labels_payload = payload.get("vol_method_labels", {}) or {}
    if not isinstance(labels_payload, Mapping):
        raise ValueError("Risk report vol_method_labels config must be a mapping")
    vol_method_labels: dict[str, str] = {}
    for raw_label, raw_key in labels_payload.items():
        label = str(raw_label).strip()
        key = str(raw_key).strip()
        if key not in SUPPORTED_VOL_METHOD_KEYS:
            raise ValueError(
                f"Unsupported vol method key in vol_method_labels['{label}']: {key}. "
                f"Valid keys: {list(SUPPORTED_VOL_METHOD_KEYS)}"
            )
        vol_method_labels[label] = key
    if not vol_method_labels:
        vol_method_labels = dict(DEFAULT_VOL_METHOD_LABELS)

    fx_excluded_payload = payload.get("fx_excluded_asset_classes", [])
    if not isinstance(fx_excluded_payload, (list, tuple)):
        raise ValueError("fx_excluded_asset_classes must be a list")
    fx_excluded = tuple(str(x).strip().upper() for x in fx_excluded_payload) or DEFAULT_FX_EXCLUDED_ASSET_CLASSES

    return RiskReportConfig(
        eq_country_lookthrough_path=eq_path,
        us_sector_lookthrough_path=us_path,
        policy=policy,
        proxy=explicit_proxy_payload,
        proxy_defaults=_parse_proxy_default_levels(proxy_payload.get("defaults", {})),
        proxy_yahoo=_parse_proxy_yahoo_config(proxy_payload.get("yahoo", {})),
        volatility=_parse_volatility_config(volatility_payload),
        fixed_income=_parse_fixed_income_config(fixed_income_payload),
        vol_method_labels=vol_method_labels,
        fx_excluded_asset_classes=fx_excluded,
    )


def _parse_allocation_policy(payload: Mapping[str, Any]) -> AllocationPolicyConfig:
    portfolio = dict(payload.get("portfolio_asset_class_targets", {}))
    equity = dict(payload.get("equity_country_policy_mix", {"ACWI": 1.0}))
    us_equity = dict(payload.get("us_equity_sector_policy_mix", {"SPY": 1.0}))
    return AllocationPolicyConfig(
        portfolio_asset_class_targets={str(k).upper(): float(v) for k, v in portfolio.items()},
        equity_country_policy_mix={str(k).upper(): float(v) for k, v in equity.items()},
        us_equity_sector_policy_mix={str(k).upper(): float(v) for k, v in us_equity.items()},
    )


def _parse_proxy_default_levels(payload: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(payload, Mapping):
        raise ValueError("Risk report proxy.defaults config must be a mapping")
    defaults = dict(DEFAULT_PROXY_LEVELS)
    for raw_key, raw_value in payload.items():
        key = str(raw_key).strip().upper()
        if key not in DEFAULT_PROXY_LEVELS:
            raise ValueError(f"Unsupported proxy.defaults key: {key}")
        defaults[key] = _coerce_non_negative_float(raw_value, f"proxy.defaults.{key}")
    return defaults


def _parse_proxy_yahoo_config(payload: Mapping[str, Any]) -> ProxyYahooConfig:
    if not isinstance(payload, Mapping):
        raise ValueError("Risk report proxy.yahoo config must be a mapping")
    symbols = dict(DEFAULT_PROXY_YAHOO_SYMBOLS)
    raw_symbols = payload.get("symbols", {})
    if not isinstance(raw_symbols, Mapping):
        raise ValueError("Risk report proxy.yahoo.symbols config must be a mapping")
    for raw_key, raw_value in raw_symbols.items():
        key = str(raw_key).strip().upper()
        if key not in DEFAULT_PROXY_YAHOO_SYMBOLS:
            raise ValueError(f"Unsupported proxy.yahoo.symbols key: {key}")
        symbol = str(raw_value).strip()
        if not symbol:
            raise ValueError(f"proxy.yahoo.symbols.{key} must be non-empty")
        symbols[key] = symbol
    period = str(payload.get("period", DEFAULT_PROXY_YAHOO_PERIOD)).strip()
    interval = str(payload.get("interval", DEFAULT_PROXY_YAHOO_INTERVAL)).strip()
    if not period:
        raise ValueError("proxy.yahoo.period must be non-empty")
    if not interval:
        raise ValueError("proxy.yahoo.interval must be non-empty")
    return ProxyYahooConfig(symbols=symbols, period=period, interval=interval)


def _parse_volatility_config(payload: Mapping[str, Any]) -> VolatilityMethodologyConfig:
    if not isinstance(payload, Mapping):
        raise ValueError("Risk report volatility config must be a mapping")
    return VolatilityMethodologyConfig(
        trading_days=_coerce_positive_int(payload.get("trading_days", TRADING_DAYS), "volatility.trading_days"),
        short_window_days=_coerce_positive_int(
            payload.get("short_window_days", HIST_1M_DAYS),
            "volatility.short_window_days",
        ),
        long_window_days=_coerce_positive_int(
            payload.get("long_window_days", HIST_3M_DAYS),
            "volatility.long_window_days",
        ),
        long_term_lookback_years=_coerce_positive_int(
            payload.get("long_term_lookback_years", DEFAULT_LONG_TERM_LOOKBACK_YEARS),
            "volatility.long_term_lookback_years",
        ),
        cash_vol=_coerce_non_negative_float(payload.get("cash_vol", DEFAULT_CASH_VOL), "volatility.cash_vol"),
    )


def _parse_fixed_income_config(payload: Mapping[str, Any]) -> FixedIncomeMethodologyConfig:
    if not isinstance(payload, Mapping):
        raise ValueError("Risk report fixed_income config must be a mapping")
    return FixedIncomeMethodologyConfig(
        fi_10y_eq_mod_duration=_coerce_positive_float(
            payload.get("fi_10y_eq_mod_duration", DEFAULT_FI_10Y_EQ_MOD_DURATION),
            "fixed_income.fi_10y_eq_mod_duration",
        ),
        move_to_yield_vol_factor=_coerce_positive_float(
            payload.get("move_to_yield_vol_factor", DEFAULT_MOVE_TO_YIELD_VOL_FACTOR),
            "fixed_income.move_to_yield_vol_factor",
        ),
    )


def _coerce_positive_int(value: Any, label: str) -> int:
    parsed = float(value)
    if not parsed.is_integer():
        raise ValueError(f"{label} must be an integer")
    resolved = int(parsed)
    if resolved <= 0:
        raise ValueError(f"{label} must be positive")
    return resolved


def _coerce_positive_float(value: Any, label: str) -> float:
    resolved = float(value)
    if resolved <= 0:
        raise ValueError(f"{label} must be positive")
    return resolved


def _coerce_non_negative_float(value: Any, label: str) -> float:
    resolved = float(value)
    if resolved < 0:
        raise ValueError(f"{label} must be non-negative")
    return resolved


def _reject_legacy_fixed_income_proxy_keys(payload: Mapping[str, Any], *, source: str) -> None:
    normalized_keys = {str(key).strip().upper() for key in payload}
    if "FI_10Y_EQ_MOD_DURATION" in normalized_keys:
        raise ValueError(
            f"{source}.FI_10Y_EQ_MOD_DURATION is no longer supported; "
            "use fixed_income.fi_10y_eq_mod_duration"
        )


def _expand_policy_mix(
    *,
    mix: Mapping[str, float],
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> dict[str, float]:
    expanded: dict[str, float] = {}
    for key, mix_weight in mix.items():
        normalized_key = str(key).upper()
        if mix_weight <= 0:
            continue
        if normalized_key in lookthrough:
            for bucket, bucket_weight in lookthrough[normalized_key]:
                expanded[bucket] = expanded.get(bucket, 0.0) + float(mix_weight) * float(bucket_weight)
            continue
        expanded[normalized_key] = expanded.get(normalized_key, 0.0) + float(mix_weight)
    total = sum(expanded.values())
    if total <= 0:
        return {}
    return {bucket: weight / total for bucket, weight in expanded.items()}


def _build_asset_class_policy_drift(
    *,
    allocation_summary: list[CategorySummaryRow],
    asset_class_targets: Mapping[str, float],
) -> list[PolicyDriftRow]:
    current = {row.asset_class.upper(): row for row in allocation_summary}
    raw_policy = {
        str(k).upper(): float(v)
        for k, v in asset_class_targets.items()
        if float(v) > 0
    }
    buckets = sorted(set(current) | set(raw_policy))
    rows: list[PolicyDriftRow] = []
    for bucket in buckets:
        current_row = current.get(bucket)
        current_weight = current_row.dollar_weight if current_row is not None else 0.0
        policy_weight = raw_policy.get(bucket, 0.0)
        rows.append(
            PolicyDriftRow(
                bucket=bucket,
                scope="PORTFOLIO",
                current_weight=current_weight,
                policy_weight=policy_weight,
                active_weight=current_weight - policy_weight,
                current_risk_contribution=current_row.risk_contribution_estimated if current_row is not None else 0.0,
            )
        )
    return sorted(rows, key=lambda item: abs(item.active_weight), reverse=True)


def _build_breakdown_policy_drift(
    *,
    breakdown: list[BreakdownRow],
    scope: str,
    policy_weights: Mapping[str, float],
) -> list[PolicyDriftRow]:
    current_total = sum(max(row.dollar_weight, 0.0) for row in breakdown)
    current_by_bucket = {row.bucket: row for row in breakdown}
    buckets = sorted(set(current_by_bucket) | set(policy_weights))
    drift_rows: list[PolicyDriftRow] = []
    for bucket in buckets:
        current_row = current_by_bucket.get(bucket)
        current_weight = ((current_row.dollar_weight / current_total) if current_row is not None and current_total > 0 else 0.0)
        policy_weight = policy_weights.get(bucket, 0.0)
        drift_rows.append(
            PolicyDriftRow(
                bucket=bucket,
                scope=scope,
                current_weight=current_weight,
                policy_weight=policy_weight,
                active_weight=current_weight - policy_weight,
                current_risk_contribution=current_row.risk_contribution_estimated if current_row is not None else 0.0,
            )
    )
    return sorted(drift_rows, key=lambda item: abs(item.active_weight), reverse=True)


def _build_eq_country_policy_drift(
    *,
    breakdown: list[BreakdownRow],
    policy_mix: Mapping[str, float],
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> list[PolicyDriftRow]:
    policy_weights = _expand_eq_country_policy_mix(
        mix=policy_mix,
        lookthrough=lookthrough,
    )
    current_weights, current_risk = _aggregate_prefixed_eq_country_current(
        breakdown=breakdown,
        lookthrough=lookthrough,
    )
    buckets = sorted(
        set(current_weights) | set(policy_weights),
        key=lambda bucket: _eq_country_policy_bucket_sort_key(bucket, lookthrough),
    )
    rows: list[PolicyDriftRow] = []
    for bucket in buckets:
        rows.append(
            PolicyDriftRow(
                bucket=bucket,
                scope="EQ",
                current_weight=current_weights.get(bucket, 0.0),
                policy_weight=policy_weights.get(bucket, 0.0),
                active_weight=current_weights.get(bucket, 0.0) - policy_weights.get(bucket, 0.0),
                current_risk_contribution=current_risk.get(bucket, 0.0),
            )
        )
    return rows


def _normalize_weights(weights: Mapping[str, float]) -> dict[str, float]:
    cleaned = {str(bucket): float(value) for bucket, value in weights.items() if float(value) > 0}
    total = sum(cleaned.values())
    if total <= 0:
        return {}
    return {bucket: value / total for bucket, value in cleaned.items()}


def _expand_eq_country_policy_mix(
    *,
    mix: Mapping[str, float],
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> dict[str, float]:
    prefixed: dict[str, float] = {}
    for key, mix_weight in mix.items():
        normalized_key = str(key).upper()
        if mix_weight <= 0:
            continue
        _merge_weight_maps(
            prefixed,
            _expand_eq_country_bucket_weights(
                bucket=normalized_key,
                weight=1.0,
                lookthrough=lookthrough,
            ),
            scale=float(mix_weight),
        )
    return _normalize_weights(prefixed)


def _build_eq_country_breakdown(
    rows: list[RiskInputRow],
    estimated_loadings: Mapping[str, float],
    *,
    lookthrough_path: Path = DEFAULT_EQ_COUNTRY_LOOKTHROUGH_PATH,
) -> list[BreakdownRow]:
    lookthrough = _load_weight_table(lookthrough_path, "eq_country", "country_bucket")
    return _build_breakdown(
        rows=rows,
        estimated_loadings=estimated_loadings,
        expander=lambda row: _expand_country_allocations(row, lookthrough),
        parent="EQ",
    )


def _build_us_sector_breakdown(
    rows: list[RiskInputRow],
    estimated_loadings: Mapping[str, float],
    *,
    lookthrough_path: Path = DEFAULT_US_SECTOR_LOOKTHROUGH_PATH,
) -> list[BreakdownRow]:
    lookthrough = _load_weight_table(lookthrough_path, "canonical_symbol", "sector")
    return _build_breakdown(
        rows=rows,
        estimated_loadings=estimated_loadings,
        expander=lambda row: _expand_us_sector_allocations(row, lookthrough),
        parent="US_EQ",
    )


def _build_fi_tenor_breakdown(
    rows: list[RiskInputRow],
    estimated_loadings: Mapping[str, float],
) -> list[BreakdownRow]:
    breakdown = _build_breakdown(
        rows=rows,
        estimated_loadings=estimated_loadings,
        expander=lambda row: [(row.fi_tenor or "UNASSIGNED", 1.0)] if row.asset_class == "FI" else [],
        parent="FI",
        bucket_labeler=_fi_tenor_bucket_label,
    )
    bucket_order = {bucket: index for index, bucket in enumerate(FI_TENOR_BUCKET_ORDER)}
    return sorted(
        breakdown,
        key=lambda item: (
            bucket_order.get(item.bucket, len(bucket_order)),
            -item.gross_exposure_usd,
            item.bucket,
        ),
    )


def _build_breakdown(
    *,
    rows: list[RiskInputRow],
    estimated_loadings: Mapping[str, float],
    expander: Any,
    parent: str,
    bucket_labeler: Any | None = None,
) -> list[BreakdownRow]:
    aggregated: dict[str, BreakdownRow] = {}
    funded_aum = _funded_aum(rows)
    for row in rows:
        for bucket, weight in expander(row):
            existing = aggregated.get(bucket)
            net_exposure = row.display_exposure_usd * weight
            gross_exposure = row.display_gross_exposure_usd * weight
            contribution = abs(estimated_loadings.get(row.internal_id, 0.0) * weight)
            if existing is None:
                aggregated[bucket] = BreakdownRow(
                    bucket=bucket,
                    bucket_label=bucket_labeler(bucket) if bucket_labeler is not None else "",
                    parent=parent,
                    exposure_usd=net_exposure,
                    gross_exposure_usd=gross_exposure,
                    dollar_weight=(gross_exposure / funded_aum) if funded_aum > 0 else 0.0,
                    risk_contribution_estimated=contribution,
                )
                continue
            aggregated[bucket] = BreakdownRow(
                bucket=existing.bucket,
                bucket_label=existing.bucket_label,
                parent=existing.parent,
                exposure_usd=existing.exposure_usd + net_exposure,
                gross_exposure_usd=existing.gross_exposure_usd + gross_exposure,
                dollar_weight=((existing.gross_exposure_usd + gross_exposure) / funded_aum) if funded_aum > 0 else 0.0,
                risk_contribution_estimated=existing.risk_contribution_estimated + contribution,
            )
    return sorted(aggregated.values(), key=lambda item: item.gross_exposure_usd, reverse=True)


def _fi_tenor_bucket_label(bucket: str) -> str:
    return FI_TENOR_BUCKET_LABELS.get(bucket, "")


def _merge_weight_maps(
    target: dict[str, float],
    source: Mapping[str, float],
    *,
    scale: float = 1.0,
) -> None:
    for bucket, value in source.items():
        if value <= 0:
            continue
        target[bucket] = target.get(bucket, 0.0) + float(value) * float(scale)


def _aggregate_prefixed_eq_country_current(
    *,
    breakdown: list[BreakdownRow],
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> tuple[dict[str, float], dict[str, float]]:
    current_weights: dict[str, float] = {}
    current_risk: dict[str, float] = {}
    leaf_aliases = _build_eq_country_leaf_aliases(lookthrough)

    for row in breakdown:
        bucket = row.bucket.upper()
        prefixed = leaf_aliases.get(bucket, bucket if bucket.startswith(("DM-", "EM-")) else None)
        if prefixed is None:
            continue
        current_weights[prefixed] = current_weights.get(prefixed, 0.0) + row.dollar_weight
        current_risk[prefixed] = current_risk.get(prefixed, 0.0) + row.risk_contribution_estimated

    return _normalize_weights(current_weights), current_risk


def _eq_country_policy_bucket_sort_key(
    bucket: str,
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> tuple[int, int, str]:
    normalized_bucket = str(bucket).upper()
    prefix, _, suffix = normalized_bucket.partition("-")
    prefix_rank = {name: index for index, name in enumerate(EQ_COUNTRY_POLICY_REGION_ORDER)}
    region_rank = prefix_rank.get(prefix, len(prefix_rank))

    region_order = [str(name).upper() for name, _ in lookthrough.get(prefix, [])]
    suffix_rank_map = {name: index for index, name in enumerate(region_order)}
    suffix_rank = suffix_rank_map.get(normalized_bucket, suffix_rank_map.get(suffix.upper(), len(suffix_rank_map)))
    return region_rank, suffix_rank, normalized_bucket


def _expand_country_allocations(
    row: RiskInputRow,
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> list[tuple[str, float]]:
    if row.asset_class != "EQ":
        return []
    if row.eq_country in lookthrough:
        return list(_expand_eq_country_bucket_weights(bucket=row.eq_country, weight=1.0, lookthrough=lookthrough).items())
    leaf_aliases = _build_eq_country_leaf_aliases(lookthrough)
    normalized_country = str(row.eq_country).upper()
    if normalized_country in leaf_aliases:
        return [(leaf_aliases[normalized_country], 1.0)]
    if row.eq_country:
        return [(row.eq_country, 1.0)]
    return [("OTHER", 1.0)]


def _expand_eq_country_bucket_weights(
    *,
    bucket: str,
    weight: float,
    lookthrough: Mapping[str, list[tuple[str, float]]],
    _seen: set[str] | None = None,
) -> dict[str, float]:
    normalized_bucket = str(bucket).upper()
    if weight <= 0:
        return {}
    if _seen is None:
        _seen = set()
    if normalized_bucket in _seen:
        return {}
    children = lookthrough.get(normalized_bucket)
    if not children:
        return {normalized_bucket: float(weight)}
    expanded: dict[str, float] = {}
    next_seen = set(_seen)
    next_seen.add(normalized_bucket)
    for child_bucket, child_weight in children:
        _merge_weight_maps(
            expanded,
            _expand_eq_country_bucket_weights(
                bucket=str(child_bucket).upper(),
                weight=float(weight) * float(child_weight),
                lookthrough=lookthrough,
                _seen=next_seen,
            ),
        )
    return expanded


def _build_eq_country_leaf_aliases(
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for root in lookthrough:
        for leaf in _expand_eq_country_bucket_weights(bucket=root, weight=1.0, lookthrough=lookthrough):
            normalized_leaf = str(leaf).upper()
            aliases[normalized_leaf] = normalized_leaf
            if normalized_leaf.startswith("DM-") or normalized_leaf.startswith("EM-"):
                _, _, suffix = normalized_leaf.partition("-")
                if suffix:
                    aliases.setdefault(suffix.upper(), normalized_leaf)
    return aliases


def _expand_us_sector_allocations(
    row: RiskInputRow,
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> list[tuple[str, float]]:
    if row.asset_class != "EQ":
        return []

    def _with_unclassified(sectors: list[tuple[str, float]]) -> list[tuple[str, float]]:
        total = round(sum(w for _, w in sectors), 6)
        remainder = round(1.0 - total, 6)
        if remainder > 1e-6:
            return list(sectors) + [("UNCLASSIFIED", remainder)]
        return list(sectors)

    # Direct lookthrough by own symbol — works for known ETFs even when eq_country is unknown.
    normalized_symbol = str(row.canonical_symbol or row.symbol).upper()
    if normalized_symbol in lookthrough:
        return _with_unclassified(lookthrough[normalized_symbol])

    # Proxy / UNCLASSIFIED logic only applies to US EQ.
    if row.eq_country != "US":
        return []
    proxy = str(row.eq_sector_proxy or "").strip().upper()
    if proxy == "NONE":
        return [("UNCLASSIFIED", 1.0)]
    if proxy and proxy in lookthrough:
        return _with_unclassified(lookthrough[proxy])
    return [("UNCLASSIFIED", 1.0)]


def _load_weight_table(
    path: Path,
    key_column: str,
    bucket_column: str,
) -> dict[str, list[tuple[str, float]]]:
    if path.suffix.lower() == ".json" and key_column == "canonical_symbol" and bucket_column == "sector":
        return load_us_sector_weight_table(path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        materialized: dict[str, list[tuple[str, float]]] = {}
        for row in reader:
            key = str(row.get(key_column) or "").strip().upper()
            bucket = str(row.get(bucket_column) or "").strip()
            weight = float(row.get("weight") or 0.0)
            if not key or not bucket or weight <= 0:
                continue
            materialized.setdefault(key, []).append((bucket, weight))
        return materialized


def _refresh_us_sector_lookthrough_for_report(
    *,
    rows: Sequence[RiskInputRow],
    lookthrough_path: Path,
    progress: ProgressReporter | None = None,
) -> None:
    if lookthrough_path.suffix.lower() != ".json":
        return
    existing_symbols = load_tracked_us_sector_symbols(lookthrough_path)
    symbols = _report_us_etf_lookthrough_symbols(rows, existing_symbols=existing_symbols)
    if not symbols:
        if progress is not None:
            progress.done("ETF sector sync", detail="no US ETF refresh needed")
        return
    refresh_us_sector_lookthrough_for_report(
        symbols=symbols,
        output_path=lookthrough_path,
        progress=progress,
    )


def _report_us_etf_lookthrough_symbols(
    rows: Sequence[RiskInputRow],
    *,
    existing_symbols: set[str],
) -> list[str]:
    to_sync: set[str] = set()
    for row in rows:
        if row.mapping_status != "mapped" or row.asset_class != "EQ" or row.eq_country != "US":
            continue
        proxy = str(row.eq_sector_proxy or "").strip().upper()
        if proxy and proxy != "NONE":
            to_sync.add(proxy)
        else:
            own_symbol = str(row.canonical_symbol or row.symbol).strip().upper()
            if own_symbol and own_symbol in existing_symbols:
                to_sync.add(own_symbol)
    return sorted(to_sync)


def _looks_like_company_name(display_name: str) -> bool:
    normalized = f" {str(display_name).upper().strip()} "
    return any(hint in normalized for hint in COMPANY_NAME_HINTS)


def _signed_exposure_usd(
    *,
    quantity: float,
    gross_exposure_usd: float,
    dir_exposure: str,
) -> float:
    quantity_sign = 1.0
    if quantity < 0:
        quantity_sign = -1.0
    dir_sign = -1.0 if dir_exposure.upper() == "S" else 1.0
    return gross_exposure_usd * quantity_sign * dir_sign


def _mapping_status(security: SecurityReference | None) -> str:
    if security is None:
        return "heuristic"
    return security.mapping_status


def _instrument_type(
    *,
    security: SecurityReference | None,
    local_symbol: str,
    exchange: str,
) -> str:
    if security is None:
        return infer_instrument_type(local_symbol, exchange)
    if security.ibkr_sec_type in {"OPT", "FOP"}:
        return "Option"
    if security.mapping_status == "outside_scope":
        return "Option" if _looks_like_option(local_symbol) else "Outside Scope"
    if security.ibkr_sec_type == "FUT":
        return "Futures"
    if security.ibkr_sec_type == "CASH":
        return "Cash"
    if security.asset_class == "EQ":
        return "EQ"
    return "ETF"


def _multiplier(
    *,
    security: SecurityReference | None,
    quantity: float,
    latest_price: float,
    market_value: float,
    local_symbol: str,
    mapping_status: str,
) -> float:
    if security is not None and mapping_status == "mapped" and security.multiplier not in (None, 0):
        return float(security.multiplier)
    return infer_multiplier(
        quantity=quantity,
        latest_price=latest_price,
        market_value=market_value,
        local_symbol=local_symbol,
    )


def _resolve_fi_10y_eq_mod_duration(value: float = DEFAULT_FI_10Y_EQ_MOD_DURATION) -> float:
    value = float(value)
    if value <= 0:
        raise ValueError("FI_10Y_EQ_MOD_DURATION must be positive")
    return value


def _fi_10y_equivalent_exposure_values(
    *,
    gross_exposure_usd: float,
    signed_exposure_usd: float,
    duration: float,
    fi_10y_eq_mod_duration: float,
) -> tuple[float, float]:
    if fi_10y_eq_mod_duration <= 0:
        raise ValueError("fi_10y_eq_mod_duration must be positive")
    scale = float(duration) / fi_10y_eq_mod_duration
    return gross_exposure_usd * scale, signed_exposure_usd * scale


def _display_exposure_values(
    *,
    asset_class: str,
    gross_exposure_usd: float,
    signed_exposure_usd: float,
    duration: float | None,
    fi_10y_eq_mod_duration: float,
) -> tuple[float, float]:
    if asset_class.upper() != "FI" or duration is None or duration <= 0:
        return gross_exposure_usd, signed_exposure_usd
    return _fi_10y_equivalent_exposure_values(
        gross_exposure_usd=gross_exposure_usd,
        signed_exposure_usd=signed_exposure_usd,
        duration=duration,
        fi_10y_eq_mod_duration=fi_10y_eq_mod_duration,
    )


def _funded_aum(rows: list[RiskInputRow]) -> float:
    return _funded_aum_from_dicts(
        [
            {
                "instrument_type": row.instrument_type,
                "gross_exposure_usd": row.gross_exposure_usd,
                "weight": row.weight,
            }
            for row in rows
        ]
    )


def _funded_aum_dual(
    rows: list[RiskInputRow],
    *,
    usdsgd_rate: float | None,
) -> tuple[float, float | None]:
    if usdsgd_rate in (None, 0.0):
        return _funded_aum(rows), None
    return _funded_aum_dual_from_dicts(
        [
            {
                "instrument_type": row.instrument_type,
                "gross_exposure_usd": row.gross_exposure_usd,
                "weight": row.weight,
                "currency": row.currency,
            }
            for row in rows
        ],
        usdsgd_rate=float(usdsgd_rate),
    )


def _funded_aum_from_dicts(rows: list[dict[str, object]]) -> float:
    funded_instruments = [
        float(row.get("gross_exposure_usd") or 0.0)
        for row in rows
        if _counts_toward_funded_aum(str(row.get("instrument_type") or ""))
    ]
    funded = sum(funded_instruments)
    if funded > 0:
        return funded
    fallback = sum(float(row.get("weight") or 0.0) for row in rows)
    if fallback > 0:
        return fallback
    return sum(abs(value) for value in funded_instruments)


def _funded_aum_dual_from_dicts(
    rows: list[dict[str, object]],
    *,
    usdsgd_rate: float,
) -> tuple[float, float]:
    funded_rows = [row for row in rows if _counts_toward_funded_aum(str(row.get("instrument_type") or ""))]
    if not funded_rows:
        fallback = sum(float(row.get("weight") or 0.0) for row in rows)
        return fallback, fallback * usdsgd_rate

    funded_usd = 0.0
    funded_sgd = 0.0
    for row in funded_rows:
        amount = float(row.get("gross_exposure_usd") or 0.0)
        currency = str(row.get("currency") or "USD").strip().upper() or "USD"
        funded_usd += _convert_summary_amount(amount=amount, currency=currency, target_currency="USD", usdsgd_rate=usdsgd_rate)
        funded_sgd += _convert_summary_amount(amount=amount, currency=currency, target_currency="SGD", usdsgd_rate=usdsgd_rate)
    return funded_usd, funded_sgd


def _convert_summary_amount(
    *,
    amount: float,
    currency: str,
    target_currency: str,
    usdsgd_rate: float,
) -> float:
    normalized_currency = str(currency).strip().upper() or "USD"
    normalized_target = str(target_currency).strip().upper()
    if normalized_currency == normalized_target:
        return amount
    if normalized_target == "USD" and normalized_currency == "SGD":
        return amount / usdsgd_rate
    if normalized_target == "SGD" and normalized_currency != "SGD":
        return amount * usdsgd_rate
    return amount


def _counts_toward_funded_aum(instrument_type: str) -> bool:
    normalized = instrument_type.strip().upper()
    return normalized in {"EQ", "ETF", "CASH"}


def _looks_like_option(local_symbol: str) -> bool:
    return bool(OPTION_LOCAL_SYMBOL_RE.search(local_symbol))


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _coerce_return_series(returns: pd.Series | list[float]) -> pd.Series:
    if isinstance(returns, pd.Series):
        return pd.to_numeric(returns, errors="coerce")
    parsed = [float(value) for value in returns]
    start = -len(parsed)
    return pd.Series(parsed, index=pd.RangeIndex(start=start, stop=0), dtype=float)


def _has_usable_returns(returns: pd.Series | list[float] | None) -> bool:
    if returns is None:
        return False
    return not _coerce_return_series(returns).dropna().empty


def _merged_proxy_default_levels(default_levels: Mapping[str, float] | None) -> dict[str, float]:
    merged = dict(DEFAULT_PROXY_LEVELS)
    if default_levels is None:
        return merged
    for raw_key, raw_value in default_levels.items():
        key = str(raw_key).strip().upper()
        if key not in merged:
            continue
        merged[key] = float(raw_value)
    return merged


def _merged_proxy_yahoo_symbols(yahoo_symbols: Mapping[str, str] | None) -> dict[str, str]:
    merged = dict(DEFAULT_PROXY_YAHOO_SYMBOLS)
    if yahoo_symbols is None:
        return merged
    for raw_key, raw_value in yahoo_symbols.items():
        key = str(raw_key).strip().upper()
        if key not in merged:
            continue
        symbol = str(raw_value).strip()
        if symbol:
            merged[key] = symbol
    return merged


def _load_returns(path: str | Path) -> dict[str, pd.Series]:
    return load_internal_id_return_series_override(path)


def _load_proxy(
    path: str | Path | None,
    *,
    yahoo_client: YahooFinanceClient,
    fallback_payload: Mapping[str, Any] | None = None,
    default_levels: Mapping[str, float] | None = None,
    yahoo_symbols: Mapping[str, str] | None = None,
    yahoo_period: str = DEFAULT_PROXY_YAHOO_PERIOD,
    yahoo_interval: str = DEFAULT_PROXY_YAHOO_INTERVAL,
    progress: ProgressReporter | None = None,
) -> dict[str, float]:
    resolved_defaults = _merged_proxy_default_levels(default_levels)
    if progress is not None:
        progress.spinner("Proxy levels", detail="loading")
    loaded = _load_proxy_payload(path, fallback_payload=fallback_payload)
    _reject_legacy_fixed_income_proxy_keys(loaded, source="proxy")
    proxy, aliases = _parse_proxy_payload(loaded)
    proxy = _populate_proxy_defaults_from_yahoo(
        proxy,
        yahoo_client=yahoo_client,
        default_levels=resolved_defaults,
        yahoo_symbols=yahoo_symbols,
        yahoo_period=yahoo_period,
        yahoo_interval=yahoo_interval,
        progress=progress,
    )
    _resolve_proxy_aliases(proxy, aliases)
    proxy.setdefault("FXVOL", DEFAULT_PROXY_FXVOL)
    proxy.setdefault("DEFAULT", proxy.get("VIX", resolved_defaults["VIX"]))
    if progress is not None:
        progress.done("Proxy levels", detail="ready")
    return proxy


def _load_proxy_payload(
    path: str | Path | None,
    *,
    fallback_payload: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    if path is None:
        return dict(fallback_payload or {})
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Expected proxy JSON object, e.g. {'VIX': 19.2}")
    return loaded


def _is_eq_country_other_bucket(bucket: str) -> bool:
    normalized_bucket = str(bucket).upper()
    if normalized_bucket in EQ_COUNTRY_OTHER_BUCKETS:
        return True
    if normalized_bucket.endswith("-OTHER") or normalized_bucket.endswith("-OTHERS"):
        return True
    return False


def _parse_proxy_payload(loaded: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, str]]:
    proxy: dict[str, float] = {}
    aliases: dict[str, str] = {}
    for raw_key, raw_value in loaded.items():
        key = str(raw_key).strip().upper()
        if not key:
            continue
        if isinstance(raw_value, (int, float)):
            proxy[key] = float(raw_value)
            continue
        if not isinstance(raw_value, str):
            continue
        stripped = raw_value.strip()
        if not stripped:
            continue
        try:
            proxy[key] = float(stripped)
        except ValueError:
            aliases[key] = stripped.upper()
    return proxy, aliases


def _populate_proxy_defaults_from_yahoo(
    proxy: Mapping[str, float],
    *,
    yahoo_client: YahooFinanceClient,
    default_levels: Mapping[str, float] | None = None,
    yahoo_symbols: Mapping[str, str] | None = None,
    yahoo_period: str = DEFAULT_PROXY_YAHOO_PERIOD,
    yahoo_interval: str = DEFAULT_PROXY_YAHOO_INTERVAL,
    progress: ProgressReporter | None = None,
) -> dict[str, float]:
    resolved_defaults = _merged_proxy_default_levels(default_levels)
    resolved = dict(proxy)
    missing_keys = [key for key in resolved_defaults if key not in resolved]
    completed = 0
    if progress is not None and missing_keys:
        progress.stage("Proxy Yahoo", current=0, total=len(missing_keys))
    for key, fallback in resolved_defaults.items():
        if key in resolved:
            continue
        try:
            resolved[key] = _fetch_proxy_level_from_yahoo(
                key,
                yahoo_client=yahoo_client,
                yahoo_symbols=yahoo_symbols,
                yahoo_period=yahoo_period,
                yahoo_interval=yahoo_interval,
            )
            detail = f"{key} fetched"
        except (RuntimeError, ValueError):
            resolved[key] = fallback
            detail = f"{key} default"
        if progress is not None:
            completed += 1
            progress.update("Proxy Yahoo", completed=completed, total=len(missing_keys), detail=detail)
    resolved.setdefault("FXVOL", DEFAULT_PROXY_FXVOL)
    resolved.setdefault("DEFAULT", resolved.get("VIX", resolved_defaults["VIX"]))
    return resolved


def _resolve_proxy_aliases(proxy: dict[str, float], aliases: Mapping[str, str]) -> None:
    pending = dict(aliases)
    while pending:
        progressed = False
        for key, alias in list(pending.items()):
            if alias not in proxy:
                continue
            proxy[key] = float(proxy[alias])
            del pending[key]
            progressed = True
        if progressed:
            continue
        unresolved = ", ".join(f"{key}->{alias}" for key, alias in sorted(pending.items()))
        raise ValueError(f"Unresolved proxy aliases: {unresolved}")


def _fetch_proxy_level_from_yahoo(
    key: str,
    *,
    yahoo_client: YahooFinanceClient,
    yahoo_symbols: Mapping[str, str] | None = None,
    yahoo_period: str = DEFAULT_PROXY_YAHOO_PERIOD,
    yahoo_interval: str = DEFAULT_PROXY_YAHOO_INTERVAL,
) -> float:
    resolved_symbols = _merged_proxy_yahoo_symbols(yahoo_symbols)
    yahoo_symbol = resolved_symbols[key]
    cached = _YAHOO_PROXY_LEVEL_CACHE.get(yahoo_symbol)
    if cached is not None:
        return cached
    history = yahoo_client.fetch_price_history(
        yahoo_symbol,
        period=yahoo_period,
        interval=yahoo_interval,
    )
    level = _latest_yahoo_history_level(history)
    _YAHOO_PROXY_LEVEL_CACHE[yahoo_symbol] = level
    return level


def _latest_yahoo_history_level(history: Mapping[str, Any]) -> float:
    prices = history.get("prices") if isinstance(history, Mapping) else None
    if not isinstance(prices, list) or not prices:
        raise ValueError("Yahoo proxy history returned no prices")
    last_row = prices[-1]
    if not isinstance(last_row, Mapping):
        raise ValueError("Yahoo proxy history returned an invalid price row")
    value = last_row.get("adjclose")
    if value in (None, ""):
        value = last_row.get("close")
    if value in (None, ""):
        raise ValueError("Yahoo proxy history returned no usable latest price")
    return float(value)


def _resolve_usdsgd_rate(
    *,
    yahoo_client: YahooFinanceClient,
    progress: ProgressReporter | None = None,
) -> float | None:
    cached = _YAHOO_FX_RATE_CACHE.get(DEFAULT_USDSGD_YAHOO_SYMBOL)
    if cached is not None:
        if progress is not None:
            progress.done("USD/SGD", detail="cached")
        return cached
    try:
        if progress is not None:
            progress.spinner("USD/SGD", detail="fetching USDSGD=X")
        rate = _fetch_symbol_level_from_yahoo(
            DEFAULT_USDSGD_YAHOO_SYMBOL,
            yahoo_client=yahoo_client,
        )
    except (RuntimeError, ValueError):
        try:
            if progress is not None:
                progress.spinner("USD/SGD", detail="fetching SGDUSD=X")
            inverse_rate = _fetch_symbol_level_from_yahoo(
                DEFAULT_SGDUSD_YAHOO_SYMBOL,
                yahoo_client=yahoo_client,
            )
        except (RuntimeError, ValueError):
            if progress is not None:
                progress.done("USD/SGD", detail="unavailable")
            return None
        if inverse_rate <= 0:
            if progress is not None:
                progress.done("USD/SGD", detail="invalid inverse rate")
            return None
        rate = 1.0 / inverse_rate
    _YAHOO_FX_RATE_CACHE[DEFAULT_USDSGD_YAHOO_SYMBOL] = rate
    if progress is not None:
        progress.done("USD/SGD", detail=f"{rate:.4f}")
    return rate


def _fetch_symbol_level_from_yahoo(
    symbol: str,
    *,
    yahoo_client: YahooFinanceClient,
    period: str = DEFAULT_PROXY_YAHOO_PERIOD,
    interval: str = DEFAULT_PROXY_YAHOO_INTERVAL,
) -> float:
    history = yahoo_client.fetch_price_history(symbol, period=period, interval=interval)
    return _latest_yahoo_history_level(history)


def _load_regime_summary(path: str | Path | None) -> RegimeReportSummary | None:
    if path is None:
        return None
    loaded: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not loaded:
        return None
    row = loaded[-1]
    if not isinstance(row, dict):
        return None
    scores = row.get("scores") if isinstance(row.get("scores"), dict) else {}
    return RegimeReportSummary(
        as_of=str(row.get("as_of") or ""),
        regime=str(row.get("regime") or "Unknown"),
        scores={str(k): float(v) for k, v in scores.items()},
    )


def _load_security_reference_table(path: str | Path | None) -> SecurityReferenceTable:
    reference_path = path or DEFAULT_SECURITY_REFERENCE_PATH
    try:
        return SecurityReferenceTable.from_csv(reference_path)
    except FileNotFoundError:
        return build_security_reference_table(reference_path=reference_path)
