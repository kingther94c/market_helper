from __future__ import annotations

"""Pipeline entrypoints for portfolio-monitor reporting flows."""

from collections import deque
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import TYPE_CHECKING
import warnings
import xml.etree.ElementTree as ET
import yaml

from market_helper.common.models import (
    DEFAULT_SECURITY_REFERENCE_PATH,
    PortfolioPositionSnapshot,
    PortfolioPriceSnapshot,
    SecurityReference,
    SecurityMapping,
    SecurityReferenceTable,
    build_security_reference_table,
    build_price_lookup,
    export_security_reference_csv,
    export_security_universe_proposal_csv,
    sync_security_reference_csv,
)
from market_helper.common.progress import ProgressReporter, resolve_progress_reporter
from market_helper.data_sources.ibkr.adapters import (
    normalize_ibkr_latest_prices,
    normalize_ibkr_positions,
)
from market_helper.data_sources.ibkr.flex import (
    FlexPerformanceDataset,
    export_flex_horizon_report_csv,
    parse_flex_performance_xml,
)
from market_helper.data_sources.ibkr.flex.performance import FlexHorizonPerformanceRow
from market_helper.providers.flex import (
    DEFAULT_IBKR_FLEX_MAX_ATTEMPTS,
    DEFAULT_IBKR_FLEX_POLL_INTERVAL_SECONDS,
    FlexWebServiceClient,
    FlexWebServicePendingError,
)
from market_helper.data_sources.ibkr.tws import (
    TwsIbAsyncClient,
    account_values_to_ibkr_cash_position_rows,
    choose_tws_account,
    portfolio_items_to_ibkr_position_rows,
    portfolio_items_to_ibkr_price_rows,
)
from market_helper.domain.portfolio_monitor.services.etf_sector_lookthrough import (
    sync_us_sector_lookthrough,
)
from market_helper.domain.portfolio_monitor.services.nav_cashflow_history import (
    DEFAULT_NAV_CASHFLOW_HISTORY_FILENAME,
    build_horizon_rows_from_nav_cashflow_history,
    load_nav_cashflow_history,
    rebuild_nav_cashflow_history_feather,
)
from market_helper.presentation.exporters.csv import export_position_report_csv
from market_helper.presentation.exporters.security_reference_seed import (
    export_security_reference_seed_csv,
    extract_security_reference_seed,
)
from market_helper.presentation.tables.portfolio_report import (
    PositionReportRow,
    build_position_report_rows,
)
from market_helper.portfolio.ibkr import enrich_security_from_contract_details

if TYPE_CHECKING:
    from market_helper.data_sources.yahoo_finance import YahooFinanceClient

DEFAULT_IBKR_FLEX_ARCHIVE_START_YEAR = 2020
DEFAULT_IBKR_FLEX_BACKFILL_MAX_INFLIGHT_REQUESTS = 3
DEFAULT_PREVIOUS_FULL_YEAR_MAX_ATTEMPTS_MULTIPLIER = 2
DEFAULT_GOOGLE_DRIVE_POSITIONS_FILENAME = "live_ibkr_position_report.csv"
DEFAULT_GOOGLE_DRIVE_COMBINED_REPORT_FILENAME = "portfolio_combined_report.html"


@dataclass(frozen=True)
class LiveIbkrRowSource:
    raw_position: dict[str, object]
    portfolio_item: object | None = None


@dataclass(frozen=True)
class FlexArchiveRecord:
    year: int
    kind: str
    target_path: Path
    status: str
    error_message: str | None = None
    source_file: Path | None = None
    xml_from_date: date | None = None
    xml_to_date: date | None = None


@dataclass(frozen=True)
class FlexStatementMetadata:
    from_date: date | None
    to_date: date | None
    period: str
    when_generated: str
    account_id: str


@dataclass(frozen=True)
class _PendingFlexArchiveFetch:
    year: int
    target_path: Path
    success_status: str


@dataclass
class _InflightFlexArchiveFetch:
    pending: _PendingFlexArchiveFetch
    reference_code: str
    attempts: int = 0


class FlexBackfillBatchError(RuntimeError):
    def __init__(self, *, records: list[FlexArchiveRecord], failed_years: list[int]):
        self.records = list(records)
        self.failed_years = list(failed_years)
        years = ", ".join(str(year) for year in failed_years)
        super().__init__(f"IBKR Flex historical backfill failed for years: {years}")


