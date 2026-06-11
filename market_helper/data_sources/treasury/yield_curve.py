"""US Treasury daily par yield curves as a real-data fallback for FRED series.

FRED's daily treasury series (T10Y2Y, T10Y3M, T5YIE, DFII10, T5YIFR, DGS*)
are themselves constructed from the Treasury's daily par yield curve (H.15 /
treasury.gov). When FRED's endpoints are unreachable — observed on some
networks: api.stlouisfed.org times out entirely and fredgraph.csv stalls for
exactly these daily series — the same observations can be rebuilt from the
primary publisher, definitionally:

- ``DGS10``/``DGS5``/``DGS2``/``DGS3MO``: nominal par yields, direct columns.
- ``DFII10``/``DFII5``: real (TIPS) par yields, direct columns.
- ``T10Y2Y`` = 10Y - 2Y nominal; ``T10Y3M`` = 10Y - 3M nominal.
- ``T10YIE`` = 10Y nominal - 10Y real; ``T5YIE`` = 5Y nominal - 5Y real.
- ``T5YIFR``: FRED's documented construction from the two breakevens with
  semiannual compounding:
  ``(((1 + T10YIE/200)^20 / (1 + T5YIE/200)^10)^0.1 - 1) * 200``.

This module never fabricates data: every value is published by treasury.gov
or derived from published values via FRED's own documented formulas. Output
series carry ``metadata["source"] = "treasury_par_yield_curve"`` so callers
can log provenance.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Callable, Dict, Iterable, List, Mapping, Optional

from market_helper.data_library.loader import DownloadError, download_text
from market_helper.models import EconomicSeries, Observation

TREASURY_RATES_CSV_URL_TEMPLATE = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type={curve_type}"
    "&field_tdr_date_value={year}&page&_format=csv"
)
NOMINAL_CURVE_TYPE = "daily_treasury_yield_curve"
REAL_CURVE_TYPE = "daily_treasury_real_yield_curve"
DEFAULT_TREASURY_TIMEOUT_SECONDS = 30
TREASURY_SOURCE_NAME = "treasury_par_yield_curve"

# series_id -> (needs_nominal, needs_real)
TREASURY_DERIVABLE_SERIES: Mapping[str, tuple[bool, bool]] = {
    "DGS3MO": (True, False),
    "DGS2": (True, False),
    "DGS5": (True, False),
    "DGS10": (True, False),
    "DFII5": (False, True),
    "DFII10": (False, True),
    "T10Y2Y": (True, False),
    "T10Y3M": (True, False),
    "T10YIE": (True, True),
    "T5YIE": (True, True),
    "T5YIFR": (True, True),
}

_NOMINAL_COLUMNS = {"3 Mo": "3m", "2 Yr": "2y", "5 Yr": "5y", "10 Yr": "10y"}
_REAL_COLUMNS = {"5 YR": "5y_real", "10 YR": "10y_real"}


def download_treasury_derived_series(
    series_id: str,
    *,
    observation_start: Optional[str] = None,
    observation_end: Optional[str] = None,
    timeout: int = DEFAULT_TREASURY_TIMEOUT_SECONDS,
    fetcher: Optional[Callable[[str], str]] = None,
    title: Optional[str] = None,
) -> EconomicSeries:
    """Rebuild a FRED treasury series from treasury.gov par-yield CSVs.

    Raises :class:`DownloadError` when the series is not derivable or the
    treasury.gov fetch/parse fails — callers treat this exactly like a failed
    FRED transport and fall back to cached observations.
    """
    normalized_id = str(series_id).strip().upper()
    if normalized_id not in TREASURY_DERIVABLE_SERIES:
        raise DownloadError(
            f"{normalized_id} is not derivable from the treasury.gov par yield curves"
        )
    needs_nominal, needs_real = TREASURY_DERIVABLE_SERIES[normalized_id]

    start = _parse_iso(observation_start) if observation_start else None
    end = _parse_iso(observation_end) if observation_end else date.today()
    years = _years_to_fetch(start, end)

    nominal: Dict[date, Dict[str, float]] = {}
    real: Dict[date, Dict[str, float]] = {}
    for year in years:
        if needs_nominal:
            nominal.update(
                _fetch_curve_year(year, NOMINAL_CURVE_TYPE, _NOMINAL_COLUMNS, timeout=timeout, fetcher=fetcher)
            )
        if needs_real:
            real.update(
                _fetch_curve_year(year, REAL_CURVE_TYPE, _REAL_COLUMNS, timeout=timeout, fetcher=fetcher)
            )

    observations: List[Observation] = []
    for obs_date in sorted(set(nominal) | set(real)):
        if start is not None and obs_date < start:
            continue
        if obs_date > end:
            continue
        value = _derive_value(normalized_id, nominal.get(obs_date, {}), real.get(obs_date, {}))
        if value is None:
            continue
        observations.append(Observation(date=obs_date.isoformat(), value=round(value, 4)))

    return EconomicSeries(
        series_id=normalized_id,
        title=title or normalized_id,
        units="lin",
        frequency="daily",
        observations=observations,
        metadata={
            "source": TREASURY_SOURCE_NAME,
            "derivation": _derivation_label(normalized_id),
        },
    )


def _derive_value(
    series_id: str,
    nominal_row: Mapping[str, float],
    real_row: Mapping[str, float],
) -> Optional[float]:
    def n(key: str) -> Optional[float]:
        return nominal_row.get(key)

    def r(key: str) -> Optional[float]:
        return real_row.get(key)

    if series_id == "DGS3MO":
        return n("3m")
    if series_id == "DGS2":
        return n("2y")
    if series_id == "DGS5":
        return n("5y")
    if series_id == "DGS10":
        return n("10y")
    if series_id == "DFII5":
        return r("5y_real")
    if series_id == "DFII10":
        return r("10y_real")
    if series_id == "T10Y2Y":
        return _diff(n("10y"), n("2y"))
    if series_id == "T10Y3M":
        return _diff(n("10y"), n("3m"))
    if series_id == "T10YIE":
        return _diff(n("10y"), r("10y_real"))
    if series_id == "T5YIE":
        return _diff(n("5y"), r("5y_real"))
    if series_id == "T5YIFR":
        bc10 = _diff(n("10y"), r("10y_real"))
        bc5 = _diff(n("5y"), r("5y_real"))
        if bc10 is None or bc5 is None:
            return None
        # FRED's documented construction (semiannual compounding):
        # (((1+BC10/200)^20 / (1+BC5/200)^10)^0.1 - 1) * 200
        try:
            return (((1.0 + bc10 / 200.0) ** 20 / (1.0 + bc5 / 200.0) ** 10) ** 0.1 - 1.0) * 200.0
        except (ZeroDivisionError, OverflowError, ValueError):
            return None
    return None


def _diff(left: Optional[float], right: Optional[float]) -> Optional[float]:
    if left is None or right is None:
        return None
    return left - right


def _derivation_label(series_id: str) -> str:
    labels = {
        "T10Y2Y": "10Y - 2Y nominal par yield",
        "T10Y3M": "10Y - 3M nominal par yield",
        "T10YIE": "10Y nominal - 10Y real par yield",
        "T5YIE": "5Y nominal - 5Y real par yield",
        "T5YIFR": "forward breakeven from T10YIE/T5YIE (FRED formula)",
    }
    return labels.get(series_id, "direct par-yield column")


def _fetch_curve_year(
    year: int,
    curve_type: str,
    column_map: Mapping[str, str],
    *,
    timeout: int,
    fetcher: Optional[Callable[[str], str]],
) -> Dict[date, Dict[str, float]]:
    url = TREASURY_RATES_CSV_URL_TEMPLATE.format(year=year, curve_type=curve_type)
    if fetcher is not None:
        body = fetcher(url)
    else:
        body = download_text(
            url,
            timeout=timeout,
            headers={"Accept": "text/csv, text/plain, */*"},
        )
    return _parse_curve_csv(body, column_map, curve_label=f"{curve_type}/{year}")


def _parse_curve_csv(
    body: str,
    column_map: Mapping[str, str],
    *,
    curve_label: str,
) -> Dict[date, Dict[str, float]]:
    import csv
    import io

    reader = csv.DictReader(io.StringIO(body))
    if reader.fieldnames is None or "Date" not in reader.fieldnames:
        raise DownloadError(
            f"treasury.gov CSV for {curve_label} did not include a Date header"
        )
    available = {
        source: target
        for source, target in column_map.items()
        if source in reader.fieldnames
    }
    if not available:
        raise DownloadError(
            f"treasury.gov CSV for {curve_label} did not include any expected tenor columns"
        )
    parsed: Dict[date, Dict[str, float]] = {}
    for row in reader:
        raw_date = str(row.get("Date") or "").strip()
        obs_date = _parse_treasury_date(raw_date)
        if obs_date is None:
            continue
        values: Dict[str, float] = {}
        for source, target in available.items():
            raw_value = str(row.get(source) or "").strip()
            if not raw_value or raw_value.upper() in {"N/A", "NA"}:
                continue
            try:
                values[target] = float(raw_value)
            except ValueError:
                continue
        if values:
            parsed[obs_date] = values
    if not parsed:
        raise DownloadError(
            f"treasury.gov CSV for {curve_label} contained no parseable observations"
        )
    return parsed


def _parse_treasury_date(raw: str) -> Optional[date]:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_iso(raw: str) -> date:
    return date.fromisoformat(str(raw).strip())


def _years_to_fetch(start: Optional[date], end: date) -> Iterable[int]:
    if start is None:
        return [end.year]
    if start > end:
        return [end.year]
    return list(range(start.year, end.year + 1))


__all__ = [
    "TREASURY_DERIVABLE_SERIES",
    "TREASURY_SOURCE_NAME",
    "download_treasury_derived_series",
]
