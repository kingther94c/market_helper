from market_helper.portfolio import PriceSnapshot, PositionSnapshot, build_price_lookup
from market_helper.reporting import PositionReportRow, build_position_report_rows


def test_build_position_report_rows_calculates_weights_and_pnl() -> None:
    positions = [
        PositionSnapshot(
            as_of="2026-03-26T00:00:00+00:00",
            account="U12345",
            internal_id="SEC:SPY",
            source="ibkr",
            quantity=100,
            avg_cost=500.0,
            market_value=51000.0,
        ),
        PositionSnapshot(
            as_of="2026-03-26T00:00:00+00:00",
            account="U12345",
            internal_id="SEC:QQQ",
            source="ibkr",
            quantity=50,
            avg_cost=400.0,
            market_value=None,
        ),
    ]
    prices = build_price_lookup(
        [
            PriceSnapshot(
                as_of="2026-03-26T00:00:00+00:00",
                internal_id="SEC:SPY",
                source="ibkr",
                last_price=510.0,
            ),
            PriceSnapshot(
                as_of="2026-03-26T00:00:00+00:00",
                internal_id="SEC:QQQ",
                source="ibkr",
                last_price=410.0,
            ),
        ]
    )

    rows = build_position_report_rows(positions, prices)

    assert rows == [
        PositionReportRow(
            as_of="2026-03-26T00:00:00+00:00",
            account="U12345",
            internal_id="SEC:SPY",
            source="ibkr",
            quantity=100,
            avg_cost=500.0,
            latest_price=510.0,
            market_value=51000.0,
            cost_basis=50000.0,
            unrealized_pnl=1000.0,
            weight=51000.0 / 71500.0,
        ),
        PositionReportRow(
            as_of="2026-03-26T00:00:00+00:00",
            account="U12345",
            internal_id="SEC:QQQ",
            source="ibkr",
            quantity=50,
            avg_cost=400.0,
            latest_price=410.0,
            market_value=20500.0,
            cost_basis=20000.0,
            unrealized_pnl=500.0,
            weight=20500.0 / 71500.0,
        ),
    ]


def test_build_position_report_rows_keeps_missing_market_values_nullable() -> None:
    positions = [
        PositionSnapshot(
            as_of="2026-03-26T00:00:00+00:00",
            account="U12345",
            internal_id="SEC:IWM",
            source="ibkr",
            quantity=10,
            avg_cost=None,
            market_value=None,
        )
    ]

    rows = build_position_report_rows(positions, {})

    assert rows[0].market_value is None
    assert rows[0].cost_basis is None
    assert rows[0].unrealized_pnl is None
    assert rows[0].weight is None
