from market_helper.providers.web_api import (
    map_account_summary,
    map_position,
    map_quote_snapshot,
)


def test_map_account_summary_accepts_camel_case() -> None:
    row = {
        "accountId": "U12345",
        "netLiquidation": "125000.50",
        "availableFunds": "40000.25",
        "currency": "USD",
    }

    account = map_account_summary(row, as_of="2026-03-26T00:00:00+00:00")

    assert account.account_id == "U12345"
    assert account.net_liquidation == 125000.50
    assert account.available_funds == 40000.25


def test_map_position_normalizes_contract_prefix() -> None:
    row = {
        "account": "U12345",
        "conid": "756733",
        "position": "20",
        "avgCost": "210.5",
        "marketValue": "4300",
    }

    position = map_position(row, as_of="2026-03-26T00:00:00+00:00")

    assert position.contract_id == "IBKR:756733"
    assert position.quantity == 20
    assert position.avg_cost == 210.5


def test_map_quote_snapshot_accepts_market_data_field_codes() -> None:
    row = {
        "conid": "756733",
        "31": "214.8",
        "84": "214.75",
        "86": "214.85",
    }

    quote = map_quote_snapshot(row, as_of="2026-03-26T00:00:00+00:00")

    assert quote.contract_id == "IBKR:756733"
    assert quote.last == 214.8
    assert quote.bid == 214.75
    assert quote.ask == 214.85
