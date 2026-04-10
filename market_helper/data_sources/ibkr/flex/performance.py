from __future__ import annotations

"""Parse IBKR Flex XML into performance-report friendly datasets."""

from dataclasses import dataclass
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import csv
import math
import re
from typing import TYPE_CHECKING
import xml.etree.ElementTree as ET

if TYPE_CHECKING:
    from market_helper.data_sources.yahoo_finance import YahooFinanceClient


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
DEFAULT_USDSGD_YAHOO_SYMBOL = "USDSGD=X"
DEFAULT_SGDUSD_YAHOO_SYMBOL = "SGDUSD=X"
DEFAULT_YAHOO_FX_PERIOD = "2y"
DEFAULT_YAHOO_FX_INTERVAL = "1d"
_YAHOO_FX_HISTORY_CACHE: dict[str, list[tuple[date, float]]] = {}


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


@dataclass(frozen=True)
class FlexNavPoint:
    date: date
    nav: float


@dataclass(frozen=True)
class FlexCashReportSummary:
    currency: str
    range_start: date | None
    range_end: date | None
    deposit_withdrawals: float | None
    deposit_withdrawals_mtd: float | None
    deposit_withdrawals_ytd: float | None


def parse_flex_performance_xml(
    path: str | Path,
    *,
    yahoo_client: YahooFinanceClient | None = None,
) -> FlexPerformanceDataset:
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

    horizon_rows = _extract_horizon_rows(
        root,
        daily_rows=normalized_daily,
        yahoo_client=yahoo_client,
    )

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
        for row in sorted(dataset.horizon_rows, key=lambda item: (_horizon_sort_key(item.horizon), item.weighting, item.currency)):
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


def _horizon_sort_key(horizon: str) -> tuple[int, int | str]:
    fixed_order = {"MTD": 0, "YTD": 1, "1M": 2}
    if horizon in fixed_order:
        return fixed_order[horizon], 0
    if horizon.startswith("Y") and horizon[1:].isdigit():
        return 3, int(horizon[1:])
    return 4, horizon


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


def _extract_horizon_rows(
    root: ET.Element,
    *,
    daily_rows: list[FlexDailyPerformanceRow],
    yahoo_client: YahooFinanceClient | None = None,
) -> list[FlexHorizonPerformanceRow]:
    by_version: dict[str, dict[tuple[str, str, str], dict[str, float | None]]] = {}
    nav_snapshots = _extract_nav_snapshots(root)
    as_of = _resolve_as_of(root, daily_rows=daily_rows, nav_snapshots=nav_snapshots)

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

    reconstructed_rows = _rebuild_horizon_rows_from_daily_nav(
        root,
        as_of=as_of,
        daily_rows=daily_rows,
        nav_snapshots=nav_snapshots,
        yahoo_client=yahoo_client,
    )
    legacy_special_rows = _extract_special_horizon_rows(
        root,
        as_of=as_of,
        nav_snapshots=nav_snapshots,
        yahoo_client=yahoo_client,
    )
    reconstructed_has_cash_flow_logic = any(
        "+ExplicitCashFlows" in row.source_version or "+CashReportSummary" in row.source_version
        for row in reconstructed_rows
    )
    if reconstructed_rows and legacy_special_rows:
        special_rows = (
            _merge_horizon_rows(primary=reconstructed_rows, fallback=legacy_special_rows)
            if reconstructed_has_cash_flow_logic
            else _merge_horizon_rows(primary=legacy_special_rows, fallback=reconstructed_rows)
        )
    elif reconstructed_rows:
        special_rows = reconstructed_rows
    else:
        special_rows = legacy_special_rows

    if not by_version:
        if special_rows:
            return special_rows
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
    return _merge_horizon_rows(primary=rows, fallback=special_rows)


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


