from __future__ import annotations

"""Parse IBKR Flex XML into performance-report friendly datasets."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
import csv
import re
import xml.etree.ElementTree as ET


_DATE_KEYS = ("date", "reportDate", "statementDate", "fromDate", "toDate")

_NAV_START_KEYS = ("startingNAV", "startingValue", "startNAV", "beginningNAV")
_NAV_END_KEYS = ("endingNAV", "endingValue", "endNAV", "netAssetValue", "total", "nav")
_CASH_FLOW_KEYS = ("depositWithdrawal", "depositsWithdrawals", "depositWithdrawals", "cashFlow", "netTransfers")
_PNL_KEYS = ("pnl", "dailyPnL", "profitAndLoss", "changeInNAV", "tradingProfitLoss")
_RETURN_KEYS = ("dailyReturn", "return", "timeWeightedReturn")

_AMOUNT_KEYS = ("amount", "amountInBase", "netAmount")
_CATEGORY_KEYS = ("type", "transactionType", "description", "category")

_CASH_CATEGORY_RE = re.compile(r"deposit|withdraw|withdrawal|fund", re.IGNORECASE)

_HORIZON_ALIASES = {
    "MTD": ("mtd", "monthtodate", "month_to_date"),
    "YTD": ("ytd", "yeartodate", "year_to_date"),
    "1M": ("1m", "1month", "one_month", "onemonth"),
}
_WEIGHTING_ALIASES = {
    "money_weighted": ("moneyweighted", "mwr", "irr"),
    "time_weighted": ("timeweighted", "twr", "twror"),
}
_CURRENCY_ALIASES = {
    "USD": ("usd",),
    "SGD": ("sgd",),
}
_PNL_ALIASES = ("pnl", "profit", "gain", "loss")
_RETURN_ALIASES = ("return", "performance", "pct", "percentage")


@dataclass(frozen=True)
class FlexDailyPerformanceRow:
    date: date
    nav_start: float | None
    nav_end: float | None
    pnl: float | None
    return_pct: float | None
    cash_flow: float


@dataclass(frozen=True)
class FlexCashFlowRow:
    date: date
    amount: float
    kind: str
    description: str


@dataclass(frozen=True)
class FlexHorizonPerformanceRow:
    as_of: date
    source_version: str
    horizon: str
    weighting: str
    currency: str
    dollar_pnl: float | None
    return_pct: float | None


@dataclass(frozen=True)
class FlexPerformanceDataset:
    daily_performance: list[FlexDailyPerformanceRow]
    cash_flows: list[FlexCashFlowRow]
    horizon_rows: list[FlexHorizonPerformanceRow]


@dataclass(frozen=True)
class FlexPerformanceExportPaths:
    daily_performance_csv: Path
    cash_flows_csv: Path


def parse_flex_performance_xml(path: str | Path) -> FlexPerformanceDataset:
    root = ET.fromstring(Path(path).read_text(encoding="utf-8"))

    raw_daily = _extract_daily_rows(root)
    cash_rows = _extract_cash_flow_rows(root)
    cash_by_date = _aggregate_cash_by_date(cash_rows)

    normalized_daily: list[FlexDailyPerformanceRow] = []
    for row in raw_daily:
        merged_cash = cash_by_date.get(row.date, row.cash_flow)
        normalized_daily.append(
            FlexDailyPerformanceRow(
                date=row.date,
                nav_start=row.nav_start,
                nav_end=row.nav_end,
                pnl=row.pnl if row.pnl is not None else _derive_pnl(row.nav_start, row.nav_end, merged_cash),
                return_pct=row.return_pct,
                cash_flow=merged_cash,
            )
        )

    if not normalized_daily and cash_rows:
        normalized_daily = [
            FlexDailyPerformanceRow(
                date=d,
                nav_start=None,
                nav_end=None,
                pnl=None,
                return_pct=None,
                cash_flow=amt,
            )
            for d, amt in sorted(cash_by_date.items())
        ]

    horizon_rows = _extract_horizon_rows(root, daily_rows=normalized_daily)

    return FlexPerformanceDataset(
        daily_performance=sorted(normalized_daily, key=lambda row: row.date),
        cash_flows=sorted(cash_rows, key=lambda row: row.date),
        horizon_rows=horizon_rows,
    )


def export_flex_performance_csv(
    dataset: FlexPerformanceDataset,
    *,
    output_dir: str | Path,
    daily_filename: str = "daily_performance.csv",
    cash_filename: str = "cash_injection_withdrawal.csv",
) -> FlexPerformanceExportPaths:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    daily_path = out_dir / daily_filename
    cash_path = out_dir / cash_filename

    with daily_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["date", "nav_start", "nav_end", "daily_pnl", "daily_return", "cash_flow"],
        )
        writer.writeheader()
        for row in dataset.daily_performance:
            writer.writerow(
                {
                    "date": row.date.isoformat(),
                    "nav_start": _to_csv_number(row.nav_start),
                    "nav_end": _to_csv_number(row.nav_end),
                    "daily_pnl": _to_csv_number(row.pnl),
                    "daily_return": _to_csv_number(row.return_pct),
                    "cash_flow": _to_csv_number(row.cash_flow),
                }
            )

    with cash_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "amount", "kind", "description"])
        writer.writeheader()
        for row in dataset.cash_flows:
            writer.writerow(
                {
                    "date": row.date.isoformat(),
                    "amount": _to_csv_number(row.amount),
                    "kind": row.kind,
                    "description": row.description,
                }
            )

    return FlexPerformanceExportPaths(
        daily_performance_csv=daily_path,
        cash_flows_csv=cash_path,
    )


def export_flex_horizon_report_csv(
    dataset: FlexPerformanceDataset,
    *,
    output_dir: str | Path,
    as_of: date | None = None,
) -> Path:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_as_of = as_of or _resolve_as_of_date(dataset)
    output_path = out_dir / f"performance_report_{report_as_of.strftime('%Y%m%d')}.csv"

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["as_of", "source_version", "horizon", "weighting", "currency", "dollar_pnl", "return_pct"],
        )
        writer.writeheader()
        for row in sorted(dataset.horizon_rows, key=lambda item: (item.horizon, item.weighting, item.currency)):
            writer.writerow(
                {
                    "as_of": row.as_of.isoformat(),
                    "source_version": row.source_version,
                    "horizon": row.horizon,
                    "weighting": row.weighting,
                    "currency": row.currency,
                    "dollar_pnl": _to_csv_number(row.dollar_pnl),
                    "return_pct": _to_csv_number(row.return_pct),
                }
            )

    return output_path


def _extract_daily_rows(root: ET.Element) -> list[FlexDailyPerformanceRow]:
    rows: list[FlexDailyPerformanceRow] = []
    for element in root.iter():
        tag = _local_name(element.tag).lower()
        if tag not in {"changeinnav", "navinbase", "performancesummaryinbase", "dailyperformancesummary"}:
            continue
        parsed_date = _extract_date(element.attrib)
        if parsed_date is None:
            continue
        rows.append(
            FlexDailyPerformanceRow(
                date=parsed_date,
                nav_start=_extract_float(element.attrib, _NAV_START_KEYS),
                nav_end=_extract_float(element.attrib, _NAV_END_KEYS),
                pnl=_extract_float(element.attrib, _PNL_KEYS),
                return_pct=_extract_float(element.attrib, _RETURN_KEYS),
                cash_flow=_extract_float(element.attrib, _CASH_FLOW_KEYS) or 0.0,
            )
        )
    return rows


def _extract_cash_flow_rows(root: ET.Element) -> list[FlexCashFlowRow]:
    rows: list[FlexCashFlowRow] = []
    for element in root.iter():
        tag = _local_name(element.tag).lower()
        if tag not in {"cashtransaction", "cashtransactions"}:
            continue
        parsed_date = _extract_date(element.attrib)
        amount = _extract_float(element.attrib, _AMOUNT_KEYS)
        if parsed_date is None or amount is None:
            continue
        category_value = " ".join(str(element.attrib.get(key, "")) for key in _CATEGORY_KEYS).strip()
        if not _CASH_CATEGORY_RE.search(category_value):
            continue
        rows.append(
            FlexCashFlowRow(
                date=parsed_date,
                amount=amount,
                kind="injection" if amount >= 0 else "withdrawal",
                description=category_value,
            )
        )
    return rows


def _extract_horizon_rows(root: ET.Element, *, daily_rows: list[FlexDailyPerformanceRow]) -> list[FlexHorizonPerformanceRow]:
    by_version: dict[str, dict[tuple[str, str, str], dict[str, float | None]]] = {}
    as_of = _resolve_as_of_from_daily(daily_rows)

    for element in root.iter():
        tag = _local_name(element.tag)
        for key, raw_value in element.attrib.items():
            tokens = _tokenize_key(key)
            metric = _metric_from_tokens(tokens)
            if metric is None:
                continue
            parsed_value = _parse_float_or_none(raw_value)
            if parsed_value is None:
                continue
            horizon, weighting, currency, measure = metric
            version_map = by_version.setdefault(tag, {})
            metric_cell = version_map.setdefault((horizon, weighting, currency), {"dollar_pnl": None, "return_pct": None})
            metric_cell[measure] = parsed_value

    if not by_version:
        return _fallback_horizon_rows_from_daily(daily_rows, as_of=as_of)

    selected_version = _pick_best_version(by_version)
    version_cells = by_version[selected_version]
    rows: list[FlexHorizonPerformanceRow] = []
    for horizon in ("MTD", "YTD", "1M"):
        for weighting in ("money_weighted", "time_weighted"):
            for currency in ("USD", "SGD"):
                cell = version_cells.get((horizon, weighting, currency), {"dollar_pnl": None, "return_pct": None})
                rows.append(
                    FlexHorizonPerformanceRow(
                        as_of=as_of,
                        source_version=selected_version,
                        horizon=horizon,
                        weighting=weighting,
                        currency=currency,
                        dollar_pnl=cell.get("dollar_pnl"),
                        return_pct=cell.get("return_pct"),
                    )
                )
    return rows


def _fallback_horizon_rows_from_daily(
    daily_rows: list[FlexDailyPerformanceRow],
    *,
    as_of: date,
) -> list[FlexHorizonPerformanceRow]:
    if not daily_rows:
        return [
            FlexHorizonPerformanceRow(
                as_of=as_of,
                source_version="fallback_daily_nav",
                horizon=horizon,
                weighting=weighting,
                currency=currency,
                dollar_pnl=None,
                return_pct=None,
            )
            for horizon in ("MTD", "YTD", "1M")
            for weighting in ("money_weighted", "time_weighted")
            for currency in ("USD", "SGD")
        ]

    pnl_by_horizon = {
        "MTD": _sum_pnl(daily_rows[-22:]),
        "YTD": _sum_pnl(daily_rows),
        "1M": _sum_pnl(daily_rows[-22:]),
    }
    start_nav = daily_rows[0].nav_start or 0.0
    end_nav = daily_rows[-1].nav_end or 0.0
    simple_return = ((end_nav - start_nav) / start_nav) if start_nav else None

    return [
        FlexHorizonPerformanceRow(
            as_of=as_of,
            source_version="fallback_daily_nav",
            horizon=horizon,
            weighting=weighting,
            currency=currency,
            dollar_pnl=pnl_by_horizon[horizon],
            return_pct=simple_return,
        )
        for horizon in ("MTD", "YTD", "1M")
        for weighting in ("money_weighted", "time_weighted")
        for currency in ("USD", "SGD")
    ]


def _metric_from_tokens(tokens: set[str]) -> tuple[str, str, str, str] | None:
    horizon = None
    if "mtd" in tokens or "monthtodate" in tokens:
        horizon = "MTD"
    elif "ytd" in tokens or "yeartodate" in tokens:
        horizon = "YTD"
    elif ("1m" in tokens or "1month" in tokens or "onemonth" in tokens or {"one", "month"}.issubset(tokens)):
        horizon = "1M"

    if horizon is None:
        return None

    weighting = None
    if "moneyweighted" in tokens or "mwr" in tokens or "irr" in tokens or {"money", "weighted"}.issubset(tokens):
        weighting = "money_weighted"
    elif "timeweighted" in tokens or "twr" in tokens or {"time", "weighted"}.issubset(tokens):
        weighting = "time_weighted"

    if weighting is None:
        return None

    currency = None
    if "usd" in tokens:
        currency = "USD"
    elif "sgd" in tokens:
        currency = "SGD"

    if currency is None:
        return None

    if any(alias in tokens for alias in _PNL_ALIASES):
        measure = "dollar_pnl"
    elif any(alias in tokens for alias in _RETURN_ALIASES):
        measure = "return_pct"
    else:
        return None

    return horizon, weighting, currency, measure


def _pick_best_version(by_version: dict[str, dict[tuple[str, str, str], dict[str, float | None]]]) -> str:
    def score(version_name: str) -> tuple[int, int]:
        cells = by_version[version_name]
        full_cells = 0
        partial_cells = 0
        for cell in cells.values():
            has_pnl = cell.get("dollar_pnl") is not None
            has_return = cell.get("return_pct") is not None
            if has_pnl and has_return:
                full_cells += 1
            elif has_pnl or has_return:
                partial_cells += 1
        return (full_cells, partial_cells)

    return max(sorted(by_version.keys()), key=score)


def _sum_pnl(rows: list[FlexDailyPerformanceRow]) -> float | None:
    values = [row.pnl for row in rows if row.pnl is not None]
    if not values:
        return None
    return sum(values)


def _resolve_as_of_date(dataset: FlexPerformanceDataset) -> date:
    if dataset.horizon_rows:
        return dataset.horizon_rows[0].as_of
    return _resolve_as_of_from_daily(dataset.daily_performance)


def _resolve_as_of_from_daily(rows: list[FlexDailyPerformanceRow]) -> date:
    if rows:
        return max(row.date for row in rows)
    return datetime.now(timezone.utc).date()


def _derive_pnl(nav_start: float | None, nav_end: float | None, cash_flow: float) -> float | None:
    if nav_start is None or nav_end is None:
        return None
    return nav_end - nav_start - cash_flow


def _aggregate_cash_by_date(rows: list[FlexCashFlowRow]) -> dict[date, float]:
    result: dict[date, float] = {}
    for row in rows:
        result[row.date] = result.get(row.date, 0.0) + row.amount
    return result


def _extract_date(attrs: dict[str, str]) -> date | None:
    for key in _DATE_KEYS:
        value = attrs.get(key)
        if not value:
            continue
        parsed = _parse_date(value)
        if parsed is not None:
            return parsed
    return None


def _parse_date(raw: str) -> date | None:
    text = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m-%d;%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _extract_float(attrs: dict[str, str], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key not in attrs:
            continue
        parsed = _parse_float_or_none(attrs[key])
        if parsed is not None:
            return parsed
    return None


def _parse_float_or_none(raw: object) -> float | None:
    text = str(raw).replace(",", "").strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _tokenize_key(key: str) -> set[str]:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", key).lower()
    chunks = [chunk for chunk in normalized.split("_") if chunk]
    if not chunks:
        return set()

    joined = "".join(chunks)
    tokens = set(chunks)
    tokens.add(joined)

    camel_chunks = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", key)
    if camel_chunks:
        tokens.update(part.lower() for part in camel_chunks)
        tokens.add("".join(part.lower() for part in camel_chunks))
    return tokens


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _to_csv_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10g}"
