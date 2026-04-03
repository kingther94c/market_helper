import csv
import json

from market_helper.domain.portfolio_monitor.pipelines.generate_portfolio_report import (
    build_live_ibkr_position_security_table,
    generate_position_report,
)


def test_generate_position_report_pipeline_writes_csv(tmp_path) -> None:
    positions_path = tmp_path / "positions.json"
    prices_path = tmp_path / "prices.json"
    output_path = tmp_path / "position_report.csv"

    positions_path.write_text(
        json.dumps(
            [
                {
                    "as_of": "2026-03-26T00:00:00+00:00",
                    "account": "U12345",
                    "internal_id": "SEC:SPY",
                    "source": "ibkr",
                    "quantity": 100,
                    "avg_cost": 500.0,
                    "market_value": 51000.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    prices_path.write_text(
        json.dumps(
            [
                {
                    "as_of": "2026-03-26T00:00:00+00:00",
                    "internal_id": "SEC:SPY",
                    "source": "ibkr",
                    "last_price": 510.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    generate_position_report(
        positions_path=positions_path,
        prices_path=prices_path,
        output_path=output_path,
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows[0]["internal_id"] == "SEC:SPY"


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

    def lookup_security(self, *, contract: object) -> dict[str, object]:
        assert getattr(contract, "conId") == 756733
        return {
            "conId": 756733,
            "symbol": "SPY",
            "secType": "STK",
            "currency": "USD",
            "exchange": "ARCA",
            "primaryExchange": "ARCA",
            "localSymbol": "SPY",
            "marketName": "SPY",
            "minTick": 0.01,
            "priceMagnifier": 1,
            "orderTypes": "MKT,LMT",
            "validExchanges": "SMART,ARCA",
            "tradingHours": "20260326:0400-20260326:2000",
            "liquidHours": "20260326:0930-20260326:1600",
            "longName": "SPDR S&P 500 ETF TRUST",
            "industry": "",
            "category": "",
            "subcategory": "",
        }


def test_build_live_ibkr_position_security_table_merges_position_reference_and_contract_details() -> None:
    client = FakeLiveClient()

    rows = build_live_ibkr_position_security_table(
        account_id="U12345",
        as_of="2026-03-26T00:00:00+00:00",
        client=client,
    )

    assert client.connected is True
    assert client.disconnected is True
    assert len(rows) == 1
    row = rows[0]

    assert row["internal_id"] == "ETF:SPY:ARCA"
    assert row["con_id"] == "756733"
    assert row["local_symbol"] == "SPY"
    assert row["quantity"] == 20.0
    assert row["latest_price"] == 214.8
    assert row["unrealized_pnl"] == 90.0
    assert row["ibkr_conid"] == 756733
    assert row["ibkr_sec_type"] == "STK"
    assert row["contract_long_name"] == "SPDR S&P 500 ETF TRUST"
    assert row["contract_primary_exchange"] == "ARCA"
    assert row["security_mapping_status"] == "mapped"
    assert row["security_universe_type"] == "ETF"
    assert row["security_display_ticker"] == "SPY"
    assert row["security_display_name"] == "US"
    assert row["security_report_category"] == "DMEQ"
    assert row["security_risk_bucket"] == "EQ"
    assert row["security_price_source_provider"] == "google_finance"
    assert row["security_price_source_symbol"] == "SPY"
    assert row["security_runtime_local_symbol"] == "SPY"