def _extract_special_horizon_rows(
    root: ET.Element,
    *,
    as_of: date,
    nav_snapshots: list[tuple[date, str, float]],
    yahoo_client: YahooFinanceClient | None = None,
) -> list[FlexHorizonPerformanceRow]:
    summary_total = _find_mtdytd_total_row(root)
    base_currency = _detect_base_currency(root, nav_snapshots)
    if summary_total is None or base_currency is None:
        return []

    start_nav_snapshots = {
        "MTD": _resolve_start_nav_snapshot(nav_snapshots, _start_of_month(as_of), currency=base_currency),
        "YTD": _resolve_start_nav_snapshot(nav_snapshots, date(as_of.year, 1, 1), currency=base_currency),
        "1M": _resolve_start_nav_snapshot(nav_snapshots, _subtract_months(as_of, 1), currency=base_currency),
    }
    start_nav_by_horizon = {
        horizon: snapshot[1] if snapshot is not None else None
        for horizon, snapshot in start_nav_snapshots.items()
    }
    end_nav_snapshot = _resolve_end_nav_snapshot(nav_snapshots, currency=base_currency)
    end_nav = end_nav_snapshot[1] if end_nav_snapshot is not None else None

    pnl_by_horizon = {
        "MTD": _parse_float_or_none(summary_total.attrib.get("mtmMTD")),
        "YTD": _parse_float_or_none(summary_total.attrib.get("mtmYTD")),
        "1M": _derive_nav_delta(start_nav_by_horizon["1M"], end_nav),
    }
    fx_history = (
        _load_usdsgd_history(yahoo_client=yahoo_client)
        if yahoo_client is not None and base_currency in {"USD", "SGD"}
        else None
    )

    rows: list[FlexHorizonPerformanceRow] = []
    for horizon in ("MTD", "YTD", "1M"):
        pnl_value = pnl_by_horizon[horizon]
        start_nav = start_nav_by_horizon[horizon]
        return_pct = None
        if pnl_value is not None and start_nav not in (None, 0.0):
            return_pct = pnl_value / start_nav

        for weighting in ("money_weighted", "time_weighted"):
            for currency in ("USD", "SGD"):
                use_value = currency == base_currency
                source_version = (
                    "MTDYTDPerformanceSummaryTotal"
                    if horizon in {"MTD", "YTD"}
                    else "EquitySummaryByReportDateInBase"
                )
                derived_source_version = source_version
                derived_pnl = pnl_value if use_value else None
                derived_return = return_pct if use_value else None
                if not use_value and fx_history:
                    derived_pnl, derived_return = _convert_horizon_metrics_with_fx(
                        base_currency=base_currency,
                        target_currency=currency,
                        pnl_value=pnl_value,
                        start_snapshot=start_nav_snapshots[horizon],
                        end_snapshot=end_nav_snapshot,
                        fx_history=fx_history,
                    )
                    if derived_pnl is not None or derived_return is not None:
                        derived_source_version = f"{source_version}+YahooFinanceFX"
                rows.append(
                    FlexHorizonPerformanceRow(
                        as_of=as_of,
                        source_version=derived_source_version,
                        horizon=horizon,
                        weighting=weighting,
                        currency=currency,
                        dollar_pnl=derived_pnl,
                        return_pct=derived_return,
                    )
                )
    return rows


