from __future__ import annotations

"""Backward-compatible workflow facade for portfolio-monitor reporting.

This module intentionally mirrors the legacy workflow API so existing tests,
notebooks, and monkeypatch-based fixtures can keep targeting the old import path
while the real implementation lives under ``domain.portfolio_monitor``.
"""

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from market_helper.common.progress import ProgressReporter
from market_helper.data_sources.ibkr.tws import TwsIbAsyncClient
from market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report import (
    FlexBackfillBatchError,
    backfill_ibkr_flex_full_years as _backfill_ibkr_flex_full_years,
    generate_combined_html_report as _generate_combined_html_report,
    generate_etf_sector_sync as _generate_etf_sector_sync,
    generate_ibkr_flex_performance_report as _generate_ibkr_flex_performance_report,
    generate_ibkr_position_report as _generate_ibkr_position_report,
    generate_live_ibkr_position_report as _generate_live_ibkr_position_report,
    generate_position_report as _generate_position_report,
    generate_report_mapping_table as _generate_report_mapping_table,
    generate_risk_html_report as _generate_risk_html_report,
    generate_risk_snapshot_report as _generate_risk_snapshot_report,
    generate_security_reference_sync as _generate_security_reference_sync,
    rebuild_ibkr_flex_nav_cashflow_history as _rebuild_ibkr_flex_nav_cashflow_history,
    refresh_current_year_latest_flex_xml as _refresh_current_year_latest_flex_xml,
)

if TYPE_CHECKING:
    from market_helper.data_sources.yahoo_finance import YahooFinanceClient


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
    poll_interval_seconds: float = 5.0,
    max_attempts: int = 10,
    client: object | None = None,
    yahoo_client: YahooFinanceClient | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    return _generate_ibkr_flex_performance_report(
        output_dir=output_dir,
        flex_xml_path=flex_xml_path,
        query_id=query_id,
        token=token,
        from_date=from_date,
        to_date=to_date,
        period=period,
        xml_output_path=xml_output_path,
        poll_interval_seconds=poll_interval_seconds,
        max_attempts=max_attempts,
        client=client,
        yahoo_client=yahoo_client,
        progress=progress,
    )


def backfill_ibkr_flex_full_years(
    *,
    output_dir: str | Path,
    query_id: str,
    token: str,
    start_year: int,
    end_year: int,
    overwrite_existing: bool = False,
    poll_interval_seconds: float = 5.0,
    max_attempts: int = 10,
    max_inflight_requests: int = 3,
    client: object | None = None,
    progress: ProgressReporter | None = None,
):
    return _backfill_ibkr_flex_full_years(
        output_dir=output_dir,
        query_id=query_id,
        token=token,
        start_year=start_year,
        end_year=end_year,
        overwrite_existing=overwrite_existing,
        poll_interval_seconds=poll_interval_seconds,
        max_attempts=max_attempts,
        max_inflight_requests=max_inflight_requests,
        client=client,
        progress=progress,
    )


def refresh_current_year_latest_flex_xml(
    *,
    output_dir: str | Path,
    query_id: str,
    token: str,
    xml_output_path: str | Path | None = None,
    poll_interval_seconds: float = 5.0,
    max_attempts: int = 10,
    client: object | None = None,
    progress: ProgressReporter | None = None,
):
    return _refresh_current_year_latest_flex_xml(
        output_dir=output_dir,
        query_id=query_id,
        token=token,
        xml_output_path=xml_output_path,
        poll_interval_seconds=poll_interval_seconds,
        max_attempts=max_attempts,
        client=client,
        progress=progress,
    )


def rebuild_ibkr_flex_nav_cashflow_history(
    *,
    output_dir: str | Path,
    yahoo_client: YahooFinanceClient | None = None,
    extra_xml_paths: list[str | Path] | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    return _rebuild_ibkr_flex_nav_cashflow_history(
        output_dir=output_dir,
        yahoo_client=yahoo_client,
        extra_xml_paths=extra_xml_paths,
        progress=progress,
    )


def generate_position_report(
    *,
    positions_path: str | Path,
    prices_path: str | Path,
    output_path: str | Path,
) -> Path:
    return _generate_position_report(
        positions_path=positions_path,
        prices_path=prices_path,
        output_path=output_path,
    )


def generate_ibkr_position_report(
    *,
    ibkr_positions_path: str | Path,
    ibkr_prices_path: str | Path,
    output_path: str | Path,
    as_of: str | None = None,
) -> Path:
    return _generate_ibkr_position_report(
        ibkr_positions_path=ibkr_positions_path,
        ibkr_prices_path=ibkr_prices_path,
        output_path=output_path,
        as_of=as_of,
    )


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
    live_client = client or TwsIbAsyncClient(
        host=host,
        port=port,
        client_id=client_id,
        timeout=timeout,
        account=account_id or "",
    )
    # Instantiate the client in this legacy facade so old tests can still
    # monkeypatch ``market_helper.workflows.generate_report.TwsIbAsyncClient``.
    return _generate_live_ibkr_position_report(
        output_path=output_path,
        host=host,
        port=port,
        client_id=client_id,
        account_id=account_id,
        timeout=timeout,
        as_of=as_of,
        client=live_client,
        progress=progress,
    )


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
    return _generate_risk_html_report(
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
        progress=progress,
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
    return _generate_risk_snapshot_report(
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
    return _generate_combined_html_report(
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


def generate_security_reference_sync(
    *,
    output_path: str | Path | None = None,
) -> Path:
    return _generate_security_reference_sync(output_path=output_path)


def generate_etf_sector_sync(
    *,
    symbols: list[str],
    output_path: str | Path | None = None,
    api_key: str | None = None,
    client: object | None = None,
    progress: ProgressReporter | None = None,
) -> Path:
    return _generate_etf_sector_sync(
        symbols=symbols,
        output_path=output_path,
        api_key=api_key,
        client=client,
        progress=progress,
    )


def generate_report_mapping_table(
    *,
    workbook_path: str | Path,
    output_path: str | Path,
) -> Path:
    return _generate_report_mapping_table(
        workbook_path=workbook_path,
        output_path=output_path,
    )


__all__ = [
    "FlexBackfillBatchError",
    "TwsIbAsyncClient",
    "backfill_ibkr_flex_full_years",
    "generate_combined_html_report",
    "generate_etf_sector_sync",
    "generate_ibkr_flex_performance_report",
    "generate_ibkr_position_report",
    "generate_live_ibkr_position_report",
    "generate_position_report",
    "generate_report_mapping_table",
    "generate_risk_html_report",
    "generate_security_reference_sync",
    "rebuild_ibkr_flex_nav_cashflow_history",
    "refresh_current_year_latest_flex_xml",
]
