from __future__ import annotations

import csv
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import stdev
from typing import Any, Mapping

TRADING_DAYS = 252
HIST_1M_DAYS = 21
HIST_3M_DAYS = 63
DEFAULT_TENOR_DV01_PER_1MM = 85.0


@dataclass(frozen=True)
class RiskInputRow:
    internal_id: str
    symbol: str
    account: str
    exchange: str
    market_value: float
    weight: float
    quantity: float
    latest_price: float
    asset_class: str
    duration: float
    dv01_usd: float


@dataclass(frozen=True)
class RiskMetricsRow:
    internal_id: str
    symbol: str
    account: str
    asset_class: str
    market_value: float
    weight: float
    duration: float
    duration_10y_equivalent: float
    dv01_usd: float
    dv01_10y_equivalent: float
    historical_vol: float
    estimated_vol: float
    risk_contribution_historical: float
    risk_contribution_estimated: float


@dataclass(frozen=True)
class PortfolioRiskSummary:
    historical_vol: float
    estimated_vol: float
    portfolio_dv01_usd: float
    missing_ctd_count: int


def build_risk_html_report(
    *,
    positions_csv_path: str | Path,
    returns_path: str | Path,
    output_path: str | Path,
    proxy_path: str | Path | None = None,
    duration_path: str | Path | None = None,
    futures_dv01_path: str | Path | None = None,
    strict_futures_dv01: bool = False,
) -> Path:
    duration_lookup = _load_duration_lookup(duration_path)
    futures_lookup, tenor_dv01_per_1mm = _load_futures_dv01_lookup(futures_dv01_path)
    rows = load_position_rows(
        positions_csv_path,
        duration_lookup=duration_lookup,
        futures_dv01_lookup=futures_lookup,
    )
    returns = _load_returns(returns_path)
    proxy = _load_proxy(proxy_path)
    missing_ctd_rows = collect_missing_ctd_rows(rows)
    if strict_futures_dv01 and missing_ctd_rows:
        missing_ids = ", ".join(sorted({row.internal_id for row in missing_ctd_rows}))
        raise ValueError(
            "Missing CTD/conversion-factor specs for rates futures: "
            f"{missing_ids}. Provide --futures-dv01-map with conversion_factor/ctd_duration/contract_multiplier."
        )

    historical_vols = {
        row.internal_id: historical_geomean_vol(returns.get(row.internal_id, [])) for row in rows
    }
    estimated_vols = {
        row.internal_id: estimated_asset_class_vol(row.asset_class, proxy) for row in rows
    }

    historical_corr = build_historical_correlation(rows, returns)
    estimated_corr = build_estimated_correlation(rows)

    portfolio_hist_vol = portfolio_volatility(rows, historical_vols, historical_corr)
    portfolio_est_vol = portfolio_volatility(rows, estimated_vols, estimated_corr)

    risk_rows = [
        RiskMetricsRow(
            internal_id=row.internal_id,
            symbol=row.symbol,
            account=row.account,
            asset_class=row.asset_class,
            market_value=row.market_value,
            weight=row.weight,
            duration=row.duration,
            duration_10y_equivalent=(row.market_value * row.duration / 10.0),
            dv01_usd=row.dv01_usd,
            dv01_10y_equivalent=(
                row.dv01_usd / tenor_dv01_per_1mm if tenor_dv01_per_1mm > 0 else 0.0
            ),
            historical_vol=historical_vols[row.internal_id],
            estimated_vol=estimated_vols[row.internal_id],
            risk_contribution_historical=row.weight * historical_vols[row.internal_id],
            risk_contribution_estimated=row.weight * estimated_vols[row.internal_id],
        )
        for row in rows
    ]
    allocation_summary = build_allocation_summary(rows)
    summary = PortfolioRiskSummary(
        historical_vol=portfolio_hist_vol,
        estimated_vol=portfolio_est_vol,
        portfolio_dv01_usd=sum(row.dv01_usd for row in rows),
        missing_ctd_count=len(missing_ctd_rows),
    )

    rendered = render_html(
        risk_rows=risk_rows,
        summary=summary,
        allocation_summary=allocation_summary,
        missing_ctd_rows=missing_ctd_rows,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return output


def load_position_rows(
    path: str | Path,
    *,
    duration_lookup: Mapping[str, float] | None = None,
    futures_dv01_lookup: Mapping[str, dict[str, float]] | None = None,
) -> list[RiskInputRow]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        loaded = list(reader)

    total_market_value = sum(float(row.get("market_value") or 0.0) for row in loaded)
    parsed: list[RiskInputRow] = []
    effective_duration_lookup = duration_lookup or {}
    effective_futures_lookup = futures_dv01_lookup or {}

    for row in loaded:
        market_value = float(row.get("market_value") or 0.0)
        quantity = float(row.get("quantity") or 0.0)
        latest_price = float(row.get("latest_price") or 0.0)
        exchange = str(row.get("exchange") or "")
        raw_weight = row.get("weight")
        weight = (
            float(raw_weight)
            if raw_weight not in (None, "")
            else (market_value / total_market_value if total_market_value > 0 else 0.0)
        )
        internal_id = str(row.get("internal_id") or "")
        symbol = str(row.get("symbol") or internal_id or "")
        asset_class = infer_asset_class(symbol, exchange)
        duration = resolve_duration(
            internal_id=internal_id,
            symbol=symbol,
            asset_class=asset_class,
            duration_lookup=effective_duration_lookup,
        )
        dv01_usd = resolve_dynamic_dv01(
            internal_id=internal_id,
            symbol=symbol,
            asset_class=asset_class,
            quantity=quantity,
            latest_price=latest_price,
            futures_dv01_lookup=effective_futures_lookup,
        )

        parsed.append(
            RiskInputRow(
                internal_id=internal_id,
                symbol=symbol,
                account=str(row.get("account") or ""),
                exchange=exchange,
                market_value=market_value,
                weight=weight,
                quantity=quantity,
                latest_price=latest_price,
                asset_class=asset_class,
                duration=duration,
                dv01_usd=dv01_usd,
            )
        )
    return parsed


def resolve_duration(
    *,
    internal_id: str,
    symbol: str,
    asset_class: str,
    duration_lookup: Mapping[str, float],
) -> float:
    if internal_id in duration_lookup:
        return duration_lookup[internal_id]
    if symbol in duration_lookup:
        return duration_lookup[symbol]
    if asset_class == "FI":
        return 7.0
    return 0.0


def resolve_dynamic_dv01(
    *,
    internal_id: str,
    symbol: str,
    asset_class: str,
    quantity: float,
    latest_price: float,
    futures_dv01_lookup: Mapping[str, dict[str, float]],
) -> float:
    """CTD/CF based dynamic DV01, expressed in USD per 1bp for the full position."""
    if asset_class != "FI":
        return 0.0

    spec = futures_dv01_lookup.get(internal_id) or futures_dv01_lookup.get(symbol)
    if spec is None:
        return 0.0

    conversion_factor = spec.get("conversion_factor", 0.0)
    ctd_duration = spec.get("ctd_duration", 0.0)
    contract_multiplier = spec.get("contract_multiplier", 0.0)
    if conversion_factor <= 0 or ctd_duration <= 0 or contract_multiplier <= 0:
        return 0.0

    # Dynamic DV01: quantity * (futures_price * multiplier / conversion_factor) * duration * 1bp
    return (
        quantity
        * (latest_price * contract_multiplier / conversion_factor)
        * ctd_duration
        * 0.0001
    )


def infer_asset_class(symbol: str, exchange: str) -> str:
    upper_symbol = symbol.upper()
    upper_exchange = exchange.upper()

    if upper_exchange in {"CME", "CBOT", "NYMEX", "COMEX", "ICE"}:
        if upper_symbol.startswith(("ZN", "ZF", "ZT", "TY", "US", "TU", "FV")):
            return "FI"
        return "CM"
    if upper_symbol in {"GLD", "IAU", "XAUUSD"}:
        return "GOLD"
    if upper_symbol in {"BIL", "SHV", "SGOV", "CASH"}:
        return "CASH"
    return "EQ"


def collect_missing_ctd_rows(rows: list[RiskInputRow]) -> list[RiskInputRow]:
    return [
        row
        for row in rows
        if row.asset_class == "FI" and row.quantity != 0 and row.dv01_usd == 0.0
    ]


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
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True)) / (n - 1)
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


