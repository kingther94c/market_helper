from __future__ import annotations

"""HTML risk-report builder for the universe-first portfolio monitor flow."""

import csv
import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import stdev
from typing import Any, Iterable, Mapping

from market_helper.data_sources.yahoo_finance import YahooFinanceClient
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
DEFAULT_EQ_COUNTRY_LOOKTHROUGH_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "portfolio_monitor" / "eq_country_lookthrough.csv"
)
DEFAULT_US_SECTOR_LOOKTHROUGH_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "portfolio_monitor" / "us_sector_lookthrough.csv"
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
    duration: float | None
    expected_vol: float | None
    local_symbol: str
    exchange: str
    mapping_status: str
    dir_exposure: str
    eq_country: str
    eq_sector: str
    fi_tenor: str
    yahoo_symbol: str


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
    historical_vol: float
    estimated_vol: float
    risk_contribution_historical: float
    risk_contribution_estimated: float
    mapping_status: str
    dir_exposure: str
    eq_country: str
    eq_sector: str
    fi_tenor: str


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
    parent: str
    exposure_usd: float
    gross_exposure_usd: float
    dollar_weight: float
    risk_contribution_estimated: float


@dataclass(frozen=True)
class PortfolioRiskSummary:
    historical_vol: float
    estimated_vol: float
    funded_aum: float
    gross_exposure: float
    net_exposure: float
    mapped_positions: int
    total_positions: int


@dataclass(frozen=True)
class RegimeReportSummary:
    as_of: str
    regime: str
    scores: dict[str, float]


