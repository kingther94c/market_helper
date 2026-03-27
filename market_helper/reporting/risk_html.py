from __future__ import annotations

import csv
import html
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import stdev
from typing import Any, Mapping

from market_helper.regimes.taxonomy import REGIME_INTERPRETATIONS

from .mapping_table import (
    ReportMappingTable,
    build_instrument_mapping_indexes,
    load_report_mapping_table,
    normalize_mapping_symbol,
    normalize_mapping_venue,
    risk_bucket_for_category,
)


TRADING_DAYS = 252
HIST_1M_DAYS = 21
HIST_3M_DAYS = 63
FUTURES_VENUES = {"CBOT", "CME", "COMEX", "ICE", "NYMEX"}
FX_FUTURE_SYMBOLS = {"AUD", "CAD", "CHF", "EUR", "GBP", "JPY", "MXN", "NZD"}
OPTION_LOCAL_SYMBOL_RE = re.compile(r"\s\d{6}[CP]\d+")


@dataclass(frozen=True)
class RiskInputRow:
    internal_id: str
    symbol: str
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
    dollar_weight: float
    duration: float | None
    expected_vol: float | None
    local_symbol: str
    exchange: str
    mapping_status: str


@dataclass(frozen=True)
class RiskMetricsRow:
    internal_id: str
    display_ticker: str
    display_name: str
    symbol: str
    account: str
    asset_class: str
    category: str
    instrument_type: str
    quantity: float
    multiplier: float
    market_value: float
    exposure_usd: float
    weight: float
    dollar_weight: float
    duration: float | None
    fi_10y_equivalent: float | None
    historical_vol: float
    estimated_vol: float
    risk_contribution_historical: float
    risk_contribution_estimated: float
    mapping_status: str


