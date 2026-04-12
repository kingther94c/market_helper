from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Sequence
import xml.etree.ElementTree as ET

import pandas as pd

from market_helper.data_sources.ibkr.flex.performance import (
    FlexHorizonPerformanceRow,
    FlexNavPoint,
    _calculate_period_irr_return,
    _convert_currency_amount,
    _detect_base_currency,
    _extract_nav_snapshots,
    _load_usdsgd_history,
    _lookup_fx_rate,
    _start_of_month,
    _subtract_months,
)

if TYPE_CHECKING:
    from market_helper.data_sources.yahoo_finance import YahooFinanceClient


DEFAULT_NAV_CASHFLOW_HISTORY_FILENAME = "nav_cashflow_history.feather"
NAV_CASHFLOW_HISTORY_COLUMNS = [
    "date",
    "nav_eod_usd",
    "cashflow_usd",
    "fx_usdsgd_eod",
    "nav_eod_sgd",
    "cashflow_sgd",
    "is_final",
    "pnl_amt_usd",
    "pnl_amt_sgd",
    "pnl_usd",
    "pnl_sgd",
    "source_kind",
    "source_file",
    "source_as_of",
]
_SUPPORTED_CURRENCIES = {"USD", "SGD"}
_CURRENT_HORIZONS = ("MTD", "YTD", "1M")


@dataclass(frozen=True)
class NavCashflowHistorySource:
    path: Path
    source_kind: str
    priority: int
    source_as_of: date | None


@dataclass(frozen=True)
class FlexCashflowEvent:
    event_date: date
    currency: str
    amount: float


@dataclass(frozen=True)
class ClassifiedDepositWithdrawal:
    transaction_type: str
    description: str
    currency: str
    amount: float
    fx_rate_to_base: float | None
    settle_date: date | None
    report_date: date | None
    date_time: str
    event_date: date | None
    classification: str


def rebuild_nav_cashflow_history_feather(
    *,
    raw_dir: str | Path,
    output_path: str | Path | None = None,
    yahoo_client: YahooFinanceClient | None = None,
    extra_xml_paths: Sequence[str | Path] | None = None,
) -> Path:
    frame = build_nav_cashflow_history_frame(
        raw_dir=raw_dir,
        yahoo_client=yahoo_client,
        extra_xml_paths=extra_xml_paths,
    )
    target_path = (
        Path(output_path)
        if output_path is not None
        else Path(raw_dir).parent / DEFAULT_NAV_CASHFLOW_HISTORY_FILENAME
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    frame.loc[:, NAV_CASHFLOW_HISTORY_COLUMNS].reset_index(drop=True).to_feather(target_path)
    return target_path


def load_nav_cashflow_history(path: str | Path) -> pd.DataFrame:
    frame = pd.read_feather(Path(path))
    return _normalize_history_frame(frame)


def export_nav_cashflow_history_debug_csv(
    *,
    history_path: str | Path,
    output_path: str | Path,
) -> Path:
    frame = load_nav_cashflow_history(history_path)
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target_path, index=False)
    return target_path


def extract_classified_deposit_withdrawal_frame(
    path: str | Path,
    *,
    yahoo_client: YahooFinanceClient | None = None,
) -> pd.DataFrame:
    root = ET.fromstring(Path(path).read_text(encoding="utf-8"))
    rows = _classified_dw_frame_from_root(root, yahoo_client=yahoo_client)
    return rows


def export_classified_deposit_withdrawal_debug_csv(
    *,
    xml_path: str | Path,
    output_path: str | Path,
    yahoo_client: YahooFinanceClient | None = None,
) -> Path:
    frame = extract_classified_deposit_withdrawal_frame(xml_path, yahoo_client=yahoo_client)
    target_path = Path(output_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target_path, index=False)
    return target_path


