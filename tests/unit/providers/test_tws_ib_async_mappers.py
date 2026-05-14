from __future__ import annotations

from market_helper.providers.tws_ib_async import (
    portfolio_items_to_ibkr_position_rows,
    portfolio_items_to_ibkr_price_rows,
)


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
        marketPrice: float | None,
        marketValue: float,
        averageCost: float,
    ) -> None:
        self.account = account
        self.contract = contract
        self.position = position
        self.marketPrice = marketPrice
        self.marketValue = marketValue
        self.averageCost = averageCost


def test_portfolio_item_mappers_emit_ibkr_compatible_rows() -> None:
    item = FakePortfolioItem(
        account="U12345",
        contract=FakeContract(
            conId=756733,
            secType="STK",
            symbol="AAPL",
            currency="USD",
            exchange="SMART",
            primaryExchange="NASDAQ",
            localSymbol="AAPL",
        ),
        position=20,
        marketPrice=214.8,
        marketValue=4300,
        averageCost=210.5,
    )

    assert portfolio_items_to_ibkr_position_rows([item]) == [
        {
            "account": "U12345",
            "conId": 756733,
            "secType": "STK",
            "symbol": "AAPL",
            "currency": "USD",
            "exchange": "NASDAQ",
            "localSymbol": "AAPL",
            "multiplier": "1",
            "position": 20,
            "avgCost": 210.5,
            "marketValue": 4300,
            "option_delta": "",
            "option_underlying_price": "",
            "option_implied_vol": "",
            "option_greeks_source": "",
            "option_greeks_status": "",
            "option_underlying_symbol": "",
        }
    ]
    assert portfolio_items_to_ibkr_price_rows([item]) == [
        {"conId": 756733, "marketPrice": 214.8}
    ]


def test_portfolio_item_price_mapper_falls_back_to_market_value_divided_by_quantity() -> None:
    item = FakePortfolioItem(
        account="U12345",
        contract=FakeContract(
            conId=756733,
            secType="STK",
            symbol="AAPL",
            currency="USD",
            exchange="SMART",
        ),
        position=20,
        marketPrice=None,
        marketValue=4300,
        averageCost=210.5,
    )

    assert portfolio_items_to_ibkr_price_rows([item]) == [
        {"conId": 756733, "marketPrice": 215.0}
    ]


def test_portfolio_item_mapper_attaches_option_model_greeks() -> None:
    item = FakePortfolioItem(
        account="U12345",
        contract=FakeContract(
            conId=999001,
            secType="OPT",
            symbol="SPY",
            currency="USD",
            exchange="SMART",
            localSymbol="SPY   260618C00600000",
            multiplier="100",
        ),
        position=2,
        marketPrice=12.5,
        marketValue=2500,
        averageCost=11.0,
    )

    rows = portfolio_items_to_ibkr_position_rows(
        [item],
        option_model_greeks={
            999001: {
                "source": "modelGreeks",
                "status": "available",
                "delta": 0.5,
                "underlying_price": 600.0,
                "implied_vol": 0.2,
            }
        },
    )

    assert rows[0]["option_delta"] == 0.5
    assert rows[0]["option_underlying_price"] == 600.0
    assert rows[0]["option_implied_vol"] == 0.2
    assert rows[0]["option_greeks_source"] == "modelGreeks"
    assert rows[0]["option_greeks_status"] == "available"
    assert rows[0]["option_underlying_symbol"] == "SPY"
