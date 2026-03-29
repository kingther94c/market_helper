"""Backward-compatible workflow facade for portfolio-monitor reporting.

This module intentionally mirrors the legacy workflow API so existing tests,
notebooks, and monkeypatch-based fixtures can keep targeting the old import path
while the real implementation lives under ``domain.portfolio_monitor``.
"""

from pathlib import Path

from market_helper.data_sources.ibkr.tws import TwsIbAsyncClient
from market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report import (
    generate_ibkr_position_report as _generate_ibkr_position_report,
    generate_live_ibkr_position_report as _generate_live_ibkr_position_report,
    generate_position_report as _generate_position_report,
    generate_report_mapping_table as _generate_report_mapping_table,
    generate_risk_html_report as _generate_risk_html_report,
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
    )


def generate_risk_html_report(
    *,
    positions_csv_path: str | Path,
    returns_path: str | Path,
    output_path: str | Path,
    proxy_path: str | Path | None = None,
    regime_path: str | Path | None = None,
    security_reference_path: str | Path | None = None,
) -> Path:
    return _generate_risk_html_report(
        positions_csv_path=positions_csv_path,
        returns_path=returns_path,
        output_path=output_path,
        proxy_path=proxy_path,
        regime_path=regime_path,
        security_reference_path=security_reference_path,
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
    "TwsIbAsyncClient",
    "generate_ibkr_position_report",
    "generate_live_ibkr_position_report",
    "generate_position_report",
    "generate_report_mapping_table",
    "generate_risk_html_report",
]
