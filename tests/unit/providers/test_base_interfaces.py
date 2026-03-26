from market_helper.domain import AccountSnapshot, PositionSnapshot, QuoteSnapshot
from market_helper.providers.base import FakeProvider


def test_fake_provider_satisfies_read_paths() -> None:
    account = AccountSnapshot(
        as_of="2026-03-26T00:00:00+00:00",
        account_id="U1",
        net_liquidation=1000.0,
        available_funds=200.0,
    )
    position = PositionSnapshot(
        as_of="2026-03-26T00:00:00+00:00",
        account_id="U1",
        contract_id="IBKR:1",
        quantity=1,
    )
    quote = QuoteSnapshot(
        as_of="2026-03-26T00:00:00+00:00",
        contract_id="IBKR:1",
        last=100.0,
    )
    provider = FakeProvider(
        accounts=[account],
        positions={"U1": [position]},
        quotes={"IBKR:1": quote},
    )

    assert provider.read_accounts()[0].account_id == "U1"
    assert provider.read_positions("U1")[0].quantity == 1
    assert provider.read_snapshot(["IBKR:1"])[0].last == 100.0
