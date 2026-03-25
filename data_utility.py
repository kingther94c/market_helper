#!/usr/bin/env python3
"""Data utility functions for market regime research.

Focus of this module:
- Source free/open market data first
- Keep functions simple and composable
- Avoid black-box processing

Data sources used here:
1) Yahoo Finance chart API (ETF prices)
2) FRED public CSV endpoint (yields, inflation, growth, labor)
3) Polymarket public Gamma API (prediction market contracts)
4) PredictIt public market data endpoint (prediction contracts)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
import urllib.parse
import urllib.request
from urllib.error import URLError, HTTPError
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_ETFS = [
    "SPY",  # US large cap
    "QQQ",  # US growth proxy
    "IWM",  # US small cap
    "EFA",  # DM ex-US
    "EEM",  # EM equities
    "TLT",  # long duration UST
    "IEF",  # intermediate UST
    "LQD",  # IG credit
    "HYG",  # HY credit
    "GLD",  # gold
    "USO",  # oil ETF proxy
    "DBC",  # broad commodities
    "XLE",  # energy sector
    "XLK",  # tech sector
    "XLF",  # financials sector
]

# Common FRED series for regime work.
FRED_SERIES = {
    # Yields / curve
    "DGS10": "US 10Y Treasury yield",
    "DGS2": "US 2Y Treasury yield",
    "T10Y2Y": "10Y-2Y spread",
    "DFF": "Fed funds effective rate",
    # Inflation
    "CPIAUCSL": "CPI index (headline)",
    "CPILFESL": "Core CPI index",
    "PCEPI": "PCE price index",
    "PCEPILFE": "Core PCE price index",
    "T5YIE": "5Y breakeven inflation",
    # Growth / labor
    "GDPC1": "Real GDP",
    "INDPRO": "Industrial production",
    "PAYEMS": "Nonfarm payrolls",
    "UNRATE": "Unemployment rate",
    "RSAFS": "Real retail and food services sales",
}


@dataclass(frozen=True)
class DataPoint:
    ds: str
    value: Optional[float]


@dataclass(frozen=True)
class PredictionMarketQuote:
    source: str
    market_id: str
    question: str
    yes_price: Optional[float]
    no_price: Optional[float]
    volume: Optional[float]
    liquidity: Optional[float]
    end_date: Optional[str]


def _read_url(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; MarketHelper/1.0)",
            "Accept": "application/json,text/csv,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def fetch_yahoo_price_history(
    symbol: str,
    start: date,
    end: Optional[date] = None,
    interval: str = "1d",
) -> List[DataPoint]:
    """Fetch adjusted close-like daily price history from Yahoo chart API.

    Args:
        symbol: e.g., 'SPY', 'TLT'.
        start: start date (inclusive).
        end: end date (inclusive). default=today.
        interval: e.g. '1d', '1wk'.
    """
    end = end or date.today()
    p1 = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    p2 = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp())

    params = urllib.parse.urlencode({
        "period1": p1,
        "period2": p2,
        "interval": interval,
        "events": "history",
        "includeAdjustedClose": "true",
    })
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?{params}"

    text = _read_url(url)
    payload = json.loads(text)

    result = payload.get("chart", {}).get("result", [])
    if not result:
        error = payload.get("chart", {}).get("error")
        raise ValueError(f"Yahoo request failed for {symbol}: {error}")

    series = result[0]
    timestamps = series.get("timestamp", [])
    quote = (series.get("indicators", {}).get("quote") or [{}])[0]
    closes = quote.get("close", [])

    out: List[DataPoint] = []
    for ts, close in zip(timestamps, closes):
        ds = datetime.utcfromtimestamp(ts).date().isoformat()
        value = float(close) if close is not None else None
        out.append(DataPoint(ds=ds, value=value))
    return out


def fetch_yahoo_latest_prices(symbols: Iterable[str]) -> Dict[str, Optional[float]]:
    """Get the latest close for a list of tickers from Yahoo Finance."""
    latest: Dict[str, Optional[float]] = {}
    end = date.today()
    start = end - timedelta(days=10)

    for symbol in symbols:
        try:
            data = fetch_yahoo_price_history(symbol=symbol, start=start, end=end)
            valid = [x.value for x in data if x.value is not None]
            latest[symbol] = valid[-1] if valid else None
        except (URLError, HTTPError, ValueError):
            # Keep utility resilient in restricted/proxied environments.
            latest[symbol] = None
    return latest


def fetch_fred_series(series_id: str, start: Optional[date] = None, end: Optional[date] = None) -> List[DataPoint]:
    """Fetch a FRED time series via the public fredgraph CSV endpoint (no API key)."""
    base = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    params = {"id": series_id}
    if start:
        params["cosd"] = start.isoformat()
    if end:
        params["coed"] = end.isoformat()
    url = f"{base}?{urllib.parse.urlencode(params)}"

    text = _read_url(url)
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    if not rows or rows[0].split(",")[:2] != ["DATE", series_id]:
        raise ValueError(f"Unexpected FRED CSV format for {series_id}")

    out: List[DataPoint] = []
    for line in rows[1:]:
        ds, raw = line.split(",", 1)
        if raw == ".":
            value = None
        else:
            value = float(raw)
        out.append(DataPoint(ds=ds, value=value))
    return out


def fetch_fred_latest(series_ids: Iterable[str]) -> Dict[str, Optional[float]]:
    """Fetch latest available value for each FRED series ID provided."""
    latest: Dict[str, Optional[float]] = {}
    for sid in series_ids:
        try:
            series = fetch_fred_series(sid)
            valid = [x.value for x in series if x.value is not None]
            latest[sid] = valid[-1] if valid else None
        except (URLError, HTTPError, ValueError):
            latest[sid] = None
    return latest


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_polymarket_markets(limit: int = 20) -> List[PredictionMarketQuote]:
    """Fetch active markets from Polymarket Gamma API.

    Gamma API is public and commonly used for read-only market snapshots.
    """
    params = urllib.parse.urlencode(
        {
            "active": "true",
            "closed": "false",
            "archived": "false",
            "limit": str(limit),
            "order": "volume",
            "ascending": "false",
        }
    )
    url = f"https://gamma-api.polymarket.com/markets?{params}"
    text = _read_url(url)
    markets = json.loads(text)

    out: List[PredictionMarketQuote] = []
    if not isinstance(markets, list):
        raise ValueError("Unexpected Polymarket response format")

    for m in markets:
        if not isinstance(m, dict):
            continue

        yes_price = _safe_float(m.get("lastTradePrice"))
        if yes_price is None:
            yes_price = _safe_float(m.get("outcomePrices", [None])[0] if isinstance(m.get("outcomePrices"), list) else None)
        no_price = None if yes_price is None else max(0.0, min(1.0, 1.0 - yes_price))

        out.append(
            PredictionMarketQuote(
                source="polymarket",
                market_id=str(m.get("id", "")),
                question=str(m.get("question", "")),
                yes_price=yes_price,
                no_price=no_price,
                volume=_safe_float(m.get("volume")),
                liquidity=_safe_float(m.get("liquidity")),
                end_date=(m.get("endDate") or m.get("end_date")),
            )
        )
    return out


def fetch_predictit_markets(limit: int = 20) -> List[PredictionMarketQuote]:
    """Fetch markets from PredictIt public market data endpoint."""
    url = "https://www.predictit.org/api/marketdata/all/"
    text = _read_url(url)
    payload = json.loads(text)
    markets = payload.get("markets", [])
    if not isinstance(markets, list):
        raise ValueError("Unexpected PredictIt response format")

    out: List[PredictionMarketQuote] = []
    for m in markets[:limit]:
        if not isinstance(m, dict):
            continue

        contracts = m.get("contracts", [])
        top_contract = contracts[0] if isinstance(contracts, list) and contracts else {}
        yes_price = _safe_float(top_contract.get("lastTradePrice"))
        no_price = _safe_float(top_contract.get("bestNoPrice"))

        out.append(
            PredictionMarketQuote(
                source="predictit",
                market_id=str(m.get("id", "")),
                question=str(m.get("name", "")),
                yes_price=yes_price,
                no_price=no_price,
                volume=_safe_float(top_contract.get("tradeVolume")),
                liquidity=None,
                end_date=top_contract.get("dateEnd") or m.get("dateEnd"),
            )
        )
    return out


def fetch_prediction_market_reserve(limit_each: int = 20) -> Dict[str, List[PredictionMarketQuote]]:
    """Best-effort cache-oriented fetcher for external prediction market data."""
    reserve: Dict[str, List[PredictionMarketQuote]] = {
        "polymarket": [],
        "predictit": [],
    }
    try:
        reserve["polymarket"] = fetch_polymarket_markets(limit=limit_each)
    except (URLError, HTTPError, ValueError, json.JSONDecodeError):
        reserve["polymarket"] = []

    try:
        reserve["predictit"] = fetch_predictit_markets(limit=limit_each)
    except (URLError, HTTPError, ValueError, json.JSONDecodeError):
        reserve["predictit"] = []

    return reserve


def get_common_market_snapshot() -> Dict[str, Dict[str, Optional[float]]]:
    """Convenience snapshot for regime dashboard scaffolding."""
    etf_prices = fetch_yahoo_latest_prices(DEFAULT_ETFS)

    yield_ids = ["DGS10", "DGS2", "T10Y2Y", "DFF"]
    inflation_ids = ["CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "T5YIE"]
    growth_ids = ["GDPC1", "INDPRO", "PAYEMS", "UNRATE", "RSAFS"]

    yield_data = fetch_fred_latest(yield_ids)
    inflation_data = fetch_fred_latest(inflation_ids)
    growth_data = fetch_fred_latest(growth_ids)

    prediction_data = fetch_prediction_market_reserve(limit_each=10)

    return {
        "etf_prices": etf_prices,
        "bond_and_curve": yield_data,
        "inflation": inflation_data,
        "growth_and_jobs": growth_data,
        "prediction_market_reserve_counts": {
            "polymarket": float(len(prediction_data["polymarket"])),
            "predictit": float(len(prediction_data["predictit"])),
        },
    }


def demo() -> None:
    snapshot = get_common_market_snapshot()

    print("=== ETF Prices (Yahoo) ===")
    for k, v in snapshot["etf_prices"].items():
        print(f"{k:>6}: {v}")

    print("\n=== Bond / Curve (FRED) ===")
    for k, v in snapshot["bond_and_curve"].items():
        print(f"{k:>10}: {v}")

    print("\n=== Inflation (FRED) ===")
    for k, v in snapshot["inflation"].items():
        print(f"{k:>10}: {v}")

    print("\n=== Growth & Jobs (FRED) ===")
    for k, v in snapshot["growth_and_jobs"].items():
        print(f"{k:>10}: {v}")

    print("\n=== Prediction Market Reserve (counts) ===")
    for k, v in snapshot["prediction_market_reserve_counts"].items():
        print(f"{k:>10}: {v}")


if __name__ == "__main__":
    demo()
