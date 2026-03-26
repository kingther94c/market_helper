from market_helper.portfolio import (
    SecurityMapping,
    SecurityReference,
    SecurityReferenceTable,
    build_price_lookup,
    join_positions_with_latest_price,
)
from market_helper.portfolio.security_reference import PositionSnapshot, PriceSnapshot


def test_reference_table_resolves_cross_source_ids() -> None:
    reference = SecurityReferenceTable()
    security = SecurityReference(
        internal_id="SEC:ESM6",
        asset_class="future",
        symbol="ES",
        currency="USD",
        exchange="CME",
    )
    reference.add_security_with_mappings(
        security,
        mappings=[
            SecurityMapping(source="ibkr", external_id="497222760", internal_id="SEC:ESM6"),
            SecurityMapping(source="bbg", external_id="ESM6 Index", internal_id="SEC:ESM6"),
            SecurityMapping(source="yahoo", external_id="ES=F", internal_id="SEC:ESM6"),
        ],
    )

    assert reference.require_internal_id("ibkr", "497222760") == "SEC:ESM6"
    assert reference.require_internal_id("bbg", "ESM6 Index") == "SEC:ESM6"
    assert reference.require_internal_id("yahoo", "ES=F") == "SEC:ESM6"


def test_join_positions_with_latest_price() -> None:
    positions = [
        PositionSnapshot(
            as_of="2026-03-25T00:00:00+00:00",
            account="U12345",
            internal_id="SEC:SPY",
            source="ibkr",
            quantity=100,
            avg_cost=500.0,
            market_value=51000.0,
        )
    ]
    prices = build_price_lookup(
        [
            PriceSnapshot(
                as_of="2026-03-25T00:00:00+00:00",
                internal_id="SEC:SPY",
                source="ibkr",
                last_price=510.0,
            )
        ]
    )

    rows = join_positions_with_latest_price(positions, prices)
    assert rows[0]["latest_price"] == 510.0
