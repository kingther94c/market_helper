from __future__ import annotations

import csv
import html
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import stdev
from typing import Mapping

TRADING_DAYS = 252
HIST_1M_DAYS = 21
HIST_3M_DAYS = 63


@dataclass(frozen=True)
class RiskInputRow:
    internal_id: str
    symbol: str
    account: str
    market_value: float
    weight: float
    asset_class: str


@dataclass(frozen=True)
class RiskMetricsRow:
    internal_id: str
    symbol: str
    account: str
    asset_class: str
    market_value: float
    weight: float
    historical_vol: float
    estimated_vol: float
    risk_contribution_historical: float
    risk_contribution_estimated: float


@dataclass(frozen=True)
class PortfolioRiskSummary:
    historical_vol: float
    estimated_vol: float


def build_risk_html_report(
    *,
    positions_csv_path: str | Path,
    returns_path: str | Path,
    output_path: str | Path,
    proxy_path: str | Path | None = None,
) -> Path:
    rows = load_position_rows(positions_csv_path)
    returns = _load_returns(returns_path)
    proxy = _load_proxy(proxy_path)

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
    )

    rendered = render_html(risk_rows=risk_rows, summary=summary, allocation_summary=allocation_summary)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    return output


def load_position_rows(path: str | Path) -> list[RiskInputRow]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        loaded = list(reader)

    total_market_value = sum(float(row.get("market_value") or 0.0) for row in loaded)
    parsed: list[RiskInputRow] = []
    for row in loaded:
        market_value = float(row.get("market_value") or 0.0)
        raw_weight = row.get("weight")
        weight = (
            float(raw_weight)
            if raw_weight not in (None, "")
            else (market_value / total_market_value if total_market_value > 0 else 0.0)
        )
        parsed.append(
            RiskInputRow(
                internal_id=str(row.get("internal_id") or ""),
                symbol=str(row.get("symbol") or row.get("internal_id") or ""),
                account=str(row.get("account") or ""),
                market_value=market_value,
                weight=weight,
                asset_class=infer_asset_class(str(row.get("symbol") or ""), str(row.get("exchange") or "")),
            )
        )
    return parsed


def infer_asset_class(symbol: str, exchange: str) -> str:
    upper_symbol = symbol.upper()
    upper_exchange = exchange.upper()

    if upper_exchange in {"CME", "CBOT", "NYMEX", "COMEX", "ICE"}:
        if upper_symbol.startswith(("ZN", "ZF", "ZT", "TY", "US")):
            return "FI"
        return "CM"
    if upper_symbol in {"GLD", "IAU", "XAUUSD"}:
        return "GOLD"
    if upper_symbol in {"BIL", "SHV", "SGOV", "CASH"}:
        return "CASH"
    return "EQ"


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


def build_allocation_summary(rows: list[RiskInputRow]) -> list[tuple[str, float, float]]:
    by_bucket: dict[str, tuple[float, float]] = {}
    for row in rows:
        mv, wt = by_bucket.get(row.asset_class, (0.0, 0.0))
        by_bucket[row.asset_class] = (mv + row.market_value, wt + row.weight)
    return sorted((bucket, vals[0], vals[1]) for bucket, vals in by_bucket.items())


def render_html(
    *,
    risk_rows: list[RiskMetricsRow],
    summary: PortfolioRiskSummary,
    allocation_summary: list[tuple[str, float, float]],
) -> str:
    position_rows = "\n".join(
        "<tr>"
        f"<td>{html.escape(row.account)}</td>"
        f"<td>{html.escape(row.symbol)}</td>"
        f"<td>{html.escape(row.internal_id)}</td>"
        f"<td>{html.escape(row.asset_class)}</td>"
        f"<td class='num'>{row.market_value:,.2f}</td>"
        f"<td class='num'>{row.weight:.2%}</td>"
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
        "</tr>"
        for asset_class, market_value, weight in allocation_summary
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
    .metric {{ background: #f1f5f9; padding: 10px 12px; border-radius: 8px; min-width: 220px; }}
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
    </div>
  </div>

  <div class='card'>
    <h2>Allocation Summary</h2>
    <table>
      <thead><tr><th>Asset class</th><th class='num'>Market value</th><th class='num'>Weight</th></tr></thead>
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