def _rebuild_horizon_rows_from_daily_nav(
    root: ET.Element,
    *,
    as_of: date,
    daily_rows: list[FlexDailyPerformanceRow],
    nav_snapshots: list[tuple[date, str, float]],
    yahoo_client: YahooFinanceClient | None = None,
) -> list[FlexHorizonPerformanceRow]:
    base_currency = _detect_base_currency(root, nav_snapshots)
    if base_currency is None:
        base_currency = "USD"

    nav_points = _extract_base_nav_points(
        daily_rows=daily_rows,
        nav_snapshots=nav_snapshots,
        base_currency=base_currency,
    )
    if len(nav_points) < 2:
        return []

    explicit_cash_flows = _extract_explicit_daily_cash_flows(daily_rows)
    cash_report_summaries = _extract_cash_report_summaries(root)
    fx_history = (
        _load_usdsgd_history(yahoo_client=yahoo_client)
        if yahoo_client is not None and base_currency in {"USD", "SGD"}
        else None
    )

    rows: list[FlexHorizonPerformanceRow] = []
    for target_currency in ("USD", "SGD"):
        target_nav_points = _convert_nav_points_to_currency(
            nav_points,
            from_currency=base_currency,
            to_currency=target_currency,
            fx_history=fx_history,
        )
        if len(target_nav_points) < 2:
            rows.extend(
                [
                    FlexHorizonPerformanceRow(
                        as_of=as_of,
                        source_version="DailyNavRebuilt",
                        horizon=horizon,
                        weighting=weighting,
                        currency=target_currency,
                        dollar_pnl=None,
                        return_pct=None,
                    )
                    for horizon in ("MTD", "YTD", "1M")
                    for weighting in ("money_weighted", "time_weighted")
                ]
            )
            continue

        target_explicit_flows = _convert_flow_schedule_to_currency(
            explicit_cash_flows,
            from_currency=base_currency,
            to_currency=target_currency,
            fx_history=fx_history,
        )
        for horizon in ("MTD", "YTD", "1M"):
            metrics = _rebuild_single_horizon_metrics(
                nav_points=target_nav_points,
                explicit_cash_flows=target_explicit_flows,
                cash_report_summaries=cash_report_summaries,
                base_currency=base_currency,
                target_currency=target_currency,
                horizon=horizon,
                as_of=as_of,
                fx_history=fx_history,
            )
            source_version = "DailyNavRebuilt"
            if metrics.used_explicit_cash_flows:
                source_version = f"{source_version}+ExplicitCashFlows"
            elif metrics.used_summary_cash_flow:
                source_version = f"{source_version}+CashReportSummary"
            if target_currency != base_currency:
                source_version = f"{source_version}+YahooFinanceFX"
            rows.extend(
                [
                    FlexHorizonPerformanceRow(
                        as_of=as_of,
                        source_version=source_version,
                        horizon=horizon,
                        weighting="money_weighted",
                        currency=target_currency,
                        dollar_pnl=metrics.money_weighted_pnl,
                        return_pct=metrics.money_weighted_return,
                    ),
                    FlexHorizonPerformanceRow(
                        as_of=as_of,
                        source_version=source_version,
                        horizon=horizon,
                        weighting="time_weighted",
                        currency=target_currency,
                        dollar_pnl=metrics.time_weighted_pnl,
                        return_pct=metrics.time_weighted_return,
                    ),
                ]
            )
    return rows


def _merge_horizon_rows(
    *,
    primary: list[FlexHorizonPerformanceRow],
    fallback: list[FlexHorizonPerformanceRow],
) -> list[FlexHorizonPerformanceRow]:
    if not fallback:
        return primary

    fallback_map = {
        (row.horizon, row.weighting, row.currency): row
        for row in fallback
    }
    merged: list[FlexHorizonPerformanceRow] = []
    for row in primary:
        fallback_row = fallback_map.get((row.horizon, row.weighting, row.currency))
        if fallback_row is None:
            merged.append(row)
            continue
        merged.append(
            FlexHorizonPerformanceRow(
                as_of=row.as_of,
                source_version=(
                    row.source_version
                    if row.dollar_pnl is not None or row.return_pct is not None
                    else fallback_row.source_version
                ),
                horizon=row.horizon,
                weighting=row.weighting,
                currency=row.currency,
                dollar_pnl=row.dollar_pnl if row.dollar_pnl is not None else fallback_row.dollar_pnl,
                return_pct=row.return_pct if row.return_pct is not None else fallback_row.return_pct,
            )
        )
    return merged


@dataclass(frozen=True)
class RebuiltHorizonMetrics:
    money_weighted_pnl: float | None
    money_weighted_return: float | None
    time_weighted_pnl: float | None
    time_weighted_return: float | None
    used_explicit_cash_flows: bool
    used_summary_cash_flow: bool


def _extract_base_nav_points(
    *,
    daily_rows: list[FlexDailyPerformanceRow],
    nav_snapshots: list[tuple[date, str, float]],
    base_currency: str,
) -> list[FlexNavPoint]:
    filtered_snapshots = [
        FlexNavPoint(date=snapshot_date, nav=nav)
        for snapshot_date, snapshot_currency, nav in nav_snapshots
        if snapshot_currency == base_currency
    ]
    if filtered_snapshots:
        return filtered_snapshots
    return _nav_points_from_daily_rows(daily_rows)


