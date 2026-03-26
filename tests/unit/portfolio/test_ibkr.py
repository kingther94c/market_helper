import pytest

from market_helper.portfolio import (
    SecurityReferenceTable,
    normalize_ibkr_latest_prices,
    normalize_ibkr_positions,
)


def test_normalize_ibkr_positions_registers_new_contracts() -> None:
    table = SecurityReferenceTable()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "AAPL",
                "currency": "USD",
                "exchange": "SMART",
                "position": "20",
                "avg_cost": "210.5",
                "market_value": "4300",
            }
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    assert positions[0].internal_id == "IBKR:756733"
    assert table.require_internal_id("ibkr", "756733") == "IBKR:756733"


def test_normalize_ibkr_latest_prices_uses_fallback_price_fields() -> None:
    table = SecurityReferenceTable()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "AAPL",
                "currency": "USD",
                "exchange": "SMART",
                "position": "20",
            }
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    prices = normalize_ibkr_latest_prices(
        [{"con_id": "756733", "close": "215.1"}],
        table,
        as_of="2026-03-25T00:01:00+00:00",
    )

    assert prices[0].last_price == 215.1


def test_normalize_ibkr_latest_prices_raises_when_no_price_fields() -> None:
    table = SecurityReferenceTable()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "AAPL",
                "currency": "USD",
                "exchange": "SMART",
                "position": "20",
            }
        ],
        table,
    )

    with pytest.raises(ValueError):
        normalize_ibkr_latest_prices([{"con_id": "756733"}], table)