def generate_ibkr_flex_performance_report(
    *,
    output_dir: str | Path,
    flex_xml_path: str | Path | None = None,
    query_id: str | None = None,
    token: str | None = None,
    from_date: date | str | None = None,
    to_date: date | str | None = None,
    period: str | None = None,
    xml_output_path: str | Path | None = None,
    poll_interval_seconds: float = DEFAULT_IBKR_FLEX_POLL_INTERVAL_SECONDS,
    max_attempts: int = DEFAULT_IBKR_FLEX_MAX_ATTEMPTS,
    client: object | None = None,
    yahoo_client: YahooFinanceClient | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    """Convert either a local Flex XML or a live Flex query into a dated CSV."""
    reporter = resolve_progress_reporter(progress)
    total_steps = 5
    current_step = 0
    reporter.stage("IBKR Flex report", current=current_step, total=total_steps)
    cleanup_path = None
    raw_dir = _flex_raw_archive_dir(output_dir)
    history_path = _nav_cashflow_history_path(output_dir)
    if flex_xml_path is not None:
        resolved_flex_xml_path = Path(flex_xml_path)
    else:
        normalized_query_id, normalized_token = _normalize_live_flex_credentials(
            query_id=query_id,
            token=token,
        )
        flex_client = client or FlexWebServiceClient(token=normalized_token)
        resolved_today = _current_local_date()
        if _uses_default_current_ytd_request(from_date=from_date, to_date=to_date, period=period):
            previous_year = resolved_today.year - 1
            if previous_year >= DEFAULT_IBKR_FLEX_ARCHIVE_START_YEAR:
                _ensure_full_year_archive(
                    raw_dir=raw_dir,
                    year=previous_year,
                    query_id=normalized_query_id,
                    flex_client=flex_client,
                    poll_interval_seconds=poll_interval_seconds,
                    max_attempts=max_attempts * DEFAULT_PREVIOUS_FULL_YEAR_MAX_ATTEMPTS_MULTIPLIER,
                    overwrite_existing=False,
                )
            latest_record = refresh_current_year_latest_flex_xml(
                output_dir=output_dir,
                query_id=normalized_query_id,
                token=normalized_token,
                xml_output_path=xml_output_path,
                poll_interval_seconds=poll_interval_seconds,
                max_attempts=max_attempts,
                client=flex_client,
                today=resolved_today,
            )
            resolved_flex_xml_path = latest_record.target_path
        else:
            resolved_flex_xml_path, cleanup_path = _resolve_flex_xml_path(
                output_dir=output_dir,
                query_id=normalized_query_id,
                token=normalized_token,
                from_date=from_date,
                to_date=to_date,
                period=period,
                xml_output_path=xml_output_path,
                poll_interval_seconds=poll_interval_seconds,
                max_attempts=max_attempts,
                client=flex_client,
            )
    current_step += 1
    reporter.stage("IBKR Flex report: XML ready", current=current_step, total=total_steps)
    try:
        resolved_yahoo_client = yahoo_client
        if resolved_yahoo_client is None:
            from market_helper.data_sources.yahoo_finance import YahooFinanceClient as _YahooFinanceClient

            resolved_yahoo_client = _YahooFinanceClient()
        dataset = parse_flex_performance_xml(
            resolved_flex_xml_path,
            yahoo_client=resolved_yahoo_client,
        )
        current_step += 1
        reporter.stage("IBKR Flex report: XML parsed", current=current_step, total=total_steps)
        history_extra_paths = _history_extra_xml_paths(
            raw_dir=raw_dir,
            resolved_flex_xml_path=resolved_flex_xml_path,
        )
        rebuilt_history_path = rebuild_nav_cashflow_history_feather(
            raw_dir=raw_dir,
            output_path=history_path,
            yahoo_client=resolved_yahoo_client,
            extra_xml_paths=history_extra_paths,
        )
        current_step += 1
        reporter.stage("IBKR Flex report: history rebuilt", current=current_step, total=total_steps)
        history_frame = load_nav_cashflow_history(rebuilt_history_path)
        history_rows, history_missing_years = build_horizon_rows_from_nav_cashflow_history(
            history_frame,
            archive_start_year=DEFAULT_IBKR_FLEX_ARCHIVE_START_YEAR,
        )
        report_year = _resolve_dataset_report_year(dataset)
        historical_rows, xml_missing_years = _load_historical_annual_horizon_rows(
            raw_dir=raw_dir,
            current_year=report_year,
            yahoo_client=resolved_yahoo_client,
        )
        missing_years = sorted(set(history_missing_years) | set(xml_missing_years))
        if missing_years:
            warnings.warn(
                "Missing full-year IBKR Flex archives for: {years}".format(
                    years=", ".join(str(year) for year in missing_years)
                ),
                stacklevel=2,
            )
        fallback_rows = [*dataset.horizon_rows, *historical_rows]
        final_horizon_rows = _merge_horizon_rows_by_key(primary=history_rows, fallback=fallback_rows)
        if final_horizon_rows:
            dataset = FlexPerformanceDataset(
                daily_performance=dataset.daily_performance,
                cash_flows=dataset.cash_flows,
                horizon_rows=final_horizon_rows,
            )
        current_step += 1
        reporter.stage("IBKR Flex report: horizons merged", current=current_step, total=total_steps)
        output_path = export_flex_horizon_report_csv(dataset, output_dir=output_dir)
        reporter.done("IBKR Flex report", detail=f"wrote {output_path}")
        return output_path
    finally:
        if cleanup_path is not None and cleanup_path.exists():
            cleanup_path.unlink()


def rebuild_ibkr_flex_nav_cashflow_history(
    *,
    output_dir: str | Path,
    yahoo_client: YahooFinanceClient | None = None,
    extra_xml_paths: list[str | Path] | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    raw_dir = _flex_raw_archive_dir(output_dir)
    reporter = resolve_progress_reporter(progress)
    reporter.spinner("IBKR Flex history", detail="rebuilding feather history")
    resolved_yahoo_client = yahoo_client
    if resolved_yahoo_client is None:
        from market_helper.data_sources.yahoo_finance import YahooFinanceClient as _YahooFinanceClient

        resolved_yahoo_client = _YahooFinanceClient()
    output_path = rebuild_nav_cashflow_history_feather(
        raw_dir=raw_dir,
        output_path=_nav_cashflow_history_path(output_dir),
        yahoo_client=resolved_yahoo_client,
        extra_xml_paths=extra_xml_paths,
    )
    reporter.done("IBKR Flex history", detail=f"wrote {output_path}")
    return output_path


def _resolve_flex_xml_path(
    *,
    output_dir: str | Path,
    query_id: str,
    token: str,
    from_date: date | str | None,
    to_date: date | str | None,
    period: str | None,
    xml_output_path: str | Path | None,
    poll_interval_seconds: float,
    max_attempts: int,
    client: object | None,
) -> tuple[Path, Path | None]:
    flex_client = client or FlexWebServiceClient(token=token)
    fetch_statement = getattr(flex_client, "fetch_statement")
    statement_xml = str(
        fetch_statement(
            query_id,
            from_date=from_date,
            to_date=to_date,
            period=period,
            poll_interval_seconds=poll_interval_seconds,
            max_attempts=max_attempts,
        )
    )
    if xml_output_path is None:
        return _write_downloaded_flex_xml(statement_xml, xml_output_path=None)
    return _write_downloaded_flex_xml(statement_xml, xml_output_path=xml_output_path)


def _write_downloaded_flex_xml(
    statement_xml: str,
    *,
    xml_output_path: str | Path | None,
) -> tuple[Path, Path | None]:
    if xml_output_path is not None:
        target_path = Path(xml_output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(statement_xml, encoding="utf-8")
        return target_path, None

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".xml",
        delete=False,
    ) as handle:
        handle.write(statement_xml)
        temp_path = Path(handle.name)
    return temp_path, temp_path


def backfill_ibkr_flex_full_years(
    *,
    output_dir: str | Path,
    query_id: str,
    token: str,
    start_year: int,
    end_year: int,
    overwrite_existing: bool = False,
    poll_interval_seconds: float = DEFAULT_IBKR_FLEX_POLL_INTERVAL_SECONDS,
    max_attempts: int = DEFAULT_IBKR_FLEX_MAX_ATTEMPTS,
    max_inflight_requests: int = DEFAULT_IBKR_FLEX_BACKFILL_MAX_INFLIGHT_REQUESTS,
    client: object | None = None,
    progress: ProgressReporter | None = None,
) -> list[FlexArchiveRecord]:
    reporter = resolve_progress_reporter(progress)
    normalized_query_id, normalized_token = _normalize_live_flex_credentials(
        query_id=query_id,
        token=token,
    )
    flex_client = client or FlexWebServiceClient(token=normalized_token)
    raw_dir = _flex_raw_archive_dir(output_dir)
    ordered_years = list(range(start_year, end_year + 1))
    reporter.stage("Flex backfill", current=0, total=len(ordered_years))
    records_by_year: dict[int, FlexArchiveRecord] = {}
    pending_fetches: list[_PendingFlexArchiveFetch] = []
    completed_years = 0

    for year in ordered_years:
        preflight_record, pending_fetch = _preflight_full_year_archive(
            raw_dir=raw_dir,
            year=year,
            overwrite_existing=overwrite_existing,
        )
        if preflight_record is not None:
            records_by_year[year] = preflight_record
            completed_years += 1
            reporter.update(
                "Flex backfill",
                completed=completed_years,
                total=len(ordered_years),
                detail=f"{year} {preflight_record.status}",
            )
            continue
        if pending_fetch is not None:
            pending_fetches.append(pending_fetch)

    if pending_fetches:
        fetched_records = _backfill_full_year_archives_batch(
            flex_client=flex_client,
            query_id=normalized_query_id,
            pending_fetches=pending_fetches,
            poll_interval_seconds=poll_interval_seconds,
            max_attempts=max_attempts,
            max_inflight_requests=max_inflight_requests,
            progress=reporter.child("Batch polling"),
        )
        records_by_year.update({record.year: record for record in fetched_records})
        for record in fetched_records:
            completed_years += 1
            reporter.update(
                "Flex backfill",
                completed=completed_years,
                total=len(ordered_years),
                detail=f"{record.year} {record.status}",
            )

    ordered_records = [records_by_year[year] for year in ordered_years]
    failed_years = [record.year for record in ordered_records if record.status == "failed"]
    if failed_years:
        raise FlexBackfillBatchError(records=ordered_records, failed_years=failed_years)
    reporter.done("Flex backfill", detail=f"{len(ordered_records)} years processed")
    return ordered_records


def _preflight_full_year_archive(
    *,
    raw_dir: Path,
    year: int,
    overwrite_existing: bool,
) -> tuple[FlexArchiveRecord | None, _PendingFlexArchiveFetch | None]:
    target_path = _full_year_archive_path(raw_dir, year)
    if target_path.exists() and not overwrite_existing:
        return (
            FlexArchiveRecord(
                year=year,
                kind="full",
                target_path=target_path,
                status="skipped",
            ),
            None,
        )

    if target_path.exists() and overwrite_existing:
        return None, _PendingFlexArchiveFetch(year=year, target_path=target_path, success_status="overwritten")

    promoted_path, promoted_source, promoted_metadata = _promote_existing_full_year_candidate(
        raw_dir=raw_dir,
        year=year,
        target_path=target_path,
    )
    if promoted_path is not None:
        return (
            FlexArchiveRecord(
                year=year,
                kind="full",
                target_path=promoted_path,
                status="promoted",
                source_file=promoted_source,
                xml_from_date=promoted_metadata.from_date if promoted_metadata is not None else None,
                xml_to_date=promoted_metadata.to_date if promoted_metadata is not None else None,
            ),
            None,
        )

    return None, _PendingFlexArchiveFetch(year=year, target_path=target_path, success_status="downloaded")


def _backfill_full_year_archives_batch(
    *,
    flex_client: object,
    query_id: str,
    pending_fetches: list[_PendingFlexArchiveFetch],
    poll_interval_seconds: float,
    max_attempts: int,
    max_inflight_requests: int,
    progress: ProgressReporter | None = None,
) -> list[FlexArchiveRecord]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    if poll_interval_seconds < 0:
        raise ValueError("poll_interval_seconds must be >= 0")
    if max_inflight_requests < 1:
        raise ValueError("max_inflight_requests must be >= 1")

    send_request = getattr(flex_client, "send_request", None)
    get_statement = getattr(flex_client, "get_statement", None)
    if not callable(send_request) or not callable(get_statement):
        raise TypeError("Historical Flex backfill batching requires a client with send_request() and get_statement()")

    completed_records: dict[int, FlexArchiveRecord] = {}
    inflight_requests: list[_InflightFlexArchiveFetch] = []
    queued_fetches = deque(pending_fetches)

    def top_up_inflight() -> None:
        while queued_fetches and len(inflight_requests) < max_inflight_requests:
            pending_fetch = queued_fetches.popleft()
            try:
                reference_code = str(
                    send_request(
                        query_id,
                        from_date=date(pending_fetch.year, 1, 1),
                        to_date=date(pending_fetch.year, 12, 31),
                    )
                )
            except Exception as error:
                completed_records[pending_fetch.year] = _failed_flex_archive_record(
                    pending_fetch=pending_fetch,
                    error_message=str(error),
                )
                continue
            inflight_requests.append(
                _InflightFlexArchiveFetch(
                    pending=pending_fetch,
                    reference_code=reference_code,
                )
            )

    top_up_inflight()
    while inflight_requests:
        if progress is not None:
            progress.spinner(
                "Flex polling",
                detail=f"inflight={len(inflight_requests)} queued={len(queued_fetches)}",
            )
        next_round_requests: list[_InflightFlexArchiveFetch] = []
        for inflight in inflight_requests:
            inflight.attempts += 1
            try:
                statement_xml = str(get_statement(inflight.reference_code))
            except FlexWebServicePendingError as error:
                if progress is not None:
                    progress.spinner(
                        "Flex polling",
                        detail=f"{inflight.pending.year} attempt {inflight.attempts}/{max_attempts}",
                    )
                if inflight.attempts >= max_attempts:
                    completed_records[inflight.pending.year] = _failed_flex_archive_record(
                        pending_fetch=inflight.pending,
                        error_message=_batch_polling_timeout_message(
                            last_error=error,
                            max_attempts=max_attempts,
                            poll_interval_seconds=poll_interval_seconds,
                        ),
                    )
                    continue
                next_round_requests.append(inflight)
                continue
            except Exception as error:
                completed_records[inflight.pending.year] = _failed_flex_archive_record(
                    pending_fetch=inflight.pending,
                    error_message=str(error),
                )
                continue

            metadata = _parse_statement_metadata(statement_xml)
            _write_statement_xml(inflight.pending.target_path, statement_xml)
            completed_records[inflight.pending.year] = FlexArchiveRecord(
                year=inflight.pending.year,
                kind="full",
                target_path=inflight.pending.target_path,
                status=inflight.pending.success_status,
                xml_from_date=metadata.from_date,
                xml_to_date=metadata.to_date,
            )
            if progress is not None:
                progress.spinner(
                    "Flex polling",
                    detail=f"{inflight.pending.year} {inflight.pending.success_status}",
                )

        unresolved_requests_remain = bool(next_round_requests)
        inflight_requests = next_round_requests
        top_up_inflight()
        if unresolved_requests_remain and inflight_requests:
            _flex_batch_sleep(flex_client, poll_interval_seconds)

    return [completed_records[pending_fetch.year] for pending_fetch in pending_fetches]


def _failed_flex_archive_record(
    *,
    pending_fetch: _PendingFlexArchiveFetch,
    error_message: str,
) -> FlexArchiveRecord:
    return FlexArchiveRecord(
        year=pending_fetch.year,
        kind="full",
        target_path=pending_fetch.target_path,
        status="failed",
        error_message=error_message,
    )


def _batch_polling_timeout_message(
    *,
    last_error: FlexWebServicePendingError,
    max_attempts: int,
    poll_interval_seconds: float,
) -> str:
    total_wait_seconds = poll_interval_seconds * max(max_attempts - 1, 0)
    return (
        f"{last_error}. Polling exhausted after {max_attempts} attempts "
        f"(~{total_wait_seconds:.0f}s wait). Increase poll_interval_seconds/max_attempts "
        "for large or historical Flex queries."
    )


def _flex_batch_sleep(flex_client: object, seconds: float) -> None:
    sleeper = getattr(flex_client, "sleep", None)
    if callable(sleeper):
        sleeper(seconds)
        return
    time.sleep(seconds)


def refresh_current_year_latest_flex_xml(
    *,
    output_dir: str | Path,
    query_id: str,
    token: str,
    xml_output_path: str | Path | None = None,
    poll_interval_seconds: float = DEFAULT_IBKR_FLEX_POLL_INTERVAL_SECONDS,
    max_attempts: int = DEFAULT_IBKR_FLEX_MAX_ATTEMPTS,
    client: object | None = None,
    today: date | None = None,
) -> FlexArchiveRecord:
    normalized_query_id, normalized_token = _normalize_live_flex_credentials(
        query_id=query_id,
        token=token,
    )
    resolved_today = today or _current_local_date()
    resolved_to_date = _previous_weekday(resolved_today)
    year = resolved_to_date.year
    target_path = (
        Path(xml_output_path)
        if xml_output_path is not None
        else _latest_year_archive_path(_flex_raw_archive_dir(output_dir), year)
    )
    flex_client = client or FlexWebServiceClient(token=normalized_token)
    statement_xml = str(
        getattr(flex_client, "fetch_statement")(
            normalized_query_id,
            from_date=date(year, 1, 1),
            to_date=resolved_to_date,
            poll_interval_seconds=poll_interval_seconds,
            max_attempts=max_attempts,
        )
    )
    metadata = _parse_statement_metadata(statement_xml)
    _write_statement_xml(target_path, statement_xml)
    return FlexArchiveRecord(
        year=year,
        kind="latest",
        target_path=target_path,
        status="refreshed",
        xml_from_date=metadata.from_date,
        xml_to_date=metadata.to_date,
    )


def _normalize_live_flex_credentials(*, query_id: str | None, token: str | None) -> tuple[str, str]:
    normalized_query_id = str(query_id or "").strip()
    normalized_token = str(token or "").strip()
    if not normalized_query_id:
        raise ValueError("query_id is required when flex_xml_path is not provided")
    if not normalized_token:
        raise ValueError("token is required when flex_xml_path is not provided")
    return normalized_query_id, normalized_token


def _current_local_date() -> date:
    return date.today()


def _previous_weekday(value: date) -> date:
    resolved = value
    while True:
        resolved = resolved - timedelta(days=1)
        if resolved.weekday() < 5:
            return resolved


def _uses_default_current_ytd_request(
    *,
    from_date: date | str | None,
    to_date: date | str | None,
    period: str | None,
) -> bool:
    return from_date is None and to_date is None and str(period or "").strip() == ""


def _nav_cashflow_history_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / DEFAULT_NAV_CASHFLOW_HISTORY_FILENAME


def _history_extra_xml_paths(
    *,
    raw_dir: Path,
    resolved_flex_xml_path: Path,
) -> list[Path]:
    try:
        resolved_raw_dir = raw_dir.resolve()
        resolved_xml = resolved_flex_xml_path.resolve()
    except OSError:
        return [resolved_flex_xml_path]
    if resolved_xml.parent == resolved_raw_dir:
        return []
    return [resolved_flex_xml_path]


def _flex_raw_archive_dir(output_dir: str | Path) -> Path:
    raw_dir = Path(output_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir


def _full_year_archive_path(raw_dir: Path, year: int) -> Path:
    return raw_dir / f"ibkr_flex_{year}_full.xml"


def _latest_year_archive_path(raw_dir: Path, year: int) -> Path:
    return raw_dir / f"ibkr_flex_{year}_latest.xml"


def _ensure_full_year_archive(
    *,
    raw_dir: Path,
    year: int,
    query_id: str,
    flex_client: object,
    poll_interval_seconds: float,
    max_attempts: int,
    overwrite_existing: bool,
) -> FlexArchiveRecord:
    target_path = _full_year_archive_path(raw_dir, year)
    if target_path.exists() and not overwrite_existing:
        return FlexArchiveRecord(
            year=year,
            kind="full",
            target_path=target_path,
            status="skipped",
        )

    if target_path.exists() and overwrite_existing:
        metadata = _fetch_year_statement_to_path(
            flex_client=flex_client,
            query_id=query_id,
            year=year,
            target_path=target_path,
            poll_interval_seconds=poll_interval_seconds,
            max_attempts=max_attempts,
        )
        return FlexArchiveRecord(
            year=year,
            kind="full",
            target_path=target_path,
            status="overwritten",
            xml_from_date=metadata.from_date,
            xml_to_date=metadata.to_date,
        )

    promoted_path, promoted_source, promoted_metadata = _promote_existing_full_year_candidate(
        raw_dir=raw_dir,
        year=year,
        target_path=target_path,
    )
    if promoted_path is not None:
        return FlexArchiveRecord(
            year=year,
            kind="full",
            target_path=promoted_path,
            status="promoted",
            source_file=promoted_source,
            xml_from_date=promoted_metadata.from_date if promoted_metadata is not None else None,
            xml_to_date=promoted_metadata.to_date if promoted_metadata is not None else None,
        )

    metadata = _fetch_year_statement_to_path(
        flex_client=flex_client,
        query_id=query_id,
        year=year,
        target_path=target_path,
        poll_interval_seconds=poll_interval_seconds,
        max_attempts=max_attempts,
    )
    return FlexArchiveRecord(
        year=year,
        kind="full",
        target_path=target_path,
        status="downloaded",
        xml_from_date=metadata.from_date,
        xml_to_date=metadata.to_date,
    )


def _fetch_year_statement_to_path(
    *,
    flex_client: object,
    query_id: str,
    year: int,
    target_path: Path,
    poll_interval_seconds: float,
    max_attempts: int,
) -> FlexStatementMetadata:
    statement_xml = str(
        getattr(flex_client, "fetch_statement")(
            query_id,
            from_date=date(year, 1, 1),
            to_date=date(year, 12, 31),
            poll_interval_seconds=poll_interval_seconds,
            max_attempts=max_attempts,
        )
    )
    metadata = _parse_statement_metadata(statement_xml)
    _write_statement_xml(target_path, statement_xml)
    return metadata


def _promote_existing_full_year_candidate(
    *,
    raw_dir: Path,
    year: int,
    target_path: Path,
) -> tuple[Path | None, Path | None, FlexStatementMetadata | None]:
    for candidate in sorted(raw_dir.glob("*.xml")):
        if candidate == target_path:
            continue
        if "_full" in candidate.stem:
            continue
        metadata = _read_statement_metadata(candidate)
        if metadata is None or not _covers_full_year(metadata, year):
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target_path)
        return target_path, candidate, metadata
    return None, None, None


def _load_historical_annual_horizon_rows(
    *,
    raw_dir: Path,
    current_year: int,
    yahoo_client: YahooFinanceClient | None = None,
) -> tuple[list[FlexHorizonPerformanceRow], list[int]]:
    rows: list[FlexHorizonPerformanceRow] = []
    missing_years: list[int] = []
    for year in range(DEFAULT_IBKR_FLEX_ARCHIVE_START_YEAR, current_year):
        full_path = _full_year_archive_path(raw_dir, year)
        if not full_path.exists():
            promoted_path, _, _ = _promote_existing_full_year_candidate(
                raw_dir=raw_dir,
                year=year,
                target_path=full_path,
            )
            if promoted_path is None:
                missing_years.append(year)
                continue
        annual_dataset = parse_flex_performance_xml(full_path, yahoo_client=yahoo_client)
        for row in annual_dataset.horizon_rows:
            if row.horizon != "YTD":
                continue
            rows.append(
                FlexHorizonPerformanceRow(
                    as_of=row.as_of,
                    source_version=f"{row.source_version}+HistoricalYear",
                    horizon=f"Y{year}",
                    weighting=row.weighting,
                    currency=row.currency,
                    dollar_pnl=row.dollar_pnl,
                    return_pct=row.return_pct,
                )
            )
    return rows, missing_years


def _merge_horizon_rows_by_key(
    *,
    primary: list[FlexHorizonPerformanceRow],
    fallback: list[FlexHorizonPerformanceRow],
) -> list[FlexHorizonPerformanceRow]:
    if not primary:
        return fallback
    fallback_map = {
        (row.horizon, row.weighting, row.currency): row
        for row in fallback
    }
    merged: list[FlexHorizonPerformanceRow] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for row in primary:
        key = (row.horizon, row.weighting, row.currency)
        seen_keys.add(key)
        fallback_row = fallback_map.get(key)
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
    for row in fallback:
        key = (row.horizon, row.weighting, row.currency)
        if key in seen_keys:
            continue
        merged.append(row)
    return merged


def _resolve_dataset_report_year(dataset: FlexPerformanceDataset) -> int:
    if dataset.horizon_rows:
        return max(row.as_of for row in dataset.horizon_rows).year
    if dataset.daily_performance:
        return max(row.date for row in dataset.daily_performance).year
    return _current_local_date().year


def _write_statement_xml(target_path: Path, statement_xml: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(statement_xml, encoding="utf-8")


def _read_statement_metadata(path: Path) -> FlexStatementMetadata | None:
    try:
        return _parse_statement_metadata(path.read_text(encoding="utf-8"))
    except (OSError, ET.ParseError, RuntimeError):
        return None


def _parse_statement_metadata(statement_xml: str) -> FlexStatementMetadata:
    root = ET.fromstring(statement_xml)
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "FlexStatement":
            continue
        return FlexStatementMetadata(
            from_date=_parse_statement_date(element.attrib.get("fromDate")),
            to_date=_parse_statement_date(element.attrib.get("toDate")),
            period=str(element.attrib.get("period", "")).strip(),
            when_generated=str(element.attrib.get("whenGenerated", "")).strip(),
            account_id=str(element.attrib.get("accountId", "")).strip(),
        )
    raise RuntimeError("Downloaded payload did not include a FlexStatement node")


def _covers_full_year(metadata: FlexStatementMetadata, year: int) -> bool:
    return metadata.from_date == date(year, 1, 1) and metadata.to_date == date(year, 12, 31)


def _parse_statement_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    text = str(raw).strip()
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


def generate_position_report(
    *,
    positions_path: str | Path,
    prices_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Build a plain CSV report from already-normalized snapshots."""
    positions = _load_positions(positions_path)
    prices = _load_prices(prices_path)
    rows = build_position_report_rows(positions, build_price_lookup(prices))
    return export_position_report_csv(rows, output_path)


def generate_ibkr_position_report(
    *,
    ibkr_positions_path: str | Path,
    ibkr_prices_path: str | Path,
    output_path: str | Path,
    as_of: str | None = None,
) -> Path:
    """Normalize raw IBKR payload dumps, then render the standard report shape."""
    reference_table = build_security_reference_table(reference_path=DEFAULT_SECURITY_REFERENCE_PATH)
    raw_positions = _load_json_rows(ibkr_positions_path)
    raw_prices = _load_json_rows(ibkr_prices_path)
    positions = normalize_ibkr_positions(raw_positions, reference_table, as_of=as_of)
    prices = normalize_ibkr_latest_prices(raw_prices, reference_table, as_of=as_of)
    rows = build_position_report_rows(
        positions,
        build_price_lookup(prices),
        reference_table.to_security_lookup(),
    )
    written_path = export_position_report_csv(rows, output_path)
    _write_generated_security_reference_csv(reference_table)
    _write_proposed_security_universe_csv(reference_table, output_path=written_path)
    return written_path


def generate_live_ibkr_position_report(
    *,
    output_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 1,
    account_id: str | None = None,
    timeout: float = 4.0,
    as_of: str | None = None,
    client: object | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    """Pull live TWS portfolio data and route it through the same normalization path."""
    reporter = resolve_progress_reporter(progress)
    total_steps = 6
    current_step = 0
    reporter.stage("IBKR live report", current=current_step, total=total_steps)
    live_client = client or TwsIbAsyncClient(
        host=host,
        port=port,
        client_id=client_id,
        timeout=timeout,
        account=account_id or "",
    )
    connect = getattr(live_client, "connect")
    disconnect = getattr(live_client, "disconnect", None)
    reporter.spinner("IBKR live report", detail="connecting")
    connect()
    try:
        selected_account_id = _load_live_account_id(live_client, account_id)
        current_step += 1
        reporter.stage("IBKR live report: account selected", current=current_step, total=total_steps)
        portfolio_items = _load_live_portfolio_items(live_client, selected_account_id)
        current_step += 1
        reporter.stage("IBKR live report: positions fetched", current=current_step, total=total_steps)
        cash_values = _load_live_account_values(live_client, selected_account_id)
        current_step += 1
        reporter.stage("IBKR live report: cash fetched", current=current_step, total=total_steps)
        sources, rows, reference_table = _build_live_ibkr_report_rows(
            portfolio_items,
            cash_values,
            as_of=as_of,
        )
        current_step += 1
        reporter.stage("IBKR live report: rows normalized", current=current_step, total=total_steps)
        _refresh_live_security_lookups(
            reference_table=reference_table,
            live_client=live_client,
            sources=sources,
            progress=reporter.child("Contract lookup"),
        )
        current_step += 1
        reporter.stage("IBKR live report: contract details refreshed", current=current_step, total=total_steps)
        written_path = export_position_report_csv(rows, output_path)
        _mirror_artifact_if_configured(
            written_path,
            target_name=DEFAULT_GOOGLE_DRIVE_POSITIONS_FILENAME,
        )
        _write_generated_security_reference_csv(reference_table)
        _write_proposed_security_universe_csv(reference_table, output_path=written_path)
        reporter.done("IBKR live report", detail=f"wrote {written_path}")
        return written_path
    finally:
        if callable(disconnect):
            disconnect()


def build_live_ibkr_position_security_table(
    *,
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 1,
    account_id: str | None = None,
    timeout: float = 4.0,
    as_of: str | None = None,
    client: object | None = None,
) -> list[dict[str, object]]:
    """Pull live TWS positions and flatten position, reference, and contract detail data."""
    live_client = client or TwsIbAsyncClient(
        host=host,
        port=port,
        client_id=client_id,
        timeout=timeout,
        account=account_id or "",
    )
    connect = getattr(live_client, "connect")
    disconnect = getattr(live_client, "disconnect", None)
    connect()
    try:
        selected_account_id = _load_live_account_id(live_client, account_id)
        portfolio_items = _load_live_portfolio_items(live_client, selected_account_id)
        cash_values = _load_live_account_values(live_client, selected_account_id)
        sources, report_rows, reference_table = _build_live_ibkr_report_rows(
            portfolio_items,
            cash_values,
            as_of=as_of,
        )
        rows: list[dict[str, object]] = []
        for source, report_row in zip(sources, report_rows):
            contract_details: dict[str, object] = {}
            security = reference_table.get_security(report_row.internal_id)
            if source.portfolio_item is not None:
                contract_details = _fetch_live_contract_details(live_client, source.portfolio_item)
                security = _refresh_live_security_lookup(
                    reference_table=reference_table,
                    security=security,
                    portfolio_item=source.portfolio_item,
                    details=contract_details,
                )
            rows.append(
                _build_live_ibkr_position_security_row(
                raw_position=source.raw_position,
                report_row=report_row,
                security=security,
                contract_details=contract_details,
            )
            )
        return rows
    finally:
        if callable(disconnect):
            disconnect()


def generate_risk_html_report(
    *,
    positions_csv_path: str | Path,
    output_path: str | Path,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
    risk_config_path: str | Path | None = None,
    allocation_policy_path: str | Path | None = None,
    vol_method: str = "geomean_1m_3m",
    inter_asset_corr: str = "historical",
    progress: ProgressReporter | None = None,
) -> Path:
    """Render the HTML risk report from a previously generated position CSV."""
    return generate_risk_snapshot_report(
        positions_csv_path=positions_csv_path,
        output_path=output_path,
        returns_path=returns_path,
        proxy_path=proxy_path,
        regime_path=regime_path,
        security_reference_path=security_reference_path,
        risk_config_path=risk_config_path,
        allocation_policy_path=allocation_policy_path,
        vol_method=vol_method,
        inter_asset_corr=inter_asset_corr,
    )


def generate_risk_snapshot_report(
    *,
    positions_csv_path: str | Path,
    output_path: str | Path,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
    risk_config_path: str | Path | None = None,
    allocation_policy_path: str | Path | None = None,
    vol_method: str = "geomean_1m_3m",
    inter_asset_corr: str = "historical",
) -> Path:
    """Render the risk report by snapshotting the NiceGUI dashboard headlessly."""
    request = _build_snapshot_request(
        positions_csv_path=positions_csv_path,
        output_path=output_path,
        returns_path=returns_path,
        proxy_path=proxy_path,
        regime_path=regime_path,
        security_reference_path=security_reference_path,
        risk_config_path=risk_config_path,
        allocation_policy_path=allocation_policy_path,
        vol_method=vol_method,
        inter_asset_corr=inter_asset_corr,
        tab="risk",
    )
    return _capture_portfolio_snapshot(request)


def generate_combined_html_report(
    *,
    positions_csv_path: str | Path,
    output_path: str | Path,
    performance_history_path: str | Path | None = None,
    performance_output_dir: str | Path | None = None,
    performance_report_csv_path: str | Path | None = None,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
    risk_config_path: str | Path | None = None,
    allocation_policy_path: str | Path | None = None,
    vol_method: str = "geomean_1m_3m",
    inter_asset_corr: str = "historical",
) -> Path:
    request = _build_snapshot_request(
        positions_csv_path=positions_csv_path,
        output_path=output_path,
        performance_history_path=performance_history_path,
        performance_output_dir=performance_output_dir,
        performance_report_csv_path=performance_report_csv_path,
        returns_path=returns_path,
        proxy_path=proxy_path,
        regime_path=regime_path,
        security_reference_path=security_reference_path,
        risk_config_path=risk_config_path,
        allocation_policy_path=allocation_policy_path,
        vol_method=vol_method,
        inter_asset_corr=inter_asset_corr,
    )
    written_path = _capture_portfolio_snapshot(request)
    _mirror_artifact_if_configured(
        written_path,
        config_path=risk_config_path,
        target_name=DEFAULT_GOOGLE_DRIVE_COMBINED_REPORT_FILENAME,
    )
    return written_path


def _capture_portfolio_snapshot(request) -> Path:
    from market_helper.presentation.dashboard.snapshot import capture_snapshot

    return capture_snapshot(request)


def _build_snapshot_request(
    *,
    positions_csv_path: str | Path,
    output_path: str | Path,
    performance_history_path: str | Path | None = None,
    performance_output_dir: str | Path | None = None,
    performance_report_csv_path: str | Path | None = None,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
    risk_config_path: str | Path | None = None,
    allocation_policy_path: str | Path | None = None,
    vol_method: str = "geomean_1m_3m",
    inter_asset_corr: str = "historical",
    tab: str | None = None,
):
    from market_helper.presentation.dashboard.snapshot import SnapshotRequest

    reference_path = _resolve_security_reference_path(security_reference_path)
    overrides = _build_snapshot_overrides(
        positions_csv_path=positions_csv_path,
        performance_history_path=performance_history_path,
        performance_output_dir=performance_output_dir,
        performance_report_csv_path=performance_report_csv_path,
        returns_path=returns_path,
        proxy_path=proxy_path,
        regime_path=regime_path,
        security_reference_path=reference_path,
        risk_config_path=risk_config_path,
        allocation_policy_path=allocation_policy_path,
        vol_method=vol_method,
        inter_asset_corr=inter_asset_corr,
    )
    query = "snapshot=1"
    if tab:
        query += f"&tab={tab}"
    return SnapshotRequest(output_path=Path(output_path), query=query, overrides=overrides)


def _resolve_security_reference_path(path: str | Path | None) -> Path:
    reference_path = Path(path) if path is not None else DEFAULT_SECURITY_REFERENCE_PATH
    sync_security_reference_csv(reference_path=reference_path)
    return reference_path


def _build_snapshot_overrides(
    *,
    positions_csv_path: str | Path,
    performance_history_path: str | Path | None = None,
    performance_output_dir: str | Path | None = None,
    performance_report_csv_path: str | Path | None = None,
    returns_path: str | Path | None = None,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path,
    risk_config_path: str | Path | None = None,
    allocation_policy_path: str | Path | None = None,
    vol_method: str = "geomean_1m_3m",
    inter_asset_corr: str = "historical",
) -> dict[str, str]:
    overrides = {
        "positions_csv_path": str(positions_csv_path),
        "security_reference_path": str(security_reference_path),
        "vol_method": vol_method,
        "inter_asset_corr": inter_asset_corr,
    }
    optional_paths = {
        "performance_history_path": performance_history_path,
        "performance_output_dir": performance_output_dir,
        "performance_report_csv_path": performance_report_csv_path,
        "returns_path": returns_path,
        "proxy_path": proxy_path,
        "regime_path": regime_path,
        "risk_config_path": risk_config_path,
        "allocation_policy_path": allocation_policy_path,
    }
    for key, value in optional_paths.items():
        if value is not None:
            overrides[key] = str(value)
    return overrides


def generate_security_reference_sync(
    *,
    output_path: str | Path | None = None,
) -> Path:
    return sync_security_reference_csv(reference_path=output_path or DEFAULT_SECURITY_REFERENCE_PATH)


def generate_etf_sector_sync(
    *,
    symbols: list[str],
    output_path: str | Path | None = None,
    api_key: str | None = None,
    client: object | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    return sync_us_sector_lookthrough(
        symbols=symbols,
        output_path=output_path,
        api_key=api_key,
        client=client,
        progress=resolve_progress_reporter(progress),
    )


def generate_report_mapping_table(
    *,
    workbook_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Convert the workbook seed into the tracked security-reference CSV format."""
    table = extract_security_reference_seed(workbook_path)
    return export_security_reference_seed_csv(table, output_path)


def _load_positions(path: str | Path) -> list[PortfolioPositionSnapshot]:
    payload = _load_json_rows(path)
    return [
        PortfolioPositionSnapshot(
            as_of=str(row["as_of"]),
            account=str(row["account"]),
            internal_id=str(row["internal_id"]),
            source=str(row["source"]),
            quantity=float(row["quantity"]),
            avg_cost=_optional_float(row.get("avg_cost")),
            market_value=_optional_float(row.get("market_value")),
        )
        for row in payload
    ]


def _load_prices(path: str | Path) -> list[PortfolioPriceSnapshot]:
    payload = _load_json_rows(path)
    return [
        PortfolioPriceSnapshot(
            as_of=str(row["as_of"]),
            internal_id=str(row["internal_id"]),
            source=str(row["source"]),
            last_price=float(row["last_price"]),
        )
        for row in payload
    ]


def _load_json_rows(path: str | Path) -> list[dict[str, object]]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(loaded, list):
        return [dict(row) for row in loaded]
    if isinstance(loaded, dict):
        # Keep accepting legacy wrapper shapes so notebook artifacts and older
        # fixtures do not all have to move in lockstep with the new pipelines.
        for key in ("rows", "positions", "prices", "data"):
            value = loaded.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value]
    raise ValueError("Expected a JSON array of snapshot rows or a wrapper object containing one")


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _load_live_account_id(live_client: object, account_id: str | None) -> str:
    accounts = live_client.list_accounts()
    return choose_tws_account(accounts, account_id)


def _load_live_portfolio_items(
    live_client: object,
    account_id: str,
) -> list[object]:
    return list(live_client.list_portfolio(account_id))


def _load_live_account_values(
    live_client: object,
    account_id: str,
) -> list[object]:
    list_account_values = getattr(live_client, "list_account_values", None)
    if not callable(list_account_values):
        return []
    return list(list_account_values(account_id))


def _build_live_ibkr_report_rows(
    portfolio_items: list[object],
    cash_values: list[object],
    *,
    as_of: str | None,
) -> tuple[list[LiveIbkrRowSource], list[PositionReportRow], SecurityReferenceTable]:
    # Keep live normalization identical to the CSV/report pipeline so notebook
    # exploration and exported reports stay aligned.
    reference_table = build_security_reference_table(reference_path=DEFAULT_SECURITY_REFERENCE_PATH)
    sources = [
        LiveIbkrRowSource(raw_position=row, portfolio_item=item)
        for item, row in zip(
            portfolio_items,
            portfolio_items_to_ibkr_position_rows(portfolio_items),
        )
    ]
    sources.extend(
        LiveIbkrRowSource(raw_position=row)
        for row in account_values_to_ibkr_cash_position_rows(cash_values)
    )
    raw_positions = [source.raw_position for source in sources]
    positions = normalize_ibkr_positions(
        raw_positions,
        reference_table,
        as_of=as_of,
    )
    prices = normalize_ibkr_latest_prices(
        portfolio_items_to_ibkr_price_rows(portfolio_items),
        reference_table,
        as_of=as_of,
    )
    prices.extend(_build_live_cash_price_rows(positions, reference_table))
    rows = build_position_report_rows(
        positions,
        build_price_lookup(prices),
        reference_table.to_security_lookup(),
    )
    return sources, rows, reference_table


def _build_live_cash_price_rows(
    positions: list[PortfolioPositionSnapshot],
    reference_table: SecurityReferenceTable,
) -> list[PortfolioPriceSnapshot]:
    lookup = reference_table.to_security_lookup()
    rows: list[PortfolioPriceSnapshot] = []
    for position in positions:
        security = lookup.get(position.internal_id)
        if security is None or security.ibkr_sec_type != "CASH":
            continue
        rows.append(
            PortfolioPriceSnapshot(
                as_of=position.as_of,
                internal_id=position.internal_id,
                source=position.source,
                last_price=1.0,
            )
        )
    return rows


def _mirror_artifact_if_configured(
    source_path: str | Path,
    *,
    target_name: str,
    config_path: str | Path | None = None,
) -> Path | None:
    mirror_dir = _load_artifact_mirror_dir(config_path)
    if mirror_dir is None:
        return None
    source = Path(source_path)
    target_path = mirror_dir / target_name
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_path)
    return target_path


def _load_artifact_mirror_dir(config_path: str | Path | None = None) -> Path | None:
    resolved_config_path = Path(config_path) if config_path is not None else _default_report_config_path()
    if not resolved_config_path.exists():
        return None
    payload = yaml.safe_load(resolved_config_path.read_text(encoding="utf-8")) or {}
    artifact_mirror = payload.get("artifact_mirror")
    if artifact_mirror is None:
        return None
    if not isinstance(artifact_mirror, dict):
        raise ValueError("artifact_mirror must be a mapping")
    google_drive_dir = str(artifact_mirror.get("google_drive_dir", "")).strip()
    if google_drive_dir == "":
        return None
    return Path(google_drive_dir).expanduser()


def _default_report_config_path() -> Path:
    from market_helper.reporting.risk_html import DEFAULT_RISK_REPORT_CONFIG_PATH

    return DEFAULT_RISK_REPORT_CONFIG_PATH


def _refresh_live_security_lookups(
    *,
    reference_table: SecurityReferenceTable,
    live_client: object,
    sources: list[LiveIbkrRowSource],
    progress: ProgressReporter | None = None,
) -> None:
    if not _supports_live_contract_lookup(live_client):
        return
    eligible_sources: list[LiveIbkrRowSource] = []
    for source in sources:
        portfolio_item = source.portfolio_item
        if portfolio_item is None:
            continue
        contract = getattr(portfolio_item, "contract", None)
        con_id = getattr(contract, "conId", None)
        if con_id in (None, ""):
            continue
        internal_id = reference_table.resolve_internal_id("ibkr", str(con_id))
        if internal_id is None:
            continue
        security = reference_table.get_security(internal_id)
        if security is None or security.mapping_status == "outside_scope":
            continue
        eligible_sources.append(source)
    completed = 0
    if progress is not None and eligible_sources:
        progress.stage("Contract details", current=0, total=len(eligible_sources))
    for source in eligible_sources:
        portfolio_item = source.portfolio_item
        if portfolio_item is None:
            continue
        contract = getattr(portfolio_item, "contract", None)
        con_id = getattr(contract, "conId", None)
        if con_id in (None, ""):
            continue
        internal_id = reference_table.resolve_internal_id("ibkr", str(con_id))
        if internal_id is None:
            continue
        security = reference_table.get_security(internal_id)
        if security is None or security.mapping_status == "outside_scope":
            continue
        details = _fetch_live_contract_details(live_client, portfolio_item)
        _refresh_live_security_lookup(
            reference_table=reference_table,
            security=security,
            portfolio_item=portfolio_item,
            details=details,
        )
        if progress is not None:
            completed += 1
            progress.update(
                "Contract details",
                completed=completed,
                total=len(eligible_sources),
                detail=f"{internal_id} refreshed",
            )


def _supports_live_contract_lookup(live_client: object) -> bool:
    return callable(getattr(live_client, "lookup_security", None)) or callable(
        getattr(live_client, "require_security_info", None)
    )


def _refresh_live_security_lookup(
    *,
    reference_table: SecurityReferenceTable,
    security: SecurityReference | None,
    portfolio_item: object,
    details: dict[str, object],
) -> SecurityReference | None:
    if security is None or security.mapping_status == "outside_scope":
        return security

    contract = getattr(portfolio_item, "contract", None)
    con_id = str(
        details.get("conId")
        or getattr(contract, "conId", "")
        or security.ibkr_conid
    )
    if not con_id:
        return security

    if security.mapping_status == "unmapped":
        remapped_security = reference_table.resolve_runtime_contract_match(
            symbol=str(
                details.get("symbol")
                or getattr(contract, "symbol", "")
                or security.ibkr_symbol
                or security.symbol
            ).upper(),
            sec_type=str(
                details.get("secType")
                or getattr(contract, "secType", "")
                or security.ibkr_sec_type
            ).upper(),
            exchange=str(
                details.get("exchange")
                or getattr(contract, "exchange", "")
                or security.exchange
            ).upper(),
            primary_exchange=str(
                details.get("primaryExchange")
                or details.get("exchange")
                or getattr(contract, "primaryExchange", "")
                or security.primary_exchange
            ).upper(),
            exclude_internal_ids={security.internal_id},
        )
        if remapped_security is not None:
            reference_table.remove_security(security.internal_id)
            reference_table.register_runtime_contract(
                security=remapped_security,
                con_id=con_id,
                symbol=str(
                    details.get("symbol")
                    or getattr(contract, "symbol", "")
                    or remapped_security.ibkr_symbol
                    or remapped_security.symbol
                ).upper(),
                exchange=str(
                    details.get("exchange")
                    or getattr(contract, "exchange", "")
                    or remapped_security.exchange
                    or remapped_security.primary_exchange
                    or remapped_security.ibkr_exchange
                ).upper(),
                primary_exchange=str(
                    details.get("primaryExchange")
                    or details.get("exchange")
                    or getattr(contract, "primaryExchange", "")
                    or remapped_security.primary_exchange
                    or remapped_security.ibkr_exchange
                ).upper(),
                local_symbol=str(
                    details.get("localSymbol")
                    or getattr(contract, "localSymbol", "")
                    or remapped_security.runtime_local_symbol
                    or remapped_security.symbol
                ),
                sec_type=str(
                    details.get("secType")
                    or getattr(contract, "secType", "")
                    or remapped_security.ibkr_sec_type
                ).upper(),
                currency=str(
                    details.get("currency")
                    or getattr(contract, "currency", "")
                    or remapped_security.currency
                ).upper(),
                multiplier=_optional_float(
                    details.get("multiplier")
                    or getattr(contract, "multiplier", None)
                ),
            )
            return reference_table.get_security(remapped_security.internal_id)
        enriched = enrich_security_from_contract_details(security, details)
        reference_table.upsert_security(enriched)
        reference_table.upsert_mapping(
            SecurityMapping(
                source="ibkr",
                external_id=con_id,
                internal_id=enriched.internal_id,
            )
        )
        return enriched

    symbol = str(
        details.get("symbol")
        or getattr(contract, "symbol", "")
        or security.ibkr_symbol
        or security.symbol
    ).upper()
    exchange = str(
        details.get("exchange")
        or getattr(contract, "exchange", "")
        or security.exchange
        or security.primary_exchange
        or security.ibkr_exchange
    ).upper()
    primary_exchange = str(
        details.get("primaryExchange")
        or details.get("exchange")
        or getattr(contract, "primaryExchange", "")
        or exchange
        or security.primary_exchange
    ).upper()
    local_symbol = str(
        details.get("localSymbol")
        or getattr(contract, "localSymbol", "")
        or security.runtime_local_symbol
        or security.symbol
    )
    sec_type = str(
        details.get("secType")
        or getattr(contract, "secType", "")
        or security.ibkr_sec_type
    ).upper()
    currency = str(
        details.get("currency")
        or getattr(contract, "currency", "")
        or security.currency
    ).upper()
    multiplier = _optional_float(
        details.get("multiplier")
        or getattr(contract, "multiplier", None)
    )
    reference_table.register_runtime_contract(
        security=security,
        con_id=con_id,
        symbol=symbol,
        exchange=exchange,
        primary_exchange=primary_exchange,
        local_symbol=local_symbol,
        sec_type=sec_type,
        currency=currency,
        multiplier=multiplier,
    )
    return reference_table.get_security(security.internal_id)


def _write_generated_security_reference_csv(
    reference_table: SecurityReferenceTable,
) -> Path:
    return export_security_reference_csv(
        reference_table.to_rows(),
        DEFAULT_SECURITY_REFERENCE_PATH,
    )


def _write_proposed_security_universe_csv(
    reference_table: SecurityReferenceTable,
    *,
    output_path: str | Path,
) -> Path | None:
    proposed_rows = reference_table.to_universe_proposal_rows()
    if not proposed_rows:
        return None

    proposed_path = Path(output_path).with_name("security_universe_PROPOSED.csv")
    export_security_universe_proposal_csv(proposed_rows, proposed_path)
    print(
        "Universe gaps were normalized with runtime contract info. "
        "Review {path} ({count} rows) and merge any approved rows into configs/security_universe.csv.".format(
            path=proposed_path,
            count=len(proposed_rows),
        )
    )
    return proposed_path


def _fetch_live_contract_details(
    live_client: object,
    portfolio_item: object,
) -> dict[str, object]:
    contract = getattr(portfolio_item, "contract", None)
    if contract is None:
        raise AttributeError("TWS portfolio item is missing contract; cannot fetch IBKR contract details.")

    lookup_security = getattr(live_client, "lookup_security", None)
    if callable(lookup_security):
        details = lookup_security(contract=contract)
        return dict(details)

    require_security_info = getattr(live_client, "require_security_info", None)
    if not callable(require_security_info):
        raise AttributeError(
            "Live TWS client must expose lookup_security() for contract enrichment."
        )

    details = require_security_info(contract=contract)
    return dict(details)


def _build_live_ibkr_position_security_row(
    *,
    raw_position: dict[str, object],
    report_row: PositionReportRow,
    security: SecurityReference | None,
    contract_details: dict[str, object],
) -> dict[str, object]:
    runtime_local_symbol = (
        raw_position.get("localSymbol")
        or contract_details.get("localSymbol")
        or report_row.local_symbol
    )
    row = {
        "as_of": report_row.as_of,
        "account": report_row.account,
        "internal_id": report_row.internal_id,
        "con_id": report_row.con_id,
        "symbol": report_row.symbol,
        "local_symbol": runtime_local_symbol,
        "exchange": report_row.exchange,
        "currency": report_row.currency,
        "source": report_row.source,
        "quantity": report_row.quantity,
        "avg_cost": report_row.avg_cost,
        "latest_price": report_row.latest_price,
        "market_value": report_row.market_value,
        "cost_basis": report_row.cost_basis,
        "unrealized_pnl": report_row.unrealized_pnl,
        "weight": report_row.weight,
        "ibkr_conid": raw_position.get("conId"),
        "ibkr_sec_type": raw_position.get("secType"),
        "ibkr_symbol": raw_position.get("symbol"),
        "ibkr_currency": raw_position.get("currency"),
        "ibkr_exchange": raw_position.get("exchange"),
        "ibkr_local_symbol": raw_position.get("localSymbol"),
        "ibkr_multiplier": raw_position.get("multiplier"),
        "ibkr_position": raw_position.get("position"),
        "ibkr_avg_cost": raw_position.get("avgCost"),
        "ibkr_market_value": raw_position.get("marketValue"),
        "ibkr_cash_tag": raw_position.get("cashTag"),
        "ibkr_cash_target_currency": raw_position.get("cashTargetCurrency"),
        "ibkr_cash_source_currencies": raw_position.get("cashSourceCurrencies"),
        "ibkr_cash_conversion_mode": raw_position.get("cashConversionMode"),
        "contract_conid": contract_details.get("conId"),
        "contract_symbol": contract_details.get("symbol"),
        "contract_sec_type": contract_details.get("secType"),
        "contract_currency": contract_details.get("currency"),
        "contract_exchange": contract_details.get("exchange"),
        "contract_primary_exchange": contract_details.get("primaryExchange"),
        "contract_local_symbol": contract_details.get("localSymbol"),
        "contract_market_name": contract_details.get("marketName"),
        "contract_min_tick": contract_details.get("minTick"),
        "contract_price_magnifier": contract_details.get("priceMagnifier"),
        "contract_order_types": contract_details.get("orderTypes"),
        "contract_valid_exchanges": contract_details.get("validExchanges"),
        "contract_trading_hours": contract_details.get("tradingHours"),
        "contract_liquid_hours": contract_details.get("liquidHours"),
        "contract_long_name": contract_details.get("longName"),
        "contract_industry": contract_details.get("industry"),
        "contract_category": contract_details.get("category"),
        "contract_subcategory": contract_details.get("subcategory"),
    }
    row.update(_security_enrichment_fields(security))
    row["security_runtime_local_symbol"] = row["security_runtime_local_symbol"] or runtime_local_symbol
    return row


def _security_enrichment_fields(
    security: SecurityReference | None,
) -> dict[str, object]:
    if security is None:
        return {
            "security_mapping_status": "",
            "security_is_active": None,
            "security_asset_class": "",
            "security_canonical_symbol": "",
            "security_display_ticker": "",
            "security_display_name": "",
            "security_symbol": "",
            "security_currency": "",
            "security_exchange": "",
            "security_primary_exchange": "",
            "security_description": "",
            "security_multiplier": None,
            "security_ibkr_sec_type": "",
            "security_ibkr_symbol": "",
            "security_ibkr_exchange": "",
            "security_ibkr_conid": "",
            "security_yahoo_symbol": "",
            "security_eq_country": "",
            "security_eq_sector_proxy": "",
            "security_dir_exposure": "",
            "security_mod_duration": None,
            "security_fi_tenor": "",
            "security_lookup_status": "",
            "security_last_verified_at": "",
            "security_runtime_local_symbol": "",
        }

    return {
        "security_mapping_status": security.mapping_status,
        "security_is_active": security.is_active,
        "security_asset_class": security.asset_class,
        "security_canonical_symbol": security.canonical_symbol,
        "security_display_ticker": security.display_ticker,
        "security_display_name": security.display_name,
        "security_symbol": security.symbol,
        "security_currency": security.currency,
        "security_exchange": security.exchange,
        "security_primary_exchange": security.primary_exchange,
        "security_description": security.description,
        "security_multiplier": security.multiplier,
        "security_ibkr_sec_type": security.ibkr_sec_type,
        "security_ibkr_symbol": security.ibkr_symbol,
        "security_ibkr_exchange": security.ibkr_exchange,
        "security_ibkr_conid": security.ibkr_conid,
        "security_yahoo_symbol": security.yahoo_symbol,
        "security_eq_country": security.eq_country,
        "security_eq_sector_proxy": security.eq_sector_proxy,
        "security_dir_exposure": security.dir_exposure,
        "security_mod_duration": security.mod_duration,
        "security_fi_tenor": security.fi_tenor,
        "security_lookup_status": security.lookup_status,
        "security_last_verified_at": security.last_verified_at,
        "security_runtime_local_symbol": security.runtime_local_symbol,
    }


__all__ = [
    "build_live_ibkr_position_security_table",
    "generate_combined_html_report",
    "generate_etf_sector_sync",
    "generate_ibkr_position_report",
    "generate_live_ibkr_position_report",
    "generate_position_report",
    "generate_report_mapping_table",
    "generate_risk_html_report",
    "generate_security_reference_sync",
]