def _nav_points_from_daily_rows(rows: list[FlexDailyPerformanceRow]) -> list[FlexNavPoint]:
    if not rows:
        return []
    sorted_rows = sorted(rows, key=lambda row: row.date)
    points: list[FlexNavPoint] = []
    first = sorted_rows[0]
    if first.nav_start is not None:
        points.append(FlexNavPoint(date=first.date - timedelta(days=1), nav=first.nav_start))
    for row in sorted_rows:
        if row.nav_end is None:
            continue
        points.append(FlexNavPoint(date=row.date, nav=row.nav_end))
    deduped: dict[date, float] = {}
    for point in points:
        deduped[point.date] = point.nav
    return [FlexNavPoint(date=point_date, nav=deduped[point_date]) for point_date in sorted(deduped)]


def _extract_explicit_daily_cash_flows(rows: list[FlexDailyPerformanceRow]) -> dict[date, float]:
    flows: dict[date, float] = {}
    for row in rows:
        if abs(row.cash_flow) <= 1e-12:
            continue
        flows[row.date] = flows.get(row.date, 0.0) + row.cash_flow
    return flows


def _extract_cash_report_summaries(root: ET.Element) -> dict[str, FlexCashReportSummary]:
    summaries: dict[str, FlexCashReportSummary] = {}
    for element in root.iter():
        if _local_name(element.tag) != "CashReportCurrency":
            continue
        currency = str(element.attrib.get("currency", "")).upper().strip()
        if currency == "":
            continue
        summaries[currency] = FlexCashReportSummary(
            currency=currency,
            range_start=_parse_date(str(element.attrib.get("fromDate", "") or "")),
            range_end=_parse_date(str(element.attrib.get("toDate", "") or "")),
            deposit_withdrawals=_parse_float_or_none(element.attrib.get("depositWithdrawals")),
            deposit_withdrawals_mtd=_parse_float_or_none(element.attrib.get("depositWithdrawalsMTD")),
            deposit_withdrawals_ytd=_parse_float_or_none(element.attrib.get("depositWithdrawalsYTD")),
        )
    return summaries


def _convert_nav_points_to_currency(
    points: list[FlexNavPoint],
    *,
    from_currency: str,
    to_currency: str,
    fx_history: list[tuple[date, float]] | None,
) -> list[FlexNavPoint]:
    if from_currency == to_currency:
        return points
    if fx_history is None:
        return []
    converted: list[FlexNavPoint] = []
    for point in points:
        rate = _lookup_fx_rate(fx_history, point.date)
        if rate is None:
            continue
        converted_nav = _convert_currency_amount(
            point.nav,
            from_currency=from_currency,
            to_currency=to_currency,
            usdsgd_rate=rate,
        )
        if converted_nav is None:
            continue
        converted.append(FlexNavPoint(date=point.date, nav=converted_nav))
    return converted


def _convert_flow_schedule_to_currency(
    flows: dict[date, float],
    *,
    from_currency: str,
    to_currency: str,
    fx_history: list[tuple[date, float]] | None,
) -> dict[date, float]:
    if from_currency == to_currency:
        return flows
    if fx_history is None:
        return {}
    converted: dict[date, float] = {}
    for flow_date, amount in flows.items():
        rate = _lookup_fx_rate(fx_history, flow_date)
        if rate is None:
            continue
        converted_amount = _convert_currency_amount(
            amount,
            from_currency=from_currency,
            to_currency=to_currency,
            usdsgd_rate=rate,
        )
        if converted_amount is None:
            continue
        converted[flow_date] = converted.get(flow_date, 0.0) + converted_amount
    return converted


