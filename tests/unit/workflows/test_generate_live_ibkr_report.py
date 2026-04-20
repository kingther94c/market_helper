import csv

import pytest

from market_helper.common.progress import RecordingProgressReporter
from market_helper.portfolio import SecurityReference, export_security_reference_csv
from market_helper.workflows.generate_report import generate_live_ibkr_position_report
import market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report as report_pipeline


@pytest.fixture(autouse=True)
def disable_default_artifact_mirror(monkeypatch) -> None:
    monkeypatch.setattr(report_pipeline, "_load_artifact_mirror_dir", lambda config_path=None: None)


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

    def list_account_values(self, account_id: str) -> list[object]:
        assert account_id == "U12345"
        return []


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

    assert rows[0]["internal_id"] == "STK:SPY:SMART"
    assert rows[0]["con_id"] == "756733"
    assert rows[0]["symbol"] == "SPY"
    assert rows[0]["exchange"] == "ARCA"
    assert rows[0]["currency"] == "USD"
    assert rows[0]["latest_price"] == "214.8"
    assert rows[0]["unrealized_pnl"] == "90.0"


def test_generate_live_ibkr_position_report_mirrors_csv_to_google_drive(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / "outputs" / "live_position_report.csv"
    mirror_dir = tmp_path / "google-drive"
    client = FakeLiveClient()

    monkeypatch.setattr(report_pipeline, "_load_artifact_mirror_dir", lambda config_path=None: mirror_dir)

    generate_live_ibkr_position_report(
        output_path=output_path,
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=client,
    )

    mirrored_path = mirror_dir / "live_ibkr_position_report.csv"
    assert mirrored_path.exists()
    assert mirrored_path.read_text(encoding="utf-8") == output_path.read_text(encoding="utf-8")


def test_generate_live_ibkr_position_report_reports_progress(tmp_path) -> None:
    output_path = tmp_path / "outputs" / "live_position_report.csv"
    client = FakeLiveClient()
    reporter = RecordingProgressReporter()

    generate_live_ibkr_position_report(
        output_path=output_path,
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=client,
        progress=reporter,
    )

    assert reporter.events[0] == {"kind": "stage", "label": "IBKR live report", "current": 0, "total": 6}
    assert reporter.events[1] == {
        "kind": "spinner",
        "label": "IBKR live report",
        "detail": "connecting",
    }
    assert reporter.events[-1] == {
        "kind": "done",
        "label": "IBKR live report",
        "detail": f"wrote {output_path}",
    }


class FakeCashAccountValue:
    def __init__(self, *, tag: str, currency: str, value: str) -> None:
        self.account = "U12345"
        self.tag = tag
        self.value = value
        self.currency = currency
        self.modelCode = ""


class FakeLiveClientWithCash(FakeLiveClient):
    def list_account_values(self, account_id: str) -> list[object]:
        assert account_id == "U12345"
        return [
            FakeCashAccountValue(tag="TotalCashBalance", currency="USD", value="1250.5"),
            FakeCashAccountValue(tag="ExchangeRate", currency="USD", value="1.3"),
            FakeCashAccountValue(tag="ExchangeRate", currency="SGD", value="1.0"),
        ]


def test_generate_live_ibkr_position_report_includes_cash_rows(tmp_path) -> None:
    output_path = tmp_path / "outputs" / "live_position_report.csv"
    client = FakeLiveClientWithCash()

    generate_live_ibkr_position_report(
        output_path=output_path,
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=client,
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    cash_rows = [row for row in rows if row["internal_id"] == "CASH:SGD_CASH_VALUE:MANUAL"]
    assert len(cash_rows) == 1
    assert cash_rows[0]["symbol"] == "SGD_CASH_VALUE"
    assert cash_rows[0]["latest_price"] == "1.0"
    assert cash_rows[0]["market_value"] == "1625.65"


class FakeAccountValue:
    def __init__(self, *, tag: str, currency: str, value: str) -> None:
        self.account = "U12345"
        self.tag = tag
        self.value = value
        self.currency = currency
        self.modelCode = ""


class FakeLiveClientWithMultiCurrencyCash(FakeLiveClient):
    def list_account_values(self, account_id: str) -> list[object]:
        assert account_id == "U12345"
        return [
            FakeAccountValue(tag="TotalCashBalance", currency="USD", value="-100"),
            FakeAccountValue(tag="TotalCashBalance", currency="EUR", value="-5"),
            FakeAccountValue(tag="TotalCashBalance", currency="SGD", value="-10"),
            FakeAccountValue(tag="ExchangeRate", currency="USD", value="1.3"),
            FakeAccountValue(tag="ExchangeRate", currency="EUR", value="1.5"),
            FakeAccountValue(tag="ExchangeRate", currency="SGD", value="1.0"),
        ]


def test_generate_live_ibkr_position_report_converts_multi_currency_cash_to_sgd(tmp_path) -> None:
    output_path = tmp_path / "outputs" / "live_position_report.csv"
    client = FakeLiveClientWithMultiCurrencyCash()

    generate_live_ibkr_position_report(
        output_path=output_path,
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=client,
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    cash_rows = [row for row in rows if row["internal_id"] == "CASH:SGD_CASH_VALUE:MANUAL"]
    assert len(cash_rows) == 1
    assert cash_rows[0]["symbol"] == "SGD_CASH_VALUE"
    assert cash_rows[0]["market_value"] == "-147.5"


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

    proposal_path = output_path.with_name("security_universe_PROPOSED.csv")
    with proposal_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["ibkr_symbol"] == "AAPL"
    assert rows[0]["display_name"] == "Apple Inc"
    assert rows[0]["lookup_conid"] == "888888"
    assert "security_universe_PROPOSED.csv" in capsys.readouterr().out


class FakeDbmfContract:
    def __init__(self) -> None:
        self.conId = 515416076
        self.secType = "STK"
        self.symbol = "DBMF"
        self.currency = "USD"
        self.exchange = "ARCA"
        self.primaryExchange = "ARCA"
        self.localSymbol = "DBMF"
        self.multiplier = "1"


class FakeDbmfPortfolioItem:
    def __init__(self) -> None:
        self.account = "U12345"
        self.contract = FakeDbmfContract()
        self.position = 10
        self.averageCost = 25.0
        self.marketPrice = 26.0
        self.marketValue = 260.0


class FakeDbmfLiveClient(FakeLiveClient):
    def list_portfolio(self, account_id: str) -> list[object]:
        assert account_id == "U12345"
        return [FakeDbmfPortfolioItem()]

    def lookup_security(self, contract=None, **kwargs) -> dict[str, object]:
        return {
            "conId": 515416076,
            "symbol": "DBMF",
            "secType": "STK",
            "currency": "USD",
            "exchange": "ARCA",
            "primaryExchange": "ARCA",
            "localSymbol": "DBMF",
            "marketName": "ARCA",
            "longName": "IMGP DBI MANAGED FUTURES STR",
            "multiplier": "1",
        }


def test_generate_live_ibkr_position_report_uses_lookup_to_match_smart_listing_without_proposal(
    tmp_path,
    monkeypatch,
) -> None:
    security_reference_path = tmp_path / "security_reference.csv"
    export_security_reference_csv(
        [
            SecurityReference(
                internal_id="STK:DBMF:SMART",
                asset_class="MACRO",
                canonical_symbol="DBMF",
                display_ticker="DBMF",
                display_name="Trend",
                currency="USD",
                primary_exchange="",
                multiplier=1.0,
                ibkr_sec_type="STK",
                ibkr_symbol="DBMF",
                ibkr_exchange="SMART",
                yahoo_symbol="DBMF",
                dir_exposure="L",
                lookup_status="seeded",
            ),
            SecurityReference(
                internal_id="STK:DBMF:SBF",
                asset_class="MACRO",
                canonical_symbol="DBMF",
                display_ticker="DBMF",
                display_name="Trend",
                currency="USD",
                primary_exchange="SBF",
                multiplier=1.0,
                ibkr_sec_type="STK",
                ibkr_symbol="DBMF",
                ibkr_exchange="SBF",
                yahoo_symbol="DBMF.L",
                dir_exposure="L",
                lookup_status="verified",
            ),
        ],
        security_reference_path,
    )
    monkeypatch.setattr(report_pipeline, "DEFAULT_SECURITY_REFERENCE_PATH", security_reference_path)

    output_path = tmp_path / "outputs" / "live_position_report.csv"
    client = FakeDbmfLiveClient()

    generate_live_ibkr_position_report(
        output_path=output_path,
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=client,
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["internal_id"] == "STK:DBMF:SMART"
    proposal_path = output_path.with_name("security_universe_PROPOSED.csv")
    assert proposal_path.exists() is False
