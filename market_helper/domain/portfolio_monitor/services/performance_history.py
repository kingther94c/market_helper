from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Sequence
import math
import xml.etree.ElementTree as ET

import pandas as pd

from market_helper.data_sources.ibkr.flex.performance import (
    FlexHorizonPerformanceRow,
    FlexNavPoint,
    _calculate_period_irr_return,
    _convert_currency_amount,
    _detect_base_currency,
    _extract_base_nav_points,
    _extract_nav_snapshots,
    _load_usdsgd_history,
    _lookup_fx_rate,
    _start_of_month,
    _subtract_months,
    parse_flex_performance_xml,
)

if TYPE_CHECKING:
    from market_helper.data_sources.yahoo_finance import YahooFinanceClient


DEFAULT_PERFORMANCE_HISTORY_FILENAME = "performance_history.feather"
PERFORMANCE_HISTORY_COLUMNS = [
    "date",
    "nav_close_usd",
    "nav_close_sgd",
    "cash_flow_usd",
    "cash_flow_sgd",
    "fx_usdsgd_eod",
    "twr_return_usd",
    "twr_return_sgd",
    "is_final",
    "source_kind",
    "source_file",
    "source_as_of",
]
_CURRENCIES = ("USD", "SGD")
_CURRENT_HORIZONS = ("MTD", "YTD", "1M")


@dataclass(frozen=True)
class PerformanceHistorySource:
    path: Path
    source_kind: str
    priority: int
    source_as_of: date | None


def rebuild_performance_history_feather(
    *,
    raw_dir: str | Path,
    output_path: str | Path | None = None,
    yahoo_client: YahooFinanceClient | None = None,
    extra_xml_paths: Sequence[str | Path] | None = None,
) -> Path:
    frame = build_performance_history_frame(
        raw_dir=raw_dir,
        yahoo_client=yahoo_client,
        extra_xml_paths=extra_xml_paths,
    )
    target_path = (
        Path(output_path)
        if output_path is not None
        else Path(raw_dir).parent / DEFAULT_PERFORMANCE_HISTORY_FILENAME
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    frame.loc[:, PERFORMANCE_HISTORY_COLUMNS].reset_index(drop=True).to_feather(target_path)
    return target_path


def load_performance_history(path: str | Path) -> pd.DataFrame:
    frame = pd.read_feather(Path(path))
    return _normalize_history_frame(frame)


def export_performance_history_debug_csv(
    *,
    history_path: str | Path,
    output_path: str | Path,
) -> Path:
    frame = load_performance_history(history_path)
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target_path, index=False)
    return target_path


def build_performance_history_frame(
    *,
    raw_dir: str | Path,
    yahoo_client: YahooFinanceClient | None = None,
    extra_xml_paths: Sequence[str | Path] | None = None,
) -> pd.DataFrame:
    sources = _discover_history_sources(Path(raw_dir), extra_xml_paths=extra_xml_paths)
    frames = [_build_source_history_frame(source, yahoo_client=yahoo_client) for source in sources]
    non_empty_frames = [frame for frame in frames if not frame.empty]
    if not non_empty_frames:
        return _empty_history_frame()

    combined = pd.concat(non_empty_frames, ignore_index=True, sort=False)
    combined["source_as_of_sort"] = pd.to_datetime(combined["source_as_of"], errors="coerce")
    combined = combined.sort_values(
        by=["date", "source_priority", "source_as_of_sort"],
        ascending=[True, True, False],
        kind="stable",
    )
    combined = combined.drop_duplicates(subset=["date"], keep="first")
    combined = combined.drop(columns=["source_priority", "source_as_of_sort"], errors="ignore")
    combined = combined.sort_values("date", kind="stable").reset_index(drop=True)
    return _normalize_history_frame(combined)


def build_horizon_rows_from_performance_history(
    history: pd.DataFrame,
    *,
    archive_start_year: int,
) -> tuple[list[FlexHorizonPerformanceRow], list[int]]:
    normalized = _normalize_history_frame(history)
    if normalized.empty:
        return [], []

    rows: list[FlexHorizonPerformanceRow] = []
    as_of = _history_as_of(normalized)
    if as_of is None:
        return [], []

    current_frame = normalized.loc[normalized["date"] <= pd.Timestamp(as_of)].copy()
    for horizon in _CURRENT_HORIZONS:
        rows.extend(_build_horizon_rows(current_frame, horizon=horizon, as_of=as_of))

    missing_years: list[int] = []
    for year in range(archive_start_year, as_of.year):
        year_rows = normalized.loc[
            (normalized["date"].dt.year == year)
            & normalized["is_final"]
            & (normalized["source_kind"] == "full")
        ].copy()
        if year_rows.empty:
            missing_years.append(year)
            continue
        rows.extend(_build_horizon_rows(normalized, horizon=f"Y{year}", as_of=date(year, 12, 31)))
    return rows, missing_years