def _rebuild_single_horizon_metrics(
    *,
    nav_points: list[FlexNavPoint],
    explicit_cash_flows: dict[date, float],
    cash_report_summaries: dict[str, FlexCashReportSummary],
    base_currency: str,
    target_currency: str,
    horizon: str,
    as_of: date,
    fx_history: list[tuple[date, float]] | None,
) -> RebuiltHorizonMetrics:
    horizon_start = _horizon_start_date(horizon, as_of=as_of)
    horizon_points = _slice_nav_points_for_horizon(nav_points, horizon_start=horizon_start, as_of=as_of)
    if len(horizon_points) < 2:
        return RebuiltHorizonMetrics(
            money_weighted_pnl=None,
            money_weighted_return=None,
            time_weighted_pnl=None,
            time_weighted_return=None,
            used_explicit_cash_flows=False,
            used_summary_cash_flow=False,
        )

    flow_schedule = {
        flow_date: amount
        for flow_date, amount in explicit_cash_flows.items()
        if horizon_points[0].date < flow_date <= horizon_points[-1].date and abs(amount) > 1e-12
    }
    used_explicit_cash_flows = bool(flow_schedule)
    used_summary_cash_flow = False
    if not flow_schedule:
        summary_flow_schedule = _build_summary_flow_schedule(
            cash_report_summaries=cash_report_summaries,
            base_currency=base_currency,
            target_currency=target_currency,
            horizon=horizon,
            horizon_points=horizon_points,
            as_of=as_of,
            fx_history=fx_history,
        )
        if summary_flow_schedule:
            flow_schedule = summary_flow_schedule
            used_summary_cash_flow = True

    time_weighted_return = _calculate_time_weighted_return(horizon_points, flow_schedule)
    money_weighted_return = _calculate_period_irr_return(horizon_points, flow_schedule)
    start_nav = horizon_points[0].nav
    time_weighted_pnl = (
        start_nav * time_weighted_return
        if time_weighted_return is not None
        else None
    )
    money_weighted_pnl = (
        start_nav * money_weighted_return
        if money_weighted_return is not None
        else None
    )
    return RebuiltHorizonMetrics(
        money_weighted_pnl=money_weighted_pnl,
        money_weighted_return=money_weighted_return,
        time_weighted_pnl=time_weighted_pnl,
        time_weighted_return=time_weighted_return,
        used_explicit_cash_flows=used_explicit_cash_flows,
        used_summary_cash_flow=used_summary_cash_flow,
    )


def _horizon_start_date(horizon: str, *, as_of: date) -> date:
    if horizon == "MTD":
        return _start_of_month(as_of)
    if horizon == "YTD":
        return date(as_of.year, 1, 1)
    if horizon == "1M":
        return _subtract_months(as_of, 1)
    raise ValueError(f"Unsupported horizon: {horizon}")


def _slice_nav_points_for_horizon(
    points: list[FlexNavPoint],
    *,
    horizon_start: date,
    as_of: date,
) -> list[FlexNavPoint]:
    eligible = [point for point in points if point.date <= as_of]
    if len(eligible) < 2:
        return eligible
    opening_index = 0
    for index, point in enumerate(eligible):
        if point.date < horizon_start:
            opening_index = index
            continue
        if index > 0:
            opening_index = index - 1
        break
    return eligible[opening_index:]


def _build_summary_flow_schedule(
    *,
    cash_report_summaries: dict[str, FlexCashReportSummary],
    base_currency: str,
    target_currency: str,
    horizon: str,
    horizon_points: list[FlexNavPoint],
    as_of: date,
    fx_history: list[tuple[date, float]] | None,
) -> dict[date, float]:
    synthetic_date = _pick_synthetic_flow_date(horizon_points)
    if synthetic_date is None:
        return {}

    target_summary = _preferred_cash_summary(
        cash_report_summaries,
        base_currency=base_currency,
        target_currency=target_currency,
    )
    amount = _cash_summary_amount_for_horizon(target_summary, horizon=horizon, as_of=as_of)
    if amount is None and target_currency != base_currency:
        base_summary = _preferred_cash_summary(
            cash_report_summaries,
            base_currency=base_currency,
            target_currency=base_currency,
        )
        base_amount = _cash_summary_amount_for_horizon(base_summary, horizon=horizon, as_of=as_of)
        if base_amount is not None and fx_history is not None:
            rate = _lookup_fx_rate(fx_history, synthetic_date)
            if rate is not None:
                amount = _convert_currency_amount(
                    base_amount,
                    from_currency=base_currency,
                    to_currency=target_currency,
                    usdsgd_rate=rate,
                )
    if amount is None or abs(amount) <= 1e-12:
        return {}
    return {synthetic_date: amount}