def build_nav_cashflow_history_frame(
    *,
    raw_dir: str | Path,
    yahoo_client: YahooFinanceClient | None = None,
    extra_xml_paths: Sequence[str | Path] | None = None,
) -> pd.DataFrame:
    if yahoo_client is None:
        raise ValueError("yahoo_client is required to build nav_cashflow_history")

    sources = _discover_history_sources(Path(raw_dir), extra_xml_paths=extra_xml_paths)
    frames = [
        _build_source_history_frame(source, yahoo_client=yahoo_client)
        for source in sources
    ]
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


def build_horizon_rows_from_nav_cashflow_history(
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
    for currency in ("USD", "SGD"):
        metrics = _calculate_horizon_metrics(window, currency=currency)
        source_version = "NavCashflowHistoryFeather"
        if metrics is not None and metrics["uses_provisional_latest"]:
            source_version = f"{source_version}+ProvisionalLatest"

        rows.extend(
            [
                FlexHorizonPerformanceRow(
                    as_of=as_of,
                    source_version=source_version,
                    horizon=horizon,
                    weighting="money_weighted",
                    currency=currency,
                    dollar_pnl=None if metrics is None else metrics["money_weighted_pnl"],
                    return_pct=None if metrics is None else metrics["money_weighted_return"],
                ),
                FlexHorizonPerformanceRow(
                    as_of=as_of,
                    source_version=source_version,
                    horizon=horizon,
                    weighting="time_weighted",
                    currency=currency,
                    dollar_pnl=None if metrics is None else metrics["time_weighted_pnl"],
                    return_pct=None if metrics is None else metrics["time_weighted_return"],
                ),
            ]
        )
    return rows


def _calculate_horizon_metrics(history: pd.DataFrame, *, currency: str) -> dict[str, object] | None:
    nav_col = f"nav_eod_{currency.lower()}"
    flow_col = f"cashflow_{currency.lower()}"
    pnl_amt_col = f"pnl_amt_{currency.lower()}"
    pnl_col = f"pnl_{currency.lower()}"

    available = history.loc[
        history[nav_col].notna(),
        ["date", nav_col, flow_col, pnl_amt_col, pnl_col, "is_final"],
    ].copy()
    if len(available) < 2:
        return None

    start_nav = float(available.iloc[0][nav_col])
    if start_nav == 0:
        return None

    returns = pd.to_numeric(available.iloc[1:][pnl_col], errors="coerce")
    if returns.empty or returns.isna().all():
        time_weighted_return = None
    else:
        time_weighted_return = float((1.0 + returns.fillna(0.0)).prod() - 1.0)

    flow_schedule: dict[date, float] = {}
    for row_date, amount in zip(
        available.iloc[1:]["date"],
        pd.to_numeric(available.iloc[1:][flow_col], errors="coerce").fillna(0.0),
        strict=False,
    ):
        if abs(float(amount)) <= 1e-12:
            continue
        flow_schedule[pd.Timestamp(row_date).date()] = float(amount)

    nav_points = [
        FlexNavPoint(date=pd.Timestamp(row["date"]).date(), nav=float(row[nav_col]))
        for _, row in available.iterrows()
    ]
    money_weighted_return = _calculate_period_irr_return(nav_points, flow_schedule)

    pnl_amounts = pd.to_numeric(available.iloc[1:][pnl_amt_col], errors="coerce")
    twr_pnl = None if pnl_amounts.empty or pnl_amounts.isna().all() else float(pnl_amounts.fillna(0.0).sum())

    return {
        "money_weighted_pnl": (
            start_nav * money_weighted_return if money_weighted_return is not None else None
        ),
        "money_weighted_return": money_weighted_return,
        "time_weighted_pnl": twr_pnl,
        "time_weighted_return": time_weighted_return,
        "uses_provisional_latest": not bool(available.iloc[-1]["is_final"]),
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
    source: NavCashflowHistorySource,
    *,
    yahoo_client: YahooFinanceClient,
) -> pd.DataFrame:
    root = ET.fromstring(source.path.read_text(encoding="utf-8"))
    nav_snapshots = _extract_nav_snapshots(root)
    if not nav_snapshots:
        return _empty_history_frame()

    base_currency = _detect_base_currency(root, nav_snapshots)
    if base_currency not in _SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported IBKR Flex base currency: {base_currency}")

    fx_history = _load_usdsgd_history(yahoo_client=yahoo_client)
    if fx_history is None:
        raise ValueError("Unable to load USD/SGD FX history from Yahoo Finance")

    cashflows = _extract_cashflow_events(root)
    source_as_of = source.source_as_of or nav_snapshots[-1][0]
    nav_dates = sorted({snapshot_date for snapshot_date, currency, _ in nav_snapshots if currency == base_currency})
    if not nav_dates:
        return _empty_history_frame()

    cashflow_usd = _aggregate_cashflows_by_date(cashflows, to_currency="USD", fx_history=fx_history)
    cashflow_sgd = _aggregate_cashflows_by_date(cashflows, to_currency="SGD", fx_history=fx_history)

    rows: list[dict[str, object]] = []
    previous_usd: float | None = None
    previous_sgd: float | None = None
    base_nav_by_date = {
        snapshot_date: total
        for snapshot_date, currency, total in nav_snapshots
        if currency == base_currency
    }

    for row_date in nav_dates:
        fx_rate = _lookup_fx_rate(fx_history, row_date)
        if fx_rate is None:
            raise ValueError(f"Missing USD/SGD FX history for {row_date.isoformat()}")

        base_nav = float(base_nav_by_date[row_date])
        if base_currency == "USD":
            nav_usd = base_nav
            nav_sgd = _convert_currency_amount(
                base_nav,
                from_currency="USD",
                to_currency="SGD",
                usdsgd_rate=fx_rate,
            )
        else:
            nav_sgd = base_nav
            nav_usd = _convert_currency_amount(
                base_nav,
                from_currency="SGD",
                to_currency="USD",
                usdsgd_rate=fx_rate,
            )
        if nav_usd is None or nav_sgd is None:
            raise ValueError(f"Unable to convert NAV for {row_date.isoformat()}")

        flow_usd = float(cashflow_usd.get(row_date, 0.0))
        flow_sgd = float(cashflow_sgd.get(row_date, 0.0))
        pnl_amt_usd = None if previous_usd is None else float(nav_usd - previous_usd - flow_usd)
        pnl_amt_sgd = None if previous_sgd is None else float(nav_sgd - previous_sgd - flow_sgd)
        pnl_usd = None if previous_usd in (None, 0.0) else float(pnl_amt_usd / previous_usd)
        pnl_sgd = None if previous_sgd in (None, 0.0) else float(pnl_amt_sgd / previous_sgd)

        rows.append(
            {
                "date": row_date,
                "nav_eod_usd": float(nav_usd),
                "cashflow_usd": flow_usd,
                "fx_usdsgd_eod": float(fx_rate),
                "nav_eod_sgd": float(nav_sgd),
                "cashflow_sgd": flow_sgd,
                "is_final": not (source.source_kind == "latest" and row_date == nav_dates[-1]),
                "pnl_amt_usd": pnl_amt_usd,
                "pnl_amt_sgd": pnl_amt_sgd,
                "pnl_usd": pnl_usd,
                "pnl_sgd": pnl_sgd,
                "source_kind": source.source_kind,
                "source_file": str(source.path),
                "source_as_of": source_as_of,
                "source_priority": source.priority,
            }
        )
        previous_usd = float(nav_usd)
        previous_sgd = float(nav_sgd)

    return _normalize_history_frame(pd.DataFrame(rows))


def _extract_cashflow_events(root: ET.Element) -> list[FlexCashflowEvent]:
    events: list[FlexCashflowEvent] = []
    for row in _extract_classified_deposit_withdrawals(root):
        if row.event_date is None or row.currency not in _SUPPORTED_CURRENCIES:
            if row.currency and row.currency not in _SUPPORTED_CURRENCIES:
                raise ValueError(f"Unsupported IBKR Flex cashflow currency: {row.currency}")
            continue
        events.append(FlexCashflowEvent(event_date=row.event_date, currency=row.currency, amount=row.amount))
    return events


def _extract_classified_deposit_withdrawals(root: ET.Element) -> list[ClassifiedDepositWithdrawal]:
    rows: list[ClassifiedDepositWithdrawal] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].lower() != "cashtransaction":
            continue
        transaction_type = str(element.attrib.get("type", "")).strip()
        if transaction_type.lower() != "deposits/withdrawals":
            continue

        description = str(element.attrib.get("description", "")).strip()
        currency = str(element.attrib.get("currency", "")).strip().upper()
        amount = _parse_float_or_none(element.attrib.get("amount"))
        if amount is None:
            continue

        rows.append(
            ClassifiedDepositWithdrawal(
                transaction_type=transaction_type,
                description=description,
                currency=currency,
                amount=float(amount),
                fx_rate_to_base=_parse_float_or_none(element.attrib.get("fxRateToBase")),
                settle_date=_parse_statement_date(str(element.attrib.get("settleDate", "")).strip()),
                report_date=_parse_statement_date(str(element.attrib.get("reportDate", "")).strip()),
                date_time=str(element.attrib.get("dateTime", "")).strip(),
                event_date=_extract_cashflow_date(element.attrib),
                classification=_classify_deposit_withdrawal_description(description),
            )
        )
    return rows


