from market_helper.portfolio import (
    SecurityMapping,
    SecurityReference,
    SecurityReferenceTable,
    build_price_lookup,
    export_security_reference_csv,
    join_positions_with_latest_price,
)
from market_helper.portfolio.security_reference import PositionSnapshot, PriceSnapshot


def test_reference_table_loads_curated_csv_and_resolves_indexes(tmp_path) -> None:
    export_path = tmp_path / "security_reference.csv"
    export_security_reference_csv(
        [
            SecurityReference(
                internal_id="ETF:SPY:ARCA",
                universe_type="ETF",
                canonical_symbol="SPY",
                display_ticker="SPY",
                display_name="US",
                currency="USD",
                primary_exchange="ARCA",
                multiplier=1.0,
                ibkr_sec_type="STK",
                ibkr_symbol="SPY",
                ibkr_exchange="ARCA",
                ibkr_conid="756733",
                google_symbol="SPY",
                yahoo_symbol="SPY",
                bbg_symbol="SPY US Equity",
                report_category="DMEQ",
                risk_bucket="EQ",
                mod_duration=1.0,
                default_expected_vol=0.15,
                price_source_provider="google_finance",
                price_source_symbol="SPY",
            ),
            SecurityReference(
                internal_id="FI_FUT:ZN:CBOT",
                universe_type="FI_FUT",
                canonical_symbol="ZN",
                display_ticker="ZNW00:CBOT",
                display_name="10Y TF",
                currency="USD",
                primary_exchange="CBOT",
                multiplier=1000.0,
                ibkr_sec_type="FUT",
                ibkr_symbol="ZN",
                ibkr_exchange="CBOT",
                google_symbol="ZNW00:CBOT",
                yahoo_symbol="ZN=F",
                report_category="FI",
                risk_bucket="FI",
                mod_duration=7.627,
                default_expected_vol=0.07,
                price_source_provider="google_finance",
                price_source_symbol="ZNW00:CBOT",
            ),
            SecurityReference(
                internal_id="CASH:USD:IDEALPRO",
                universe_type="CASH",
                canonical_symbol="USD",
                display_ticker="USD Cash",
                display_name="USD Cash",
                currency="USD",
                primary_exchange="IDEALPRO",
                multiplier=1.0,
                ibkr_sec_type="CASH",
                ibkr_symbol="USD",
                ibkr_exchange="IDEALPRO",
                report_category="CASH",
                risk_bucket="CASH",
                mod_duration=0.0,
                default_expected_vol=0.0,
                price_source_provider="manual",
                price_source_symbol="USD Cash",
            ),
        ],
        export_path,
    )

    reference = SecurityReferenceTable.from_csv(export_path)

    assert reference.by_internal_id["ETF:SPY:ARCA"].display_ticker == "SPY"
    assert reference.by_ibkr_conid["756733"].internal_id == "ETF:SPY:ARCA"
    assert reference.by_google_symbol["SPY"].internal_id == "ETF:SPY:ARCA"
    assert reference.by_yahoo_symbol["SPY"].internal_id == "ETF:SPY:ARCA"
    assert reference.by_bbg_symbol["SPY US EQUITY"].internal_id == "ETF:SPY:ARCA"
    assert reference.resolve_by_ibkr_alias(symbol="SPY", sec_type="STK", exchange="ARCA")
    assert reference.resolve_by_ibkr_alias(symbol="ZNM6", sec_type="FUT", exchange="CBOT").internal_id == "FI_FUT:ZN:CBOT"
    assert reference.resolve_by_ibkr_alias(symbol="ZN", sec_type="FUT", exchange="CBOT").internal_id == "FI_FUT:ZN:CBOT"
    assert reference.resolve_cash_reference(symbol="USD", currency="USD").internal_id == "CASH:USD:IDEALPRO"


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