def _preferred_cash_summary(
    cash_report_summaries: dict[str, FlexCashReportSummary],
    *,
    base_currency: str,
    target_currency: str,
) -> FlexCashReportSummary | None:
    if target_currency == base_currency:
        return cash_report_summaries.get("BASE_SUMMARY") or cash_report_summaries.get(target_currency)
    return cash_report_summaries.get(target_currency)


def _cash_summary_amount_for_horizon(
    summary: FlexCashReportSummary | None,
    *,
    horizon: str,
    as_of: date,
) -> float | None:
    if summary is None:
        return None
    if horizon == "MTD":
        return summary.deposit_withdrawals_mtd
    if horizon == "YTD":
        return summary.deposit_withdrawals_ytd
    if horizon == "1M":
        if summary.range_start is not None and (as_of - summary.range_start).days <= 35:
            return summary.deposit_withdrawals
        return None
    raise ValueError(f"Unsupported horizon: {horizon}")


def _pick_synthetic_flow_date(points: list[FlexNavPoint]) -> date | None:
    if len(points) < 2:
        return None
    start_date = points[0].date
    end_date = points[-1].date
    midpoint_ordinal = start_date.toordinal() + (max((end_date - start_date).days, 1) / 2.0)
    candidates = points[1:]
    return min(candidates, key=lambda point: abs(point.date.toordinal() - midpoint_ordinal)).date


def _calculate_time_weighted_return(
    points: list[FlexNavPoint],
    flow_schedule: dict[date, float],
) -> float | None:
    if len(points) < 2:
        return None
    product = 1.0
    for previous, current in zip(points, points[1:]):
        if previous.nav == 0:
            return None
        cash_flow = flow_schedule.get(current.date, 0.0)
        period_return = (current.nav - cash_flow) / previous.nav - 1.0
        product *= 1.0 + period_return
    return product - 1.0


def _calculate_period_irr_return(
    points: list[FlexNavPoint],
    flow_schedule: dict[date, float],
) -> float | None:
    if len(points) < 2:
        return None
    start_point = points[0]
    end_point = points[-1]
    if start_point.nav <= 0:
        return None
    if not flow_schedule:
        return (end_point.nav / start_point.nav) - 1.0

    total_days = max((end_point.date - start_point.date).days, 1)
    cashflows = [(-start_point.nav, start_point.date)]
    for flow_date, amount in sorted(flow_schedule.items()):
        cashflows.append((-amount, flow_date))
    cashflows.append((end_point.nav, end_point.date))

    def npv(rate: float) -> float:
        if rate <= -0.999999999:
            return math.inf
        total = 0.0
        for amount, flow_date in cashflows:
            fraction = (flow_date - start_point.date).days / total_days
            total += amount / ((1.0 + rate) ** fraction)
        return total

    bracket = [
        -0.9999,
        -0.99,
        -0.95,
        -0.9,
        -0.75,
        -0.5,
        -0.25,
        -0.1,
        -0.05,
        0.0,
        0.05,
        0.1,
        0.2,
        0.5,
        1.0,
        2.0,
        5.0,
        10.0,
    ]
    bracket_values = [(rate, npv(rate)) for rate in bracket]
    for rate, value in bracket_values:
        if abs(value) <= 1e-12:
            return rate
    low = None
    high = None
    for (left_rate, left_value), (right_rate, right_value) in zip(bracket_values, bracket_values[1:]):
        if not math.isfinite(left_value) or not math.isfinite(right_value):
            continue
        if left_value == 0:
            return left_rate
        if left_value * right_value < 0:
            low = left_rate
            high = right_rate
            break
    if low is None or high is None:
        return None
    for _ in range(120):
        mid = (low + high) / 2.0
        mid_value = npv(mid)
        if abs(mid_value) <= 1e-12:
            return mid
        low_value = npv(low)
        if low_value * mid_value < 0:
            high = mid
        else:
            low = mid
    return (low + high) / 2.0