@dataclass(frozen=True)
class CategorySummaryRow:
    category: str
    asset_class: str
    exposure_usd: float
    dollar_weight: float
    risk_contribution_estimated: float
    fi_10y_equivalent: float


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
    returns_path: str | Path,
    output_path: str | Path,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    mapping_table_path: str | Path | None = None,
) -> Path:
    mapping_table = (
        load_report_mapping_table(mapping_table_path) if mapping_table_path is not None else None
    )
    rows = load_position_rows(positions_csv_path, mapping_table=mapping_table)
    returns = _load_returns(returns_path)
    proxy = _load_proxy(proxy_path)
    regime_summary = _load_regime_summary(regime_path)

    historical_vols = {
        row.internal_id: historical_geomean_vol(returns.get(row.internal_id, [])) for row in rows
    }
    estimated_vols = {
        row.internal_id: row.expected_vol
        if row.expected_vol is not None
        else estimated_asset_class_vol(row.asset_class, proxy)
        for row in rows
    }

    historical_corr = build_historical_correlation(rows, returns)
    estimated_corr = build_estimated_correlation(rows)

    portfolio_hist_vol = portfolio_volatility(rows, historical_vols, historical_corr)
    portfolio_est_vol = portfolio_volatility(rows, estimated_vols, estimated_corr)

    ten_year_duration = (
        mapping_table.ten_year_equiv_duration if mapping_table is not None else 7.627
    )
    risk_rows = [
        RiskMetricsRow(
            internal_id=row.internal_id,
            display_ticker=row.display_ticker,
            display_name=row.display_name,
            symbol=row.symbol,
            account=row.account,
            asset_class=row.asset_class,
            category=row.category,
            instrument_type=row.instrument_type,
            quantity=row.quantity,
            multiplier=row.multiplier,
            market_value=row.market_value,
            exposure_usd=row.exposure_usd,
            weight=row.weight,
            dollar_weight=row.dollar_weight,
            duration=row.duration,
            fi_10y_equivalent=_fi_10y_equivalent(
                asset_class=row.asset_class,
                exposure_usd=row.exposure_usd,
                duration=row.duration,
                ten_year_duration=ten_year_duration,
            ),
            historical_vol=historical_vols[row.internal_id],
            estimated_vol=estimated_vols[row.internal_id],
            risk_contribution_historical=row.weight * historical_vols[row.internal_id],
            risk_contribution_estimated=row.dollar_weight * estimated_vols[row.internal_id],
            mapping_status=row.mapping_status,
        )
        for row in rows
    ]
    allocation_summary = build_allocation_summary(risk_rows)
    summary = PortfolioRiskSummary(
        historical_vol=portfolio_hist_vol,
        estimated_vol=portfolio_est_vol,
        funded_aum=_funded_aum(rows),
        gross_exposure=sum(abs(row.exposure_usd) for row in rows),
        net_exposure=sum(row.exposure_usd for row in rows),
        mapped_positions=sum(1 for row in rows if row.mapping_status == "mapped"),
        total_positions=len(rows),
    )

    rendered = render_html(
        risk_rows=risk_rows,
        summary=summary,
        allocation_summary=allocation_summary,
        regime_summary=regime_summary,
        mapping_table=mapping_table,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return output


def load_position_rows(
    path: str | Path,
    *,
    mapping_table: ReportMappingTable | None = None,
) -> list[RiskInputRow]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        loaded = list(reader)

    total_market_value = sum(float(row.get("market_value") or 0.0) for row in loaded)
    mapping_index, unique_mappings = (
        build_instrument_mapping_indexes(mapping_table)
        if mapping_table is not None
        else ({}, {})
    )

    parsed_rows: list[dict[str, object]] = []
    for row in loaded:
        symbol = str(row.get("symbol") or "").upper()
        local_symbol = str(row.get("local_symbol") or "")
        exchange = str(row.get("exchange") or "").upper()
        market_value = float(row.get("market_value") or 0.0)
        latest_price = float(row.get("latest_price") or 0.0)
        quantity = float(row.get("quantity") or 0.0)
        raw_weight = row.get("weight")
        mapping = _resolve_mapping(
            symbol=symbol,
            exchange=exchange,
            local_symbol=local_symbol,
            mapping_index=mapping_index,
            unique_mappings=unique_mappings,
        )

        instrument_type = (
            mapping.instrument_type if mapping is not None else infer_instrument_type(local_symbol, exchange)
        )
        multiplier = (
            mapping.multiplier
            if mapping is not None
            else infer_multiplier(
                quantity=quantity,
                latest_price=latest_price,
                market_value=market_value,
                local_symbol=local_symbol,
            )
        )
        exposure_usd = market_value if market_value != 0.0 else quantity * multiplier * latest_price
        category = mapping.category if mapping is not None else infer_category(symbol, exchange, local_symbol)
        asset_class = mapping.risk_bucket if mapping is not None else risk_bucket_for_category(category)
        display_ticker = (
            mapping.display_ticker
            if mapping is not None
            else infer_display_ticker(symbol, exchange, local_symbol)
        )
        display_name = (
            mapping.display_name
            if mapping is not None
            else infer_display_name(symbol, local_symbol, instrument_type)
        )
        weight = (
            float(raw_weight)
            if raw_weight not in (None, "")
            else (market_value / total_market_value if total_market_value > 0 else 0.0)
        )

        parsed_rows.append(
            {
                "internal_id": str(row.get("internal_id") or ""),
                "symbol": symbol,
                "account": str(row.get("account") or ""),
                "market_value": market_value,
                "weight": weight,
                "asset_class": asset_class,
                "category": category,
                "display_ticker": display_ticker,
                "display_name": display_name,
                "instrument_type": instrument_type,
                "quantity": quantity,
                "latest_price": latest_price,
                "multiplier": multiplier,
                "exposure_usd": exposure_usd,
                "duration": mapping.duration if mapping is not None else None,
                "expected_vol": mapping.expected_vol if mapping is not None else None,
                "local_symbol": local_symbol,
                "exchange": exchange,
                "mapping_status": "mapped" if mapping is not None else "heuristic",
            }
        )

    funded_aum = _funded_aum_from_dicts(parsed_rows)
    return [
        RiskInputRow(
            internal_id=str(row["internal_id"]),
            symbol=str(row["symbol"]),
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
            exposure_usd=float(row["exposure_usd"]),
            dollar_weight=(
                float(row["exposure_usd"]) / funded_aum
                if funded_aum > 0
                else float(row["weight"])
            ),
            duration=_optional_float(row.get("duration")),
            expected_vol=_optional_float(row.get("expected_vol")),
            local_symbol=str(row["local_symbol"]),
            exchange=str(row["exchange"]),
            mapping_status=str(row["mapping_status"]),
        )
        for row in parsed_rows
    ]


def infer_asset_class(symbol: str, exchange: str) -> str:
    upper_symbol = symbol.upper()
    upper_exchange = exchange.upper()

    if upper_exchange in FUTURES_VENUES:
        if upper_symbol.startswith(("ZN", "ZF", "ZT", "TY", "US")):
            return "FI"
        if upper_symbol in FX_FUTURE_SYMBOLS:
            return "MACRO"
        return "CM"
    if upper_symbol in {"GLD", "GDX", "IAU", "SLV", "XAUUSD"}:
        return "GOLD"
    if upper_symbol in {"BIL", "BOXX", "CASH", "SGOV", "SHV"}:
        return "CASH"
    if upper_symbol in {"DBMF"}:
        return "MACRO"
    return "EQ"


def infer_category(symbol: str, exchange: str, local_symbol: str) -> str:
    if infer_instrument_type(local_symbol, exchange) == "Option":
        return "EQ"
    asset_class = infer_asset_class(symbol, exchange)
    if asset_class == "MACRO":
        return "Macro"
    return asset_class


def infer_instrument_type(local_symbol: str, exchange: str) -> str:
    if _looks_like_option(local_symbol):
        return "Option"
    if exchange.upper() in FUTURES_VENUES:
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
    if exchange.upper() in FUTURES_VENUES and local_symbol:
        return f"{local_symbol}:{exchange.upper()}"
    if normalize_mapping_venue(exchange) == "INTL":
        return f"LON:{symbol}"
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


def estimated_asset_class_vol(asset_class: str, proxy: Mapping[str, float]) -> float:
    name = asset_class.upper()
    if name == "EQ":
        return proxy.get("VIX", 18.0) / 100.0
    if name == "FI":
        return proxy.get("MOVE", 110.0) / 100.0
    if name == "GOLD":
        return proxy.get("GVZ", 18.0) / 100.0
    if name == "CM":
        return proxy.get("OVX", 30.0) / 100.0
    if name == "CASH":
        return 0.01
    if name == "MACRO":
        return proxy.get("DEFAULT", 20.0) / 100.0
    return proxy.get("DEFAULT", 20.0) / 100.0


def build_historical_correlation(
    rows: list[RiskInputRow], returns: Mapping[str, list[float]]
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
                corr[key] = 0.75
            elif {left.asset_class, right.asset_class} == {"EQ", "FI"}:
                corr[key] = -0.2
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
        existing = by_bucket.get(row.category)
        if existing is None:
            by_bucket[row.category] = CategorySummaryRow(
                category=row.category,
                asset_class=row.asset_class,
                exposure_usd=row.exposure_usd,
                dollar_weight=row.dollar_weight,
                risk_contribution_estimated=row.risk_contribution_estimated,
                fi_10y_equivalent=row.fi_10y_equivalent or 0.0,
            )
            continue
        by_bucket[row.category] = CategorySummaryRow(
            category=existing.category,
            asset_class=existing.asset_class,
            exposure_usd=existing.exposure_usd + row.exposure_usd,
            dollar_weight=existing.dollar_weight + row.dollar_weight,
            risk_contribution_estimated=(
                existing.risk_contribution_estimated + row.risk_contribution_estimated
            ),
            fi_10y_equivalent=existing.fi_10y_equivalent + (row.fi_10y_equivalent or 0.0),
        )

    return sorted(by_bucket.values(), key=lambda item: (item.asset_class, item.category))


def render_html(
    *,
    risk_rows: list[RiskMetricsRow],
    summary: PortfolioRiskSummary,
    allocation_summary: list[CategorySummaryRow],
    regime_summary: RegimeReportSummary | None,
    mapping_table: ReportMappingTable | None,
) -> str:
    position_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row.account)}</td>"
        f"<td>{html.escape(row.display_ticker)}</td>"
        f"<td>{html.escape(row.display_name)}</td>"
        f"<td>{html.escape(row.category)}</td>"
        f"<td>{html.escape(row.instrument_type)}</td>"
        f"<td class='num'>{row.quantity:,.2f}</td>"
        f"<td class='num'>{row.multiplier:,.2f}</td>"
        f"<td class='num'>{row.exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.dollar_weight:.2%}</td>"
        f"<td class='num'>{row.estimated_vol:.2%}</td>"
        f"<td class='num'>{row.risk_contribution_estimated:.2%}</td>"
        f"<td class='num'>{row.historical_vol:.2%}</td>"
        f"<td>{html.escape(row.mapping_status)}</td>"
        "</tr>"
        for row in risk_rows
    )

    allocation_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row.category)}</td>"
        f"<td>{html.escape(row.asset_class)}</td>"
        f"<td class='num'>{row.exposure_usd:,.2f}</td>"
        f"<td class='num'>{row.dollar_weight:.2%}</td>"
        f"<td class='num'>{row.risk_contribution_estimated:.2%}</td>"
        f"<td class='num'>{row.fi_10y_equivalent:,.2f}</td>"
        "</tr>"
        for row in allocation_summary
    )

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
            "<p><em>Risk interpretation note: historical/estimated metrics above should be read in the context of this active regime.</em></p>"
            "</div>"
        )

    proxy_rows = ""
    if mapping_table is not None and mapping_table.risk_proxies:
        proxy_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(row.risk_bucket)}</td>"
            f"<td>{html.escape(row.proxy_name)}</td>"
            f"<td>{html.escape(row.provider)}</td>"
            f"<td>{html.escape(row.symbol)}</td>"
            f"<td class='num'>{'' if row.tail_level is None else f'{row.tail_level:,.2f}'}</td>"
            f"<td>{html.escape(row.unit)}</td>"
            "</tr>"
            for row in mapping_table.risk_proxies
        )

    fx_rows = ""
    if mapping_table is not None and mapping_table.fx_sources:
        fx_rows = "\n".join(
            "<tr>"
            f"<td>{html.escape(row.currency_pair)}</td>"
            f"<td>{html.escape(row.provider)}</td>"
            f"<td>{html.escape(row.symbol)}</td>"
            "</tr>"
            for row in mapping_table.fx_sources
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
      <div class='metric'><span>Historical portfolio vol (1M/3M geomean)</span><strong>{summary.historical_vol:.2%}</strong></div>
      <div class='metric'><span>Estimated portfolio vol (asset-class proxy / mapped vol)</span><strong>{summary.estimated_vol:.2%}</strong></div>
      <div class='metric'><span>Funded AUM</span><strong>{summary.funded_aum:,.0f}</strong></div>
      <div class='metric'><span>Gross exposure</span><strong>{summary.gross_exposure:,.0f}</strong></div>
      <div class='metric'><span>Net exposure</span><strong>{summary.net_exposure:,.0f}</strong></div>
      <div class='metric'><span>Mapping coverage</span><strong>{summary.mapped_positions}/{summary.total_positions}</strong></div>
    </div>
  </div>

  <div class='card'>
    <h2>Allocation Summary</h2>
    <table>
      <thead><tr><th>Category</th><th>Risk Bucket</th><th class='num'>Exposure USD</th><th class='num'>Dollar%</th><th class='num'>Basic RC</th><th class='num'>FI 10Y Eqv</th></tr></thead>
      <tbody>{allocation_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>Position Risk Decomposition</h2>
    <table>
      <thead>
        <tr>
          <th>Account</th><th>Ticker</th><th>Name</th><th>Category</th><th>Type</th>
          <th class='num'>Qty</th><th class='num'>Multiplier</th><th class='num'>Exposure USD</th>
          <th class='num'>Dollar%</th><th class='num'>Est Vol</th><th class='num'>Basic RC</th>
          <th class='num'>Hist Vol</th><th>Mapping</th>
        </tr>
      </thead>
      <tbody>{position_rows}</tbody>
    </table>
  </div>
  {"" if not proxy_rows else f"<div class='card'><h2>Live Proxy Hints</h2><table><thead><tr><th>Risk Bucket</th><th>Proxy</th><th>Provider</th><th>Lookup</th><th class='num'>Tail</th><th>Unit</th></tr></thead><tbody>{proxy_rows}</tbody></table></div>"}
  {"" if not fx_rows else f"<div class='card'><h2>FX Source Hints</h2><table><thead><tr><th>Pair</th><th>Provider</th><th>Lookup</th></tr></thead><tbody>{fx_rows}</tbody></table></div>"}
</body>
</html>
"""


def _resolve_mapping(
    *,
    symbol: str,
    exchange: str,
    local_symbol: str,
    mapping_index: Mapping[tuple[str, str], object],
    unique_mappings: Mapping[str, object],
):
    if _looks_like_option(local_symbol):
        return None

    symbol_key = normalize_mapping_symbol(symbol)
    venue = normalize_mapping_venue(exchange)
    exact = mapping_index.get((symbol_key, venue))
    if exact is not None:
        return exact
    return unique_mappings.get(symbol_key)


def _fi_10y_equivalent(
    *,
    asset_class: str,
    exposure_usd: float,
    duration: float | None,
    ten_year_duration: float,
) -> float | None:
    if asset_class != "FI" or duration is None or ten_year_duration == 0:
        return None
    return exposure_usd * duration / ten_year_duration


def _funded_aum(rows: list[RiskInputRow]) -> float:
    return _funded_aum_from_dicts(
        [
            {
                "instrument_type": row.instrument_type,
                "exposure_usd": row.exposure_usd,
                "weight": row.weight,
            }
            for row in rows
        ]
    )


def _funded_aum_from_dicts(rows: list[dict[str, object]]) -> float:
    non_futures = [
        float(row.get("exposure_usd") or 0.0)
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
