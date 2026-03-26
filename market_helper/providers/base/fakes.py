from __future__ import annotations

from dataclasses import dataclass, field

from market_helper.domain import AccountSnapshot, PositionSnapshot, QuoteSnapshot


@dataclass
class FakeProvider:
    accounts: list[AccountSnapshot] = field(default_factory=list)
    positions: dict[str, list[PositionSnapshot]] = field(default_factory=dict)
    quotes: dict[str, QuoteSnapshot] = field(default_factory=dict)

    def read_accounts(self) -> list[AccountSnapshot]:
        return self.accounts

    def read_positions(self, account_id: str) -> list[PositionSnapshot]:
        return self.positions.get(account_id, [])

    def read_snapshot(self, contract_ids: list[str]) -> list[QuoteSnapshot]:
        return [self.quotes[contract_id] for contract_id in contract_ids if contract_id in self.quotes]