def _resolve_as_of_date(dataset: FlexPerformanceDataset) -> date:
    if dataset.horizon_rows:
        return dataset.horizon_rows[0].as_of
    return _resolve_as_of_from_daily(dataset.daily_performance)


def _resolve_as_of(
    root: ET.Element,
    *,
    daily_rows: list[FlexDailyPerformanceRow],
    nav_snapshots: list[tuple[date, str, float]],
) -> date:
    if daily_rows:
        return max(row.date for row in daily_rows)
    if nav_snapshots:
        return max(snapshot_date for snapshot_date, _, _ in nav_snapshots)
    statement_as_of = _extract_statement_as_of(root)
    if statement_as_of is not None:
        return statement_as_of
    return datetime.now(timezone.utc).date()


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
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y%m%d;%H%M%S", "%Y-%m-%d;%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
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


def _extract_nav_snapshots(root: ET.Element) -> list[tuple[date, str, float]]:
    snapshots: list[tuple[date, str, float]] = []
    for element in root.iter():
        if _local_name(element.tag).lower() != "equitysummarybyreportdateinbase":
            continue
        snapshot_date = _extract_date(element.attrib)
        currency = str(element.attrib.get("currency", "")).upper()
        total = _parse_float_or_none(element.attrib.get("total"))
        if snapshot_date is None or currency == "" or total is None:
            continue
        snapshots.append((snapshot_date, currency, total))
    return sorted(snapshots, key=lambda item: item[0])


def _extract_statement_as_of(root: ET.Element) -> date | None:
    for element in root.iter():
        if _local_name(element.tag) != "FlexStatement":
            continue
        return _extract_date(element.attrib)
    return None


def _detect_base_currency(root: ET.Element, nav_snapshots: list[tuple[date, str, float]]) -> str | None:
    if nav_snapshots:
        return nav_snapshots[-1][1]
    for element in root.iter():
        currency = str(element.attrib.get("currency", "")).upper()
        if currency in {"USD", "SGD"} and _local_name(element.tag).lower().endswith("inbase"):
            return currency
    return None


def _find_mtdytd_total_row(root: ET.Element) -> ET.Element | None:
    for element in root.iter():
        if _local_name(element.tag) != "MTDYTDPerformanceSummaryUnderlying":
            continue
        if str(element.attrib.get("description", "")).strip().lower() == "total":
            return element
    return None


def _resolve_start_nav_snapshot(
    nav_snapshots: list[tuple[date, str, float]],
    horizon_start: date,
    *,
    currency: str,
) -> tuple[date, float] | None:
    filtered = [(snapshot_date, nav) for snapshot_date, snapshot_currency, nav in nav_snapshots if snapshot_currency == currency]
    if not filtered:
        return None

    prior = [snapshot for snapshot in filtered if snapshot[0] < horizon_start]
    if prior:
        return prior[-1]

    future = [snapshot for snapshot in filtered if snapshot[0] >= horizon_start]
    if future:
        return future[0]
    return None


def _resolve_end_nav_snapshot(
    nav_snapshots: list[tuple[date, str, float]],
    *,
    currency: str,
) -> tuple[date, float] | None:
    filtered = [(snapshot_date, nav) for snapshot_date, snapshot_currency, nav in nav_snapshots if snapshot_currency == currency]
    if not filtered:
        return None
    return filtered[-1]