def _build_horizon_rows(
    history: pd.DataFrame,
    *,
    horizon: str,
    as_of: date,
) -> list[FlexHorizonPerformanceRow]:
    rows: list[FlexHorizonPerformanceRow] = []
    window = _slice_history_for_horizon(history, horizon=horizon, as_of=as_of)
    for currency in _CURRENCIES:
        metrics = _calculate_horizon_metrics(window, currency=currency)
        if metrics is None:
            rows.extend(
                [
                    FlexHorizonPerformanceRow(
                        as_of=as_of,
                        source_version="PerformanceHistoryFeather",
                        horizon=horizon,
                        weighting="money_weighted",
                        currency=currency,
                        dollar_pnl=None,
                        return_pct=None,
                    ),
                    FlexHorizonPerformanceRow(
                        as_of=as_of,
                        source_version="PerformanceHistoryFeather",
                        horizon=horizon,
                        weighting="time_weighted",
                        currency=currency,
                        dollar_pnl=None,
                        return_pct=None,
                    ),
                ]
            )
            continue

        source_version = "PerformanceHistoryFeather"
        if metrics["uses_simple_fallback"]:
            source_version = f"{source_version}+SimpleNavFallback"
        if metrics["uses_provisional_latest"]:
            source_version = f"{source_version}+ProvisionalLatest"

        rows.extend(
            [
                FlexHorizonPerformanceRow(
                    as_of=as_of,
                    source_version=source_version,
                    horizon=horizon,
                    weighting="money_weighted",
                    currency=currency,
                    dollar_pnl=metrics["money_weighted_pnl"],
                    return_pct=metrics["money_weighted_return"],
                ),
                FlexHorizonPerformanceRow(
                    as_of=as_of,
                    source_version=source_version,
                    horizon=horizon,
                    weighting="time_weighted",
                    currency=currency,
                    dollar_pnl=metrics["time_weighted_pnl"],
                    return_pct=metrics["time_weighted_return"],
                ),
            ]
        )
    return rows


def _calculate_horizon_metrics(history: pd.DataFrame, *, currency: str) -> dict[str, object] | None:
    if history.empty:
        return None

    nav_col = f"nav_close_{currency.lower()}"
    flow_col = f"cash_flow_{currency.lower()}"
    return_col = f"twr_return_{currency.lower()}"
    available = history.loc[history[nav_col].notna(), ["date", nav_col, flow_col, return_col, "is_final"]].copy()
    if len(available) < 2:
        return None

    start_nav = float(available.iloc[0][nav_col])
    end_nav = float(available.iloc[-1][nav_col])
    if start_nav == 0:
        return None

    period_returns = pd.to_numeric(available.iloc[1:][return_col], errors="coerce")
    if period_returns.empty or period_returns.isna().all():
        time_weighted_return = None
    else:
        time_weighted_return = float((1.0 + period_returns.fillna(0.0)).prod() - 1.0)

    flow_schedule: dict[date, float] = {}
    cash_flows = pd.to_numeric(available.iloc[1:][flow_col], errors="coerce")
    for row_date, raw_amount in zip(available.iloc[1:]["date"], cash_flows, strict=False):
        if pd.isna(raw_amount) or abs(float(raw_amount)) <= 1e-12:
            continue
        flow_schedule[pd.Timestamp(row_date).date()] = float(raw_amount)

    nav_points = [
        FlexNavPoint(date=pd.Timestamp(row["date"]).date(), nav=float(row[nav_col]))
        for _, row in available.iterrows()
    ]
    money_weighted_return = _calculate_period_irr_return(nav_points, flow_schedule)

    return {
        "money_weighted_pnl": (
            start_nav * money_weighted_return if money_weighted_return is not None else None
        ),
        "money_weighted_return": money_weighted_return,
        "time_weighted_pnl": (
            start_nav * time_weighted_return if time_weighted_return is not None else None
        ),
        "time_weighted_return": time_weighted_return,
        "uses_provisional_latest": not bool(available.iloc[-1]["is_final"]),
        "uses_simple_fallback": bool(cash_flows.isna().any()),
    }


