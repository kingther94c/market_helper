import csv

from market_helper.workflows.generate_report import generate_live_ibkr_position_report


class FakeLiveClient:
    def auth_status(self) -> dict[str, object]:
        return {"connected": True, "authenticated": True}

    def tickle(self) -> dict[str, object]:
        return {"session": "abc"}

    def list_accounts(self) -> list[dict[str, object]]:
        return [{"accountId": "U12345"}]

    def list_positions(self, account_id: str) -> list[dict[str, object]]:
        assert account_id == "U12345"
        return [
            {
                "accountId": "U12345",
                "conid": "756733",
                "symbol": "AAPL",
                "secType": "STK",
                "currency": "USD",
                "exchange": "SMART",
                "position": "20",
                "avgCost": "210.5",
                "mktPrice": "214.8",
                "marketValue": "4300",
            }
        ]


def test_generate_live_ibkr_position_report_writes_csv_from_gateway_client(tmp_path) -> None:
    output_path = tmp_path / "outputs" / "live_position_report.csv"

    written_path = generate_live_ibkr_position_report(
        output_path=output_path,
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=FakeLiveClient(),
    )

    assert written_path == output_path
    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert rows[0]["internal_id"] == "IBKR:756733"
    assert rows[0]["latest_price"] == "214.8"
    assert rows[0]["unrealized_pnl"] == "90.0"