def _classify_deposit_withdrawal_description(description: str) -> str:
    _ = " ".join(description.strip().upper().split())
    return "DEPOSITS_WITHDRAWALS"


def _classified_dw_frame_from_root(
    root: ET.Element,
    *,
    yahoo_client: YahooFinanceClient | None = None,
) -> pd.DataFrame:
    rows = _extract_classified_deposit_withdrawals(root)
    if not rows:
        return pd.DataFrame(
            columns=[
                "transaction_type",
                "description",
                "classification",
                "currency",
                "amount",
                "fx_rate_to_base",
                "settle_date",
                "report_date",
                "date_time",
                "event_date",
                "is_external_flow",
                "amount_usd",
                "amount_sgd",
            ]
        )

    fx_history = _load_usdsgd_history(yahoo_client=yahoo_client) if yahoo_client is not None else None
    payload: list[dict[str, object]] = []
    for row in rows:
        amount_usd = None
        amount_sgd = None
        if row.currency in _SUPPORTED_CURRENCIES and row.event_date is not None:
            if row.currency == "USD":
                amount_usd = row.amount
                if fx_history is not None:
                    rate = _lookup_fx_rate(fx_history, row.event_date)
                    if rate is not None:
                        amount_sgd = _convert_currency_amount(
                            row.amount,
                            from_currency="USD",
                            to_currency="SGD",
                            usdsgd_rate=rate,
                        )
            elif row.currency == "SGD":
                amount_sgd = row.amount
                if fx_history is not None:
                    rate = _lookup_fx_rate(fx_history, row.event_date)
                    if rate is not None:
                        amount_usd = _convert_currency_amount(
                            row.amount,
                            from_currency="SGD",
                            to_currency="USD",
                            usdsgd_rate=rate,
                        )

        payload.append(
            {
                "transaction_type": row.transaction_type,
                "description": row.description,
                "classification": row.classification,
                "currency": row.currency,
                "amount": row.amount,
                "fx_rate_to_base": row.fx_rate_to_base,
                "settle_date": row.settle_date,
                "report_date": row.report_date,
                "date_time": row.date_time,
                "event_date": row.event_date,
                "is_external_flow": True,
                "amount_usd": amount_usd,
                "amount_sgd": amount_sgd,
            }
        )

    frame = pd.DataFrame(payload)
    for column in ("settle_date", "report_date", "event_date"):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame.sort_values(
        by=["event_date", "settle_date", "report_date", "date_time", "description", "currency", "amount"],
        kind="stable",
    ).reset_index(drop=True)