def _slice_history_for_horizon(
    history: pd.DataFrame,
    *,
    horizon: str,
    as_of: date,
) -> pd.DataFrame:
    if history.empty:
        return history.copy()

    normalized = _normalize_history_frame(history)
    end_ts = pd.Timestamp(as_of)
    if horizon.startswith("Y") and horizon[1:].isdigit():
        year = int(horizon[1:])
        start_date = date(year, 1, 1)
        end_ts = normalized.loc[
            (normalized["date"].dt.year == year) & normalized["is_final"],
            "date",
        ].max()
        if pd.isna(end_ts):
            return normalized.iloc[0:0].copy()
    else:
        start_date = _horizon_start_date(horizon, as_of=as_of)

    eligible = normalized.loc[normalized["date"] <= end_ts].copy()
    if eligible.empty:
        return eligible

    opening = eligible.loc[eligible["date"] < pd.Timestamp(start_date)].tail(1)
    in_window = eligible.loc[eligible["date"] >= pd.Timestamp(start_date)]
    if opening.empty:
        return in_window.reset_index(drop=True)
    return pd.concat([opening, in_window], ignore_index=True)


def _horizon_start_date(horizon: str, *, as_of: date) -> date:
    if horizon == "MTD":
        return _start_of_month(as_of)
    if horizon == "YTD":
        return date(as_of.year, 1, 1)
    if horizon == "1M":
        return _subtract_months(as_of, 1)
    raise ValueError(f"Unsupported horizon: {horizon}")


def _history_as_of(history: pd.DataFrame) -> date | None:
    if history.empty:
        return None
    last_value = history["date"].max()
    if pd.isna(last_value):
        return None
    return pd.Timestamp(last_value).date()


def _build_source_history_frame(
    source: PerformanceHistorySource,
    *,
    yahoo_client: YahooFinanceClient | None,
) -> pd.DataFrame:
    xml_text = source.path.read_text(encoding="utf-8")
    root = ET.fromstring(xml_text)
    dataset = parse_flex_performance_xml(source.path, yahoo_client=yahoo_client)
    nav_snapshots = _extract_nav_snapshots(root)
    base_currency = _detect_base_currency(root, nav_snapshots) or "USD"
    base_nav_points = _extract_base_nav_points(
        daily_rows=dataset.daily_performance,
        nav_snapshots=nav_snapshots,
        base_currency=base_currency,
    )
    if not base_nav_points:
        return _empty_history_frame()

    known_base_flows = {row.date: float(row.cash_flow) for row in dataset.daily_performance}
    fx_history = (
        _load_usdsgd_history(yahoo_client=yahoo_client)
        if yahoo_client is not None and base_currency in {"USD", "SGD"}
        else None
    )
    source_as_of = source.source_as_of or max(point.date for point in base_nav_points)

    by_date: dict[date, dict[str, object]] = {}
    nav_dates = sorted({point.date for point in base_nav_points})
    for point_date in nav_dates:
        by_date[point_date] = {
            "date": point_date,
            "nav_close_usd": math.nan,
            "nav_close_sgd": math.nan,
            "cash_flow_usd": math.nan,
            "cash_flow_sgd": math.nan,
            "fx_usdsgd_eod": math.nan,
            "twr_return_usd": math.nan,
            "twr_return_sgd": math.nan,
            "is_final": not (source.source_kind == "latest" and point_date == nav_dates[-1]),
            "source_kind": source.source_kind,
            "source_file": str(source.path),
            "source_as_of": source_as_of,
            "source_priority": source.priority,
        }

    for currency in _CURRENCIES:
        nav_points = _convert_points_to_currency(
            base_nav_points,
            from_currency=base_currency,
            to_currency=currency,
            fx_history=fx_history,
        )
        known_flows = _convert_known_flows_to_currency(
            known_base_flows,
            from_currency=base_currency,
            to_currency=currency,
            fx_history=fx_history,
        )
        _populate_currency_columns(
            by_date,
            currency=currency,
            nav_points=nav_points,
            known_flows=known_flows,
        )

    for point_date in nav_dates:
        rate = _lookup_fx_rate(fx_history, point_date) if fx_history is not None else None
        if rate is not None:
            by_date[point_date]["fx_usdsgd_eod"] = float(rate)

    return _normalize_history_frame(pd.DataFrame([by_date[key] for key in sorted(by_date)]))