def build_risk_html_report(
    *,
    positions_csv_path: str | Path,
    output_path: str | Path,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
    yahoo_client: YahooFinanceClient | None = None,
    vol_method: str = "geomean_1m_3m",
    inter_asset_corr: str = "historical",
) -> Path:
    reference_table = _load_security_reference_table(security_reference_path)
    rows = load_position_rows(positions_csv_path, security_reference_table=reference_table)
    proxy = _load_proxy(proxy_path)
    returns = _load_or_build_returns(
        returns_path=returns_path,
        rows=rows,
        yahoo_client=yahoo_client or YahooFinanceClient(),
    )
    regime_summary = _load_regime_summary(regime_path)

    historical_vols = {
        row.internal_id: _security_vol(
            returns=returns.get(row.internal_id, []),
            asset_class=row.asset_class,
            proxy=proxy,
            method="geomean_1m_3m",
        )
        for row in rows
    }
    estimated_vols = {
        row.internal_id: _security_vol(
            returns=returns.get(row.internal_id, []),
            asset_class=row.asset_class,
            proxy=proxy,
            method=vol_method,
        )
        for row in rows
    }

    historical_group_loadings = _build_group_loadings(rows, historical_vols)
    estimated_group_loadings = _build_group_loadings(rows, estimated_vols)
    group_returns = _build_group_returns(rows, returns)
    historical_group_corr = _build_group_correlation(
        asset_classes=historical_group_loadings.keys(),
        group_returns=group_returns,
        mode="historical",
    )
    estimated_group_corr = _build_group_correlation(
        asset_classes=estimated_group_loadings.keys(),
        group_returns=group_returns,
        mode=inter_asset_corr,
    )
    portfolio_hist_vol = _portfolio_vol_from_group_loadings(historical_group_loadings, historical_group_corr)
    portfolio_est_vol = _portfolio_vol_from_group_loadings(estimated_group_loadings, estimated_group_corr)

    security_hist_loadings = _build_security_loadings(rows, historical_vols)
    security_est_loadings = _build_security_loadings(rows, estimated_vols)
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
            exposure_usd=row.signed_exposure_usd,
            gross_exposure_usd=row.gross_exposure_usd,
            weight=row.weight,
            dollar_weight=row.dollar_weight,
            duration=row.duration,
            historical_vol=historical_vols[row.internal_id],
            estimated_vol=estimated_vols[row.internal_id],
            risk_contribution_historical=abs(security_hist_loadings[row.internal_id]),
            risk_contribution_estimated=abs(security_est_loadings[row.internal_id]),
            mapping_status=row.mapping_status,
            dir_exposure=row.dir_exposure,
            eq_country=row.eq_country,
            eq_sector=row.eq_sector,
            fi_tenor=row.fi_tenor,
        )
        for row in rows
    ]
    allocation_summary = build_allocation_summary(risk_rows)
    country_breakdown = _build_eq_country_breakdown(rows, security_est_loadings)
    sector_breakdown = _build_us_sector_breakdown(rows, security_est_loadings)
    fi_tenor_breakdown = _build_fi_tenor_breakdown(rows, security_est_loadings)
    summary = PortfolioRiskSummary(
        historical_vol=portfolio_hist_vol,
        estimated_vol=portfolio_est_vol,
        funded_aum=_funded_aum(rows),
        gross_exposure=sum(row.gross_exposure_usd for row in rows),
        net_exposure=sum(row.signed_exposure_usd for row in rows),
        mapped_positions=sum(1 for row in rows if row.mapping_status == "mapped"),
        total_positions=len(rows),
    )

    rendered = render_html(
        risk_rows=risk_rows,
        summary=summary,
        allocation_summary=allocation_summary,
        country_breakdown=country_breakdown,
        sector_breakdown=sector_breakdown,
        fi_tenor_breakdown=fi_tenor_breakdown,
        regime_summary=regime_summary,
        vol_method=vol_method,
        inter_asset_corr=inter_asset_corr,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return output


def load_position_rows(
    path: str | Path,
    *,
    security_reference_table: SecurityReferenceTable | None = None,
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
            eq_sector = security.eq_sector
            dir_exposure = security.dir_exposure or "L"
            fi_tenor = security.fi_tenor
            yahoo_symbol = security.yahoo_symbol
            canonical_symbol = security.canonical_symbol or symbol
        elif security is not None and security.mapping_status == "outside_scope":
            asset_class = "OUTSIDE_SCOPE"
            display_ticker = security.display_ticker or infer_display_ticker(symbol, exchange, local_symbol)
            display_name = security.display_name or infer_display_name(symbol, local_symbol, instrument_type)
            duration = None
            eq_country = ""
            eq_sector = ""
            dir_exposure = "L"
            fi_tenor = ""
            yahoo_symbol = ""
            canonical_symbol = security.canonical_symbol or symbol
        else:
            asset_class = infer_asset_class(symbol, exchange)
            display_ticker = infer_display_ticker(symbol, exchange, local_symbol)
            display_name = infer_display_name(symbol, local_symbol, instrument_type)
            duration = None
            eq_country = ""
            eq_sector = ""
            dir_exposure = "L"
            fi_tenor = ""
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
                "eq_sector": eq_sector,
                "fi_tenor": fi_tenor,
                "yahoo_symbol": yahoo_symbol,
            }
        )

    funded_aum = _funded_aum_from_dicts(parsed_rows)
    return [
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
            duration=_optional_float(row.get("duration")),
            expected_vol=None,
            local_symbol=str(row["local_symbol"]),
            exchange=str(row["exchange"]),
            mapping_status=str(row["mapping_status"]),
            dir_exposure=str(row["dir_exposure"]),
            eq_country=str(row["eq_country"]),
            eq_sector=str(row["eq_sector"]),
            fi_tenor=str(row["fi_tenor"]),
            yahoo_symbol=str(row["yahoo_symbol"]),
        )
        for row in parsed_rows
    ]


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