def _aggregate_cashflows_by_date(
    events: Sequence[FlexCashflowEvent],
    *,
    to_currency: str,
    fx_history: list[tuple[date, float]],
) -> dict[date, float]:
    aggregated: dict[date, float] = {}
    for event in events:
        fx_rate = _lookup_fx_rate(fx_history, event.event_date)
        if fx_rate is None:
            raise ValueError(f"Missing USD/SGD FX history for cashflow date {event.event_date.isoformat()}")
        converted_amount = _convert_currency_amount(
            event.amount,
            from_currency=event.currency,
            to_currency=to_currency,
            usdsgd_rate=fx_rate,
        )
        if converted_amount is None:
            raise ValueError(
                f"Unable to convert cashflow from {event.currency} to {to_currency} on {event.event_date.isoformat()}"
            )
        aggregated[event.event_date] = aggregated.get(event.event_date, 0.0) + float(converted_amount)
    return aggregated


def _extract_cashflow_date(attributes: dict[str, object]) -> date | None:
    for key in ("reportDate", "settleDate", "dateTime"):
        raw = str(attributes.get(key, "")).strip()
        parsed = _parse_statement_date(raw[:10] if key == "dateTime" else raw)
        if parsed is not None:
            return parsed
    return None


def _discover_history_sources(
    raw_dir: Path,
    *,
    extra_xml_paths: Sequence[str | Path] | None,
) -> list[NavCashflowHistorySource]:
    discovered: dict[Path, NavCashflowHistorySource] = {}
    for path in sorted(raw_dir.glob("*.xml")):
        source = _build_source_descriptor(path)
        if source is None:
            source = NavCashflowHistorySource(
                path=path,
                source_kind="adhoc",
                priority=1,
                source_as_of=_read_statement_metadata(path),
            )
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
            descriptor = NavCashflowHistorySource(
                path=path,
                source_kind="adhoc",
                priority=1,
                source_as_of=_read_statement_metadata(path),
            )
        discovered[resolved] = descriptor

    return sorted(
        discovered.values(),
        key=lambda source: (source.priority, source.source_as_of or date.min, str(source.path)),
    )


