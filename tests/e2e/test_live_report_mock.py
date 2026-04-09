import csv
from pathlib import Path

from market_helper.cli.main import main
from market_helper.reporting import POSITION_REPORT_HEADERS


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "live_ibkr_position_report_mock.csv"
LIVE_ACCOUNT_ID = "U1234567"
PAPER_ACCOUNT_ID = "DU1234567"


class FakeContract:
    def __init__(
        self,
        *,
        conId: int,
        secType: str,
        symbol: str,
        currency: str,
        exchange: str,
        primaryExchange: str = "",
        localSymbol: str = "",
        multiplier: str = "1",
    ) -> None:
        self.conId = conId
        self.secType = secType
        self.symbol = symbol
        self.currency = currency
        self.exchange = exchange
        self.primaryExchange = primaryExchange
        self.localSymbol = localSymbol
        self.multiplier = multiplier


class FakePortfolioItem:
    def __init__(
        self,
        *,
        account: str,
        contract: FakeContract,
        position: float,
        averageCost: float,
        marketPrice: float,
        marketValue: float,
    ) -> None:
        self.account = account
        self.contract = contract
        self.position = position
        self.averageCost = averageCost
        self.marketPrice = marketPrice
        self.marketValue = marketValue


class FakeTwsIbAsyncClient:
    created: list["FakeTwsIbAsyncClient"] = []

    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_id: int,
        timeout: float,
        account: str,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.timeout = timeout
        self.account = account
        self.connected = False
        self.disconnected = False
        self.__class__.created.append(self)

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.disconnected = True

    def list_accounts(self) -> list[str]:
        return [LIVE_ACCOUNT_ID, PAPER_ACCOUNT_ID]

    def list_portfolio(self, account_id: str) -> list[object]:
        assert account_id == LIVE_ACCOUNT_ID
        return [
            FakePortfolioItem(
                account=LIVE_ACCOUNT_ID,
                contract=FakeContract(
                    conId=91812967,
                    secType="STK",
                    symbol="ACWD",
                    currency="USD",
                    exchange="SMART",
                    primaryExchange="LSEETF",
                    localSymbol="ACWD",
                ),
                position=300.0,
                averageCost=299.38974535,
                marketPrice=282.34020995,
                marketValue=84702.06,
            ),
            FakePortfolioItem(
                account=LIVE_ACCOUNT_ID,
                contract=FakeContract(
                    conId=818615223,
                    secType="FUT",
                    symbol="ZF",
                    currency="USD",
                    exchange="CBOT",
                    localSymbol="ZFM6",
                    multiplier="1000",
                ),
                position=4.0,
                averageCost=109712.5943,
                marketPrice=107.8125,
                marketValue=431250.0,
            ),
            FakePortfolioItem(
                account=LIVE_ACCOUNT_ID,
                contract=FakeContract(
                    conId=815824229,
                    secType="FUT",
                    symbol="ZN",
                    currency="USD",
                    exchange="CBOT",
                    localSymbol="ZNM6",
                    multiplier="1000",
                ),
                position=1.0,
                averageCost=113212.7578,
                marketPrice=110.625,
                marketValue=110625.0,
            ),
        ]


def test_cli_live_report_mock_e2e_matches_expected_csv(monkeypatch, tmp_path) -> None:
    FakeTwsIbAsyncClient.created = []
    monkeypatch.setattr(
        "market_helper.workflows.generate_report.TwsIbAsyncClient",
        FakeTwsIbAsyncClient,
    )

    output_path = tmp_path / "outputs" / "live_ibkr_position_report.csv"

    exit_code = main(
        [
            "ibkr-live-position-report",
            "--output",
            str(output_path),
            "--host",
            "127.0.0.1",
            "--port",
            "7497",
            "--client-id",
            "7",
            "--account",
            LIVE_ACCOUNT_ID,
            "--timeout",
            "9.5",
            "--as-of",
            "2026-03-26T14:09:26+00:00",
        ]
    )

    assert exit_code == 0
    assert output_path.exists()
    assert len(FakeTwsIbAsyncClient.created) == 1

    client = FakeTwsIbAsyncClient.created[0]
    assert client.host == "127.0.0.1"
    assert client.port == 7497
    assert client.client_id == 7
    assert client.timeout == 9.5
    assert client.account == LIVE_ACCOUNT_ID
    assert client.connected is True
    assert client.disconnected is True

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        actual_reader = csv.DictReader(handle)
        actual_rows = list(actual_reader)

    with FIXTURE_PATH.open("r", encoding="utf-8", newline="") as handle:
        expected_reader = csv.DictReader(handle)
        expected_rows = list(expected_reader)

    assert actual_reader.fieldnames == POSITION_REPORT_HEADERS
    assert expected_reader.fieldnames == POSITION_REPORT_HEADERS
    assert actual_rows == expected_rows