def _populate_currency_columns(
    rows_by_date: dict[date, dict[str, object]],
    *,
    currency: str,
    nav_points: list[FlexNavPoint],
    known_flows: dict[date, float],
) -> None:
    if not nav_points:
        return
    nav_col = f"nav_close_{currency.lower()}"
    flow_col = f"cash_flow_{currency.lower()}"
    return_col = f"twr_return_{currency.lower()}"

    sorted_points = sorted(nav_points, key=lambda point: point.date)
    previous_nav: float | None = None
    for point in sorted_points:
        target_row = rows_by_date.setdefault(
            point.date,
            {
                "date": point.date,
                "nav_close_usd": math.nan,
                "nav_close_sgd": math.nan,
                "cash_flow_usd": math.nan,
                "cash_flow_sgd": math.nan,
                "fx_usdsgd_eod": math.nan,
                "twr_return_usd": math.nan,
                "twr_return_sgd": math.nan,
                "is_final": True,
                "source_kind": "adhoc",
                "source_file": "",
                "source_as_of": point.date,
                "source_priority": 99,
            },
        )
        target_row[nav_col] = float(point.nav)

        known_flow = known_flows.get(point.date)
        if point.date in known_flows:
            target_row[flow_col] = float(known_flow)

        if previous_nav is None or previous_nav == 0:
            previous_nav = float(point.nav)
            continue

        current_nav = float(point.nav)
        if point.date in known_flows:
            target_row[return_col] = ((current_nav - float(known_flow)) / previous_nav) - 1.0
        else:
            target_row[return_col] = (current_nav / previous_nav) - 1.0
        previous_nav = current_nav


def _convert_points_to_currency(
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


def _convert_known_flows_to_currency(
    flows: dict[date, float],
    *,
    from_currency: str,
    to_currency: str,
    fx_history: list[tuple[date, float]] | None,
) -> dict[date, float]:
    if from_currency == to_currency:
        return dict(flows)
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
        converted[flow_date] = float(converted_amount)
    return converted


def _discover_history_sources(
    raw_dir: Path,
    *,
    extra_xml_paths: Sequence[str | Path] | None,
) -> list[PerformanceHistorySource]:
    discovered: dict[Path, PerformanceHistorySource] = {}
    for path in sorted(raw_dir.glob("*.xml")):
        source = _build_source_descriptor(path)
        if source is None:
            continue
        discovered[path.resolve()] = source

    for raw_path in extra_xml_paths or ():
        path = Path(raw_path)
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in discovered:
            continue
        descriptor = _build_source_descriptor(path)
        if descriptor is None:
            metadata = _read_statement_metadata(path)
            descriptor = PerformanceHistorySource(
                path=path,
                source_kind="adhoc",
                priority=1,
                source_as_of=metadata,
            )
        discovered[resolved] = descriptor

    return sorted(
        discovered.values(),
        key=lambda source: (source.priority, source.source_as_of or date.min, str(source.path)),
    )


def _build_source_descriptor(path: Path) -> PerformanceHistorySource | None:
    stem = path.stem
    metadata = _read_statement_metadata(path)
    if "_full" in stem:
        return PerformanceHistorySource(path=path, source_kind="full", priority=0, source_as_of=metadata)
    if "_latest" in stem:
        return PerformanceHistorySource(path=path, source_kind="latest", priority=2, source_as_of=metadata)
    return None


def _read_statement_metadata(path: Path) -> date | None:
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except (ET.ParseError, OSError):
        return None
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "FlexStatement":
            continue
        for key in ("toDate", "reportDate", "date"):
            raw = str(element.attrib.get(key, "")).strip()
            parsed = _parse_statement_date(raw)
            if parsed is not None:
                return parsed
    return None


def _parse_statement_date(raw: str) -> date | None:
    text = raw.strip()
    if text == "":
        return None
    if len(text) == 8 and text.isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _empty_history_frame() -> pd.DataFrame:
    return _normalize_history_frame(pd.DataFrame(columns=[*PERFORMANCE_HISTORY_COLUMNS, "source_priority"]))


def _normalize_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in PERFORMANCE_HISTORY_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.Series(dtype="object")
    if "source_priority" not in normalized.columns:
        normalized["source_priority"] = 99

    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized["source_as_of"] = pd.to_datetime(normalized["source_as_of"], errors="coerce")
    for column in (
        "nav_close_usd",
        "nav_close_sgd",
        "cash_flow_usd",
        "cash_flow_sgd",
        "fx_usdsgd_eod",
        "twr_return_usd",
        "twr_return_sgd",
    ):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized["is_final"] = normalized["is_final"].astype("boolean")
    normalized["source_kind"] = normalized["source_kind"].fillna("").astype(str)
    normalized["source_file"] = normalized["source_file"].fillna("").astype(str)
    normalized["source_priority"] = pd.to_numeric(normalized["source_priority"], errors="coerce").fillna(99).astype(int)
    ordered = [*PERFORMANCE_HISTORY_COLUMNS, "source_priority"]
    return normalized.loc[:, ordered].sort_values("date", kind="stable").reset_index(drop=True)
