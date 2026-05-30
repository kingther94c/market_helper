from pathlib import Path

import pytest

from market_helper.portfolio import (
    SecurityReferenceTable,
    normalize_ibkr_latest_prices,
    normalize_ibkr_positions,
)

# Tiny committed curated fixture (just SPY) so these tests stay hermetic instead
# of depending on the generated, git-ignored
# data/artifacts/portfolio_monitor/security_reference.csv. The futures / option
# identities the tests assert are *inferred* by normalize_ibkr_positions; only
# SPY needs to be pre-curated (the equity match + the option-underlying
# resolution), so a one-row fixture is enough.
_SECURITY_REFERENCE_FIXTURE = Path(__file__).parent / "_fixtures" / "security_reference.csv"


def _curated_reference_table() -> SecurityReferenceTable:
    return SecurityReferenceTable.from_csv(_SECURITY_REFERENCE_FIXTURE)


class FakeIbkrRow:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_normalize_ibkr_positions_matches_curated_equity_row() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "ARCA",
                "position": "20",
                "avg_cost": "210.5",
                "market_value": "4300",
            }
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    assert positions[0].internal_id == "STK:SPY:SMART"
    assert table.require_internal_id("ibkr", "756733") == "STK:SPY:SMART"


def test_normalize_ibkr_positions_matches_futures_family_alias() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "999001",
                "sec_type": "FUT",
                "symbol": "ZN",
                "currency": "USD",
                "exchange": "CBOT",
                "local_symbol": "ZNM6",
                "multiplier": "1000",
                "position": "1",
                "avg_cost": "110",
                "market_value": "111000",
            }
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    assert positions[0].internal_id == "FUT:ZN:CBOT"
    assert table.require_internal_id("ibkr", "999001") == "FUT:ZN:CBOT"


def test_normalize_ibkr_positions_uses_contract_specific_identity_for_commodity_futures() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "880001",
                "sec_type": "FUT",
                "symbol": "NG",
                "currency": "USD",
                "exchange": "NYMEX",
                "local_symbol": "NGN26",
                "multiplier": "10000",
                "position": "1",
                "avg_cost": "4.60",
                "market_value": "46000",
            },
            {
                "account": "U12345",
                "con_id": "880002",
                "sec_type": "FUT",
                "symbol": "NG",
                "currency": "USD",
                "exchange": "NYMEX",
                "local_symbol": "NGQ26",
                "multiplier": "10000",
                "position": "-1",
                "avg_cost": "4.75",
                "market_value": "-47500",
            },
        ],
        table,
        as_of="2026-05-03T00:00:00+00:00",
    )

    assert [position.internal_id for position in positions] == ["FUT:NGN26:NYMEX", "FUT:NGQ26:NYMEX"]
    assert table.require_internal_id("ibkr", "880001") == "FUT:NGN26:NYMEX"
    assert table.require_internal_id("ibkr", "880002") == "FUT:NGQ26:NYMEX"


def test_normalize_ibkr_positions_repairs_cached_generic_commodity_future_mapping() -> None:
    table = SecurityReferenceTable()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "880001",
                "sec_type": "FUT",
                "symbol": "NG",
                "currency": "USD",
                "exchange": "NYMEX",
                "position": "1",
            }
        ],
        table,
        as_of="2026-05-03T00:00:00+00:00",
    )
    assert table.require_internal_id("ibkr", "880001") == "FUT:NG:NYMEX"

    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "880001",
                "sec_type": "FUT",
                "symbol": "NG",
                "currency": "USD",
                "exchange": "NYMEX",
                "local_symbol": "NGF27",
                "multiplier": "10000",
                "position": "1",
                "avg_cost": "4.60",
                "market_value": "46000",
            }
        ],
        table,
        as_of="2026-05-04T00:00:00+00:00",
    )

    assert positions[0].internal_id == "FUT:NGF27:NYMEX"
    assert table.require_internal_id("ibkr", "880001") == "FUT:NGF27:NYMEX"


def test_normalize_ibkr_latest_prices_uses_fallback_price_fields() -> None:
    table = _curated_reference_table()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "ARCA",
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
    assert prices[0].internal_id == "STK:SPY:SMART"


def test_normalize_ibkr_positions_accepts_camel_case_and_object_payload() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            FakeIbkrRow(
                account="U12345",
                conId="999002",
                secType="FUT",
                symbol="ZF",
                currency="USD",
                exchange="CBOT",
                localSymbol="ZFM6",
                multiplier="1000",
                position="3",
                averageCost="106.25",
                marketValue="318750",
            )
        ],
        table,
        as_of="2026-03-25T00:00:00+00:00",
    )

    assert positions[0].internal_id == "FUT:ZF:CBOT"
    assert positions[0].avg_cost == 106.25
    assert positions[0].market_value == 318750
    assert table.require_internal_id("ibkr", "999002") == "FUT:ZF:CBOT"