def _load_usdsgd_history(*, yahoo_client: YahooFinanceClient) -> list[tuple[date, float]] | None:
    cached = _YAHOO_FX_HISTORY_CACHE.get(DEFAULT_USDSGD_YAHOO_SYMBOL)
    if cached is not None:
        return cached

    try:
        history = yahoo_client.fetch_price_history(
            DEFAULT_USDSGD_YAHOO_SYMBOL,
            period=DEFAULT_YAHOO_FX_PERIOD,
            interval=DEFAULT_YAHOO_FX_INTERVAL,
        )
        levels = _extract_history_levels(history)
    except (RuntimeError, ValueError):
        try:
            inverse_history = yahoo_client.fetch_price_history(
                DEFAULT_SGDUSD_YAHOO_SYMBOL,
                period=DEFAULT_YAHOO_FX_PERIOD,
                interval=DEFAULT_YAHOO_FX_INTERVAL,
            )
            inverse_levels = _extract_history_levels(inverse_history)
        except (RuntimeError, ValueError):
            return None
        levels = [
            (level_date, 1.0 / level_value)
            for level_date, level_value in inverse_levels
            if level_value > 0
        ]

    if not levels:
        return None
    _YAHOO_FX_HISTORY_CACHE[DEFAULT_USDSGD_YAHOO_SYMBOL] = levels
    return levels


def _extract_history_levels(history: dict[str, object]) -> list[tuple[date, float]]:
    prices = history.get("prices")
    if not isinstance(prices, list):
        raise ValueError("Yahoo FX history returned no prices")

    levels: list[tuple[date, float]] = []
    for row in prices:
        if not isinstance(row, dict):
            continue
        timestamp = row.get("timestamp")
        level = _parse_float_or_none(row.get("adjclose"))
        if level is None:
            level = _parse_float_or_none(row.get("close"))
        if level is None:
            continue
        try:
            level_date = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date()
        except (TypeError, ValueError):
            continue
        levels.append((level_date, level))
    if not levels:
        raise ValueError("Yahoo FX history returned no usable prices")
    return sorted(levels, key=lambda item: item[0])


def _convert_horizon_metrics_with_fx(
    *,
    base_currency: str,
    target_currency: str,
    pnl_value: float | None,
    start_snapshot: tuple[date, float] | None,
    end_snapshot: tuple[date, float] | None,
    fx_history: list[tuple[date, float]],
) -> tuple[float | None, float | None]:
    if start_snapshot is None or end_snapshot is None:
        return None, None

    start_rate = _lookup_fx_rate(fx_history, start_snapshot[0])
    end_rate = _lookup_fx_rate(fx_history, end_snapshot[0])
    converted_start_nav = (
        _convert_currency_amount(
            start_snapshot[1],
            from_currency=base_currency,
            to_currency=target_currency,
            usdsgd_rate=start_rate,
        )
        if start_rate is not None
        else None
    )
    converted_pnl = (
        _convert_currency_amount(
            pnl_value,
            from_currency=base_currency,
            to_currency=target_currency,
            usdsgd_rate=end_rate,
        )
        if pnl_value is not None and end_rate is not None
        else None
    )
    converted_return = None
    if converted_pnl is not None and converted_start_nav not in (None, 0.0):
        converted_return = converted_pnl / converted_start_nav
    return converted_pnl, converted_return


def _lookup_fx_rate(levels: list[tuple[date, float]], target_date: date) -> float | None:
    prior_rate = None
    for level_date, rate in levels:
        if level_date <= target_date:
            prior_rate = rate
            continue
        return prior_rate if prior_rate is not None else rate
    return prior_rate


def _convert_currency_amount(
    amount: float,
    *,
    from_currency: str,
    to_currency: str,
    usdsgd_rate: float,
) -> float | None:
    if usdsgd_rate <= 0:
        return None
    if from_currency == to_currency:
        return amount
    if from_currency == "USD" and to_currency == "SGD":
        return amount * usdsgd_rate
    if from_currency == "SGD" and to_currency == "USD":
        return amount / usdsgd_rate
    return None


def _derive_nav_delta(start_nav: float | None, end_nav: float | None) -> float | None:
    if start_nav is None or end_nav is None:
        return None
    return end_nav - start_nav


def _start_of_month(value: date) -> date:
    return date(value.year, value.month, 1)


def _subtract_months(value: date, months: int) -> date:
    year = value.year
    month = value.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def _to_csv_number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.10g}"
