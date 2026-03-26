from __future__ import annotations

from typing import Protocol

from market_helper.domain import AccountSnapshot, PositionSnapshot, QuoteSnapshot


class PortfolioProvider(Protocol):
    def read_accounts(self) -> list[AccountSnapshot]: ...

    def read_positions(self, account_id: str) -> list[PositionSnapshot]: ...


class MarketDataProvider(Protocol):
    def read_snapshot(self, contract_ids: list[str]) -> list[QuoteSnapshot]: ...


class ReportingProvider(Protocol):
    def fetch_report(self, report_id: str) -> str: ...