def historical_geomean_vol(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    v1 = annualized_vol(returns[-HIST_1M_DAYS:])
    v3 = annualized_vol(returns[-HIST_3M_DAYS:])
    if v1 <= 0 or v3 <= 0:
        return max(v1, v3)
    return math.sqrt(v1 * v3)


def annualized_vol(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    return stdev(returns) * math.sqrt(TRADING_DAYS)


def ewma_vol(returns: list[float], *, decay: float = 0.94) -> float:
    if len(returns) < 2:
        return 0.0
    variance = returns[0] ** 2
    for value in returns[1:]:
        variance = decay * variance + (1.0 - decay) * (value ** 2)
    return math.sqrt(max(variance, 0.0)) * math.sqrt(TRADING_DAYS)


def estimated_asset_class_vol(asset_class: str, proxy: Mapping[str, float]) -> float:
    name = asset_class.upper()
    if name == "EQ":
        return proxy.get("VIX", 18.0) / 100.0
    if name == "FI":
        return proxy.get("MOVE", 110.0) / 100.0
    if name == "CM":
        return proxy.get("OVX", proxy.get("GVZ", 25.0)) / 100.0
    if name == "CASH":
        return 0.01
    if name == "FX":
        return proxy.get("FXVOL", proxy.get("DEFAULT", 12.0)) / 100.0
    if name == "MACRO":
        return proxy.get("DEFAULT", 20.0) / 100.0
    return proxy.get("DEFAULT", 20.0) / 100.0


def build_historical_correlation(
    rows: list[RiskInputRow],
    returns: Mapping[str, list[float]],
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
    n = min(len(left), len(right))
    if n < 2:
        return 0.0
    x = left[-n:]
    y = right[-n:]
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / (n - 1)
    sx = stdev(x)
    sy = stdev(y)
    if sx == 0 or sy == 0:
        return 0.0
    value = cov / (sx * sy)
    return max(-1.0, min(1.0, value))


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
    return sorted(by_bucket.values(), key=lambda item: item.asset_class)


def render_html(
    *,
    risk_rows: list[RiskMetricsRow],
    summary: PortfolioRiskSummary,
    allocation_summary: list[CategorySummaryRow],
    country_breakdown: list[BreakdownRow],
    sector_breakdown: list[BreakdownRow],
    fi_tenor_breakdown: list[BreakdownRow],
    regime_summary: RegimeReportSummary | None,
    vol_method: str,
    inter_asset_corr: str,
) -> str:
    position_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row.account)}</td>"
        f"<td>{html.escape(row.display_ticker)}</td>"
        f"<td>{html.escape(row.display_name)}</td>"
        f"<td>{html.escape(row.asset_class)}</td>"
        f"<td>{html.escape(row.instrument_type)}</td>"
        f"<td class='num'>{row.quantity:,.2f}</td>"
        f"<td class='num'>{row.gross_exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.dollar_weight:.2%}</td>"
        f"<td class='num'>{row.estimated_vol:.2%}</td>"
        f"<td class='num'>{row.risk_contribution_estimated:.2%}</td>"
        f"<td class='num'>{row.historical_vol:.2%}</td>"
        f"<td>{html.escape(row.mapping_status)}</td>"
        "</tr>"
        for row in risk_rows
    )
    allocation_rows = _render_breakdown_rows(
        [
            BreakdownRow(
                bucket=row.category,
                parent=row.asset_class,
                exposure_usd=row.exposure_usd,
                gross_exposure_usd=row.gross_exposure_usd,
                dollar_weight=row.dollar_weight,
                risk_contribution_estimated=row.risk_contribution_estimated,
            )
            for row in allocation_summary
        ]
    )
    country_rows = _render_breakdown_rows(country_breakdown)
    sector_rows = _render_breakdown_rows(sector_breakdown)
    tenor_rows = _render_breakdown_rows(fi_tenor_breakdown)

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
  </style>
