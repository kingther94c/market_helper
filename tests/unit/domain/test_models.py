from market_helper.domain import (
    AccountSnapshot,
    AllocationRow,
    MonitorView,
    PositionSnapshot,
    RiskRow,
)


def test_monitor_view_contains_domain_rows() -> None:
    account = AccountSnapshot(
        as_of="2026-03-26T00:00:00+00:00",
        account_id="U12345",
        net_liquidation=150000.0,
        available_funds=50000.0,
    )
    position = PositionSnapshot(
        as_of="2026-03-26T00:00:00+00:00",
        account_id="U12345",
        contract_id="IBKR:756733",
        quantity=20,
        avg_cost=210.5,
        market_value=4300.0,
    )

    monitor = MonitorView(
        generated_at="2026-03-26T00:01:00+00:00",
        account=account,
        positions=[position],
        allocations=[AllocationRow(contract_id="IBKR:756733", weight=0.2, market_value=4300.0)],
        risks=[RiskRow(contract_id="IBKR:756733", exposure=4300.0, concentration=0.2)],
    )

    assert monitor.account.account_id == "U12345"
    assert monitor.positions[0].contract_id == "IBKR:756733"
    assert monitor.allocations[0].weight == 0.2
