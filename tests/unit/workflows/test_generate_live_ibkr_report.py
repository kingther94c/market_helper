import csv

from market_helper.workflows.generate_report import generate_live_ibkr_position_report


class FakeContract:
    def __init__(self) -> None:
        self.conId = 756733
        self.secType = "STK"
        self.symbol = "SPY"
        self.currency = "USD"
        self.exchange = "ARCA"
        self.primaryExchange = "ARCA"
        self.localSymbol = "SPY"
        self.multiplier = "1"


class FakePortfolioItem:
    def __init__(self) -> None:
        self.account = "U12345"
        self.contract = FakeContract()
        self.position = 20
        self.averageCost = 210.5
        self.marketPrice = 214.8
        self.marketValue = 4300


class FakeLiveClient:
    def __init__(self) -> None:
        self.connected = False
        self.disconnected = False

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def list_accounts(self) -> list[str]:
        return ["U12345"]

    def list_portfolio(self, account_id: str) -> list[object]:
        assert account_id == "U12345"
        return [FakePortfolioItem()]


def test_generate_live_ibkr_position_report_writes_csv_from_gateway_client(tmp_path) -> None:
    output_path = tmp_path / "outputs" / "live_position_report.csv"
    client = FakeLiveClient()

    written_path = generate_live_ibkr_position_report(
        output_path=output_path,
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=client,
    )

    assert written_path == output_path
    assert client.connected is True
    assert client.disconnected is True
    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert rows[0]["internal_id"] == "STK:SPY:ARCA"
    assert rows[0]["con_id"] == "756733"
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["exchange"] == "ARCA"
    assert rows[0]["currency"] == "USD"
    assert rows[0]["latest_price"] == "214.8"
    assert rows[0]["unrealized_pnl"] == "90.0"


class FakeUnmappedContract:
    def __init__(self) -> None:
        self.conId = 888888
        self.secType = "STK"
        self.symbol = "AAPL"
        self.currency = "USD"
        self.exchange = "SMART"
        self.primaryExchange = "SMART"
        self.localSymbol = "AAPL"
        self.multiplier = "1"


class FakeUnmappedPortfolioItem:
    def __init__(self) -> None:
        self.account = "U12345"
        self.contract = FakeUnmappedContract()
        self.position = 20
        self.averageCost = 210.5
        self.marketPrice = 214.8
        self.marketValue = 4300


class FakeUnmappedLiveClient(FakeLiveClient):
    def list_portfolio(self, account_id: str) -> list[object]:
        assert account_id == "U12345"
        return [FakeUnmappedPortfolioItem()]

    def lookup_security(self, contract=None, **kwargs) -> dict[str, object]:
        return {
            "conId": 888888,
            "symbol": "AAPL",
            "secType": "STK",
            "currency": "USD",
            "exchange": "SMART",
            "primaryExchange": "SMART",
            "localSymbol": "AAPL",
            "marketName": "NMS",
            "longName": "Apple Inc",
            "multiplier": "1",
        }


def test_generate_live_ibkr_position_report_writes_proposed_reference_for_unmapped_rows(
    tmp_path,
    capsys,
) -> None:
    output_path = tmp_path / "outputs" / "live_position_report.csv"
    client = FakeUnmappedLiveClient()

    generate_live_ibkr_position_report(
        output_path=output_path,
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=client,
    )

    proposal_path = output_path.with_name("security_reference_PROPOSED.csv")
    with proposal_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["internal_id"] == "STK:AAPL:SMART"
    assert rows[0]["display_name"] == "Apple Inc"
    assert rows[0]["ibkr_conid"] == "888888"
    assert "security_reference_PROPOSED.csv" in capsys.readouterr().out