def _build_source_descriptor(path: Path) -> NavCashflowHistorySource | None:
    stem = path.stem
    metadata = _read_statement_metadata(path)
    if "_full" in stem:
        return NavCashflowHistorySource(path=path, source_kind="full", priority=0, source_as_of=metadata)
    if "_latest" in stem:
        return NavCashflowHistorySource(path=path, source_kind="latest", priority=2, source_as_of=metadata)
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


def _parse_float_or_none(raw: object) -> float | None:
    text = str(raw).replace(",", "").strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _empty_history_frame() -> pd.DataFrame:
    return _normalize_history_frame(pd.DataFrame(columns=[*NAV_CASHFLOW_HISTORY_COLUMNS, "source_priority"]))


def _normalize_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    for column in NAV_CASHFLOW_HISTORY_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.Series(dtype="object")
    if "source_priority" not in normalized.columns:
        normalized["source_priority"] = 99

    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce")
    normalized["source_as_of"] = pd.to_datetime(normalized["source_as_of"], errors="coerce")
    for column in (
        "nav_eod_usd",
        "cashflow_usd",
        "fx_usdsgd_eod",
        "nav_eod_sgd",
        "cashflow_sgd",
        "pnl_amt_usd",
        "pnl_amt_sgd",
        "pnl_usd",
        "pnl_sgd",
    ):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized["is_final"] = normalized["is_final"].astype("boolean")
    normalized["source_kind"] = normalized["source_kind"].fillna("").astype(str)
    normalized["source_file"] = normalized["source_file"].fillna("").astype(str)
    normalized["source_priority"] = pd.to_numeric(normalized["source_priority"], errors="coerce").fillna(99).astype(int)
    ordered = [*NAV_CASHFLOW_HISTORY_COLUMNS, "source_priority"]
    return normalized.loc[:, ordered].sort_values("date", kind="stable").reset_index(drop=True)