</head>
<body>
  <h1>Portfolio Risk Report</h1>
  {regime_block}

  <div class='card'>
    <h2>Portfolio Summary</h2>
    <div class='metrics'>
      <div class='metric'><span>Historical portfolio vol (1M/3M geomean, historical corr)</span><strong>{summary.historical_vol:.2%}</strong></div>
      <div class='metric'><span>Selected portfolio vol ({html.escape(vol_method)}, {html.escape(inter_asset_corr)})</span><strong>{summary.estimated_vol:.2%}</strong></div>
      <div class='metric'><span>Funded AUM</span><strong>{summary.funded_aum:,.0f}</strong></div>
      <div class='metric'><span>Gross exposure</span><strong>{summary.gross_exposure:,.0f}</strong></div>
      <div class='metric'><span>Net exposure</span><strong>{summary.net_exposure:,.0f}</strong></div>
      <div class='metric'><span>Mapping coverage</span><strong>{summary.mapped_positions}/{summary.total_positions}</strong></div>
    </div>
  </div>

  <div class='card'>
    <h2>Asset Class Summary</h2>
    <table>
      <thead><tr><th>Asset Class</th><th class='num'>Net Exposure</th><th class='num'>Gross Exposure</th><th class='num'>Dollar%</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{allocation_rows}</tbody>
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
    <h2>US Sector Breakdown</h2>
    <table>
      <thead><tr><th>Sector</th><th>Scope</th><th class='num'>Net Exposure</th><th class='num'>Gross Exposure</th><th class='num'>Dollar%</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{sector_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>FI Tenor Breakdown</h2>
    <table>
      <thead><tr><th>Tenor</th><th>Scope</th><th class='num'>Net Exposure</th><th class='num'>Gross Exposure</th><th class='num'>Dollar%</th><th class='num'>Vol Contribution</th></tr></thead>
      <tbody>{tenor_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>Position Risk Decomposition</h2>
    <table>
      <thead>
        <tr>
          <th>Account</th><th>Ticker</th><th>Name</th><th>Asset Class</th><th>Type</th>
          <th class='num'>Qty</th><th class='num'>Gross Exposure</th><th class='num'>Net Exposure</th>
          <th class='num'>Dollar%</th><th class='num'>Est Vol</th><th class='num'>Vol Contribution</th>
          <th class='num'>Hist Vol</th><th>Mapping</th>
        </tr>
      </thead>
      <tbody>{position_rows}</tbody>
    </table>
  </div>
</body>
</html>
"""


def _render_breakdown_rows(rows: Iterable[BreakdownRow]) -> str:
    materialized = list(rows)
    if not materialized:
        return "<tr><td colspan='6'>No data</td></tr>"
    return "\n".join(
        "<tr>"
        f"<td>{html.escape(row.bucket)}</td>"
        f"<td>{html.escape(row.parent)}</td>"
        f"<td class='num'>{row.exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.gross_exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.dollar_weight:.2%}</td>"
        f"<td class='num'>{row.risk_contribution_estimated:.2%}</td>"
        "</tr>"
        for row in materialized
    )


def _load_or_build_returns(
    *,
    returns_path: str | Path | None,
    rows: list[RiskInputRow],
    yahoo_client: YahooFinanceClient,
) -> dict[str, list[float]]:
    if returns_path is not None:
        return _load_returns(returns_path)
    return _build_returns_from_yahoo(rows=rows, yahoo_client=yahoo_client)


def _build_returns_from_yahoo(
    *,
    rows: list[RiskInputRow],
    yahoo_client: YahooFinanceClient,
) -> dict[str, list[float]]:
    built: dict[str, list[float]] = {}
    for row in rows:
        if row.internal_id in built:
            continue
        if row.mapping_status != "mapped" or row.asset_class == "CASH":
            continue
        if not row.yahoo_symbol:
            raise ValueError(f"Missing yahoo_symbol for mapped security {row.internal_id}")
        history = yahoo_client.fetch_price_history(row.yahoo_symbol, period="5y")
        built[row.internal_id] = _returns_from_price_history(history)
        if not built[row.internal_id]:
            raise ValueError(f"Yahoo history returned no usable returns for {row.internal_id}")
    return built


def _returns_from_price_history(history: Mapping[str, Any]) -> list[float]:
    prices = history.get("prices") if isinstance(history, Mapping) else None
    if not isinstance(prices, list):
        return []
    series: list[float] = []
    prior: float | None = None
    for row in prices:
        if not isinstance(row, Mapping):
            continue
        value = row.get("adjclose", row.get("close"))
        if value in (None, "", 0):
            continue
        price = float(value)
        if prior not in (None, 0):
            series.append((price / prior) - 1.0)
        prior = price
    return series


def _security_vol(
    *,
    returns: list[float],
    asset_class: str,
    proxy: Mapping[str, float],
    method: str,
) -> float:
    if returns:
        normalized = method.strip().lower()
        if normalized == "5y_realized":
            return annualized_vol(returns)
        if normalized == "ewma":
            return ewma_vol(returns)
        return historical_geomean_vol(returns)
    return estimated_asset_class_vol(asset_class, proxy)


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
    returns: Mapping[str, list[float]],
) -> dict[str, list[float]]:
    grouped: dict[str, list[RiskInputRow]] = {}
    for row in rows:
        grouped.setdefault(row.asset_class, []).append(row)

    series: dict[str, list[float]] = {}
    for asset_class, group_rows in grouped.items():
        candidates = [row for row in group_rows if returns.get(row.internal_id)]
        if not candidates:
            series[asset_class] = []
            continue
        n = min(len(returns[row.internal_id]) for row in candidates)
        if n < 2:
            series[asset_class] = []
            continue
        denominator = sum(abs(row.signed_exposure_usd) for row in candidates) or 1.0
        materialized: list[float] = []
        for idx in range(-n, 0):
            materialized.append(
                sum(
                    (row.signed_exposure_usd / denominator) * returns[row.internal_id][idx]
                    for row in candidates
                )
            )
        series[asset_class] = materialized
    return series


def _build_group_correlation(
    *,
    asset_classes: Iterable[str],
    group_returns: Mapping[str, list[float]],
    mode: str,
) -> dict[tuple[str, str], float]:
    normalized_mode = mode.strip().lower()
    keys = sorted(set(asset_classes))
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
            corr[(left, right)] = pairwise_corr(group_returns.get(left, []), group_returns.get(right, []))
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


def _build_eq_country_breakdown(
    rows: list[RiskInputRow],
    estimated_loadings: Mapping[str, float],
) -> list[BreakdownRow]:
    lookthrough = _load_weight_table(DEFAULT_EQ_COUNTRY_LOOKTHROUGH_PATH, "eq_country", "country_bucket")
    return _build_breakdown(
        rows=rows,
        estimated_loadings=estimated_loadings,
        expander=lambda row: _expand_country_allocations(row, lookthrough),
        parent="EQ",
    )


def _build_us_sector_breakdown(
    rows: list[RiskInputRow],
    estimated_loadings: Mapping[str, float],
) -> list[BreakdownRow]:
    lookthrough = _load_weight_table(DEFAULT_US_SECTOR_LOOKTHROUGH_PATH, "canonical_symbol", "sector")
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
    return _build_breakdown(
        rows=rows,
        estimated_loadings=estimated_loadings,
        expander=lambda row: [(row.fi_tenor or "UNASSIGNED", 1.0)] if row.asset_class == "FI" else [],
        parent="FI",
    )


def _build_breakdown(
    *,
    rows: list[RiskInputRow],
    estimated_loadings: Mapping[str, float],
    expander: Any,
    parent: str,
) -> list[BreakdownRow]:
    aggregated: dict[str, BreakdownRow] = {}
    funded_aum = _funded_aum(rows)
    for row in rows:
        for bucket, weight in expander(row):
            existing = aggregated.get(bucket)
            net_exposure = row.signed_exposure_usd * weight
            gross_exposure = row.gross_exposure_usd * weight
            contribution = abs(estimated_loadings.get(row.internal_id, 0.0) * weight)
            if existing is None:
                aggregated[bucket] = BreakdownRow(
                    bucket=bucket,
                    parent=parent,
                    exposure_usd=net_exposure,
                    gross_exposure_usd=gross_exposure,
                    dollar_weight=(gross_exposure / funded_aum) if funded_aum > 0 else 0.0,
                    risk_contribution_estimated=contribution,
                )
                continue
            aggregated[bucket] = BreakdownRow(
                bucket=existing.bucket,
                parent=existing.parent,
                exposure_usd=existing.exposure_usd + net_exposure,
                gross_exposure_usd=existing.gross_exposure_usd + gross_exposure,
                dollar_weight=((existing.gross_exposure_usd + gross_exposure) / funded_aum) if funded_aum > 0 else 0.0,
                risk_contribution_estimated=existing.risk_contribution_estimated + contribution,
            )
    return sorted(aggregated.values(), key=lambda item: item.gross_exposure_usd, reverse=True)


def _expand_country_allocations(
    row: RiskInputRow,
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> list[tuple[str, float]]:
    if row.asset_class != "EQ":
        return []
    if row.eq_country in lookthrough:
        return lookthrough[row.eq_country]
    if row.eq_country:
        return [(row.eq_country, 1.0)]
    return [("OTHER", 1.0)]


def _expand_us_sector_allocations(
    row: RiskInputRow,
    lookthrough: Mapping[str, list[tuple[str, float]]],
) -> list[tuple[str, float]]:
    if row.asset_class != "EQ":
        return []
    if row.eq_sector and row.eq_country == "US":
        return [(row.eq_sector, 1.0)]
    if row.canonical_symbol in lookthrough:
        return lookthrough[row.canonical_symbol]
    return []


def _load_weight_table(
    path: Path,
    key_column: str,
    bucket_column: str,
) -> dict[str, list[tuple[str, float]]]:
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


def _funded_aum_from_dicts(rows: list[dict[str, object]]) -> float:
    non_futures = [
        float(row.get("gross_exposure_usd") or 0.0)
        for row in rows
        if str(row.get("instrument_type") or "").upper() != "FUTURES"
    ]
    funded = sum(non_futures)
    if funded > 0:
        return funded
    fallback = sum(float(row.get("weight") or 0.0) for row in rows)
    if fallback > 0:
        return fallback
    return sum(abs(value) for value in non_futures)


def _looks_like_option(local_symbol: str) -> bool:
    return bool(OPTION_LOCAL_SYMBOL_RE.search(local_symbol))


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _load_returns(path: str | Path) -> dict[str, list[float]]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Expected returns JSON object: {internal_id: [daily_returns...]}")
    return {str(k): [float(v) for v in values] for k, values in loaded.items() if isinstance(values, list)}


def _load_proxy(path: str | Path | None) -> dict[str, float]:
    if path is None:
        return {}
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Expected proxy JSON object, e.g. {'VIX': 19.2}")
    return {str(k).upper(): float(v) for k, v in loaded.items() if isinstance(v, (int, float, str))}


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