def build_allocation_summary(rows: list[RiskInputRow]) -> list[tuple[str, float, float, float]]:
    by_bucket: dict[str, tuple[float, float, float]] = {}
    for row in rows:
        mv, wt, dv01 = by_bucket.get(row.asset_class, (0.0, 0.0, 0.0))
        by_bucket[row.asset_class] = (mv + row.market_value, wt + row.weight, dv01 + row.dv01_usd)
    return sorted((bucket, vals[0], vals[1], vals[2]) for bucket, vals in by_bucket.items())


def render_html(
    *,
    risk_rows: list[RiskMetricsRow],
    summary: PortfolioRiskSummary,
    allocation_summary: list[tuple[str, float, float, float]],
    missing_ctd_rows: list[RiskInputRow],
) -> str:
    position_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row.account)}</td>"
        f"<td>{html.escape(row.symbol)}</td>"
        f"<td>{html.escape(row.internal_id)}</td>"
        f"<td>{html.escape(row.asset_class)}</td>"
        f"<td class='num'>{row.market_value:,.2f}</td>"
        f"<td class='num'>{row.weight:.2%}</td>"
        f"<td class='num'>{row.duration:.2f}</td>"
        f"<td class='num'>{row.duration_10y_equivalent:,.2f}</td>"
        f"<td class='num'>{row.dv01_usd:,.2f}</td>"
        f"<td class='num'>{row.dv01_10y_equivalent:,.2f}</td>"
        f"<td class='num'>{row.historical_vol:.2%}</td>"
        f"<td class='num'>{row.estimated_vol:.2%}</td>"
        f"<td class='num'>{row.risk_contribution_historical:.2%}</td>"
        f"<td class='num'>{row.risk_contribution_estimated:.2%}</td>"
        "</tr>"
        for row in risk_rows
    )

    allocation_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(asset_class)}</td>"
        f"<td class='num'>{market_value:,.2f}</td>"
        f"<td class='num'>{weight:.2%}</td>"
        f"<td class='num'>{dv01:,.2f}</td>"
        "</tr>"
        for asset_class, market_value, weight, dv01 in allocation_summary
    )

    missing_rows_html = "\n".join(
        "<li>"
        f"{html.escape(row.internal_id)} ({html.escape(row.symbol)})"
        "</li>"
        for row in missing_ctd_rows
    )
    warning_block = (
        "<div class='card'>"
        "<h2>Missing CTD/CF Inputs</h2>"
        "<p>These rates futures have no CTD+conversion-factor mapping, so DV01 is set to 0:</p>"
        f"<ul>{missing_rows_html}</ul>"
        "</div>"
        if missing_ctd_rows
        else ""
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
    .metrics {{ display: flex; gap: 12px; }}
    .metric {{ background: #f1f5f9; padding: 10px 12px; border-radius: 8px; min-width: 240px; }}
    .metric span {{ display: block; color: #475569; font-size: 12px; }}
    .metric strong {{ font-size: 20px; }}
  </style>
</head>
<body>
  <h1>Portfolio Risk Report</h1>

  <div class='card'>
    <h2>Portfolio Summary</h2>
    <div class='metrics'>
      <div class='metric'><span>Historical portfolio vol (1M/3M geomean)</span><strong>{summary.historical_vol:.2%}</strong></div>
      <div class='metric'><span>Estimated portfolio vol (asset-class proxy)</span><strong>{summary.estimated_vol:.2%}</strong></div>
      <div class='metric'><span>Portfolio DV01 (USD / 1bp)</span><strong>{summary.portfolio_dv01_usd:,.2f}</strong></div>
      <div class='metric'><span>Missing CTD/CF rows</span><strong>{summary.missing_ctd_count}</strong></div>
    </div>
  </div>

  {warning_block}

  <div class='card'>
    <h2>Allocation Summary</h2>
    <table>
      <thead><tr><th>Asset class</th><th class='num'>Market value</th><th class='num'>Weight</th><th class='num'>DV01</th></tr></thead>
      <tbody>{allocation_rows}</tbody>
    </table>
  </div>

  <div class='card'>
    <h2>Position Risk Decomposition</h2>
    <table>
      <thead>
        <tr>
          <th>Account</th><th>Symbol</th><th>Internal ID</th><th>Asset Class</th>
          <th class='num'>Market Value</th><th class='num'>Weight</th>
          <th class='num'>Duration</th><th class='num'>10Y Eqv Exposure</th>
          <th class='num'>DV01</th><th class='num'>DV01 10Y Eqv (1MM notional)</th>
          <th class='num'>Hist Vol</th><th class='num'>Est Vol</th>
          <th class='num'>Hist RC</th><th class='num'>Est RC</th>
        </tr>
      </thead>
      <tbody>{position_rows}</tbody>
    </table>
  </div>
</body>
</html>
"""


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
    return {str(k).upper(): float(v) for k, v in loaded.items()}


def _load_duration_lookup(path: str | Path | None) -> dict[str, float]:
    if path is None:
        return {}
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Expected duration JSON object, e.g. {'IBKR:123': 6.2, 'TLT': 16.5}")
    return {str(k): float(v) for k, v in loaded.items()}


def _load_futures_dv01_lookup(path: str | Path | None) -> tuple[dict[str, dict[str, float]], float]:
    if path is None:
        return ({}, DEFAULT_TENOR_DV01_PER_1MM)

    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Expected futures DV01 JSON object")

    tenor_dv01_per_1mm = float(loaded.get("tenor_dv01_per_1mm", DEFAULT_TENOR_DV01_PER_1MM))
    rows_raw: Any = loaded.get("rows", loaded)
    if not isinstance(rows_raw, dict):
        raise ValueError("Expected futures DV01 rows object keyed by internal_id or symbol")

    normalized: dict[str, dict[str, float]] = {}
    for key, value in rows_raw.items():
        if not isinstance(value, dict):
            continue
        normalized[str(key)] = {
            "conversion_factor": float(value.get("conversion_factor", 0.0)),
            "ctd_duration": float(value.get("ctd_duration", 0.0)),
            "contract_multiplier": float(value.get("contract_multiplier", 0.0)),
        }
    return normalized, tenor_dv01_per_1mm