def test_normalize_ibkr_positions_marks_options_outside_scope() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "701332964",
                "sec_type": "OPT",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "AMEX",
                "local_symbol": "SPY   260618P00620000",
                "position": "1",
                "market_value": "-100",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].internal_id == "OUTSIDE_SCOPE:OPT:SPY_260618P00620000:AMEX"
    assert table.get_security("OUTSIDE_SCOPE:OPT:SPY_260618P00620000:AMEX").mapping_status == "outside_scope"


def test_normalize_ibkr_positions_attaches_option_delta_exposure() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "999001",
                "sec_type": "OPT",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "AMEX",
                "local_symbol": "SPY   260618C00600000",
                "multiplier": "100",
                "position": "2",
                "market_value": "2500",
                "option_delta": "0.5",
                "option_underlying_price": "600",
                "option_implied_vol": "0.2",
                "option_greeks_source": "modelGreeks",
                "option_greeks_status": "available",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].option_delta == pytest.approx(0.5)
    assert positions[0].option_underlying_price == pytest.approx(600.0)
    assert positions[0].option_delta_exposure_usd == pytest.approx(60_000.0)
    assert positions[0].option_underlying_internal_id == "STK:SPY:SMART"


def test_normalize_ibkr_positions_keeps_option_contract_ids_distinct() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "999001",
                "sec_type": "OPT",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "AMEX",
                "local_symbol": "SPY   260618C00600000",
                "position": "1",
                "market_value": "100",
            },
            {
                "account": "U12345",
                "con_id": "999002",
                "sec_type": "OPT",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "AMEX",
                "local_symbol": "SPY   260618P00500000",
                "position": "1",
                "market_value": "100",
            },
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert [position.internal_id for position in positions] == [
        "OUTSIDE_SCOPE:OPT:SPY_260618C00600000:AMEX",
        "OUTSIDE_SCOPE:OPT:SPY_260618P00500000:AMEX",
    ]


def test_normalize_ibkr_positions_flips_option_delta_exposure_for_short_quantity() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "999003",
                "sec_type": "OPT",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "AMEX",
                "local_symbol": "SPY   260618C00600000",
                "multiplier": "100",
                "position": "-1",
                "market_value": "-1200",
                "option_delta": "0.5",
                "option_underlying_price": "600",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].option_delta_exposure_usd == pytest.approx(-30_000.0)


def test_normalize_ibkr_positions_marks_futures_options_outside_scope() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "792265603",
                "sec_type": "FOP",
                "symbol": "MCL",
                "currency": "USD",
                "exchange": "NYMEX",
                "local_symbol": "MCON6 C8525",
                "position": "1",
                "market_value": "589.24",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].internal_id == "OUTSIDE_SCOPE:FOP:MCL:NYMEX"
    assert table.get_security("OUTSIDE_SCOPE:FOP:MCL:NYMEX").mapping_status == "outside_scope"


def test_normalize_ibkr_positions_marks_unmapped_instruments() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "accountId": "U12345",
                "conid": "888888",
                "secType": "STK",
                "symbol": "AAPL",
                "currency": "USD",
                "exchange": "SMART",
                "position": "20",
                "avgCost": "210.5",
                "marketValue": "4300",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].account == "U12345"
    assert positions[0].avg_cost == 210.5
    assert positions[0].internal_id == "STK:AAPL:SMART"
    assert table.get_security("STK:AAPL:SMART").mapping_status == "unmapped"


def test_normalize_ibkr_positions_prefers_primary_exchange_and_unique_symbol_match() -> None:
    table = _curated_reference_table()
    positions = normalize_ibkr_positions(
        [
            {
                "accountId": "U12345",
                "conid": "756733",
                "secType": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "SMART",
                "primaryExchange": "ARCA",
                "position": "20",
            }
        ],
        table,
        as_of="2026-03-26T00:00:00+00:00",
    )

    assert positions[0].internal_id == "STK:SPY:SMART"


def test_normalize_ibkr_latest_prices_accepts_market_price_alias() -> None:
    table = _curated_reference_table()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "ARCA",
                "position": "20",
            }
        ],
        table,
    )

    prices = normalize_ibkr_latest_prices(
        [{"conId": "756733", "marketPrice": "214.8"}],
        table,
    )
    assert prices[0].last_price == 214.8


def test_normalize_ibkr_latest_prices_raises_when_no_price_fields() -> None:
    table = _curated_reference_table()
    normalize_ibkr_positions(
        [
            {
                "account": "U12345",
                "con_id": "756733",
                "sec_type": "STK",
                "symbol": "SPY",
                "currency": "USD",
                "exchange": "ARCA",
                "position": "20",
            }
        ],
        table,
    )

    with pytest.raises(ValueError):
        normalize_ibkr_latest_prices([{"con_id": "756733"}], table)
