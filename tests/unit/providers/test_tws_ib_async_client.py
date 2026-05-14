from __future__ import annotations

import pytest

import market_helper.providers.tws_ib_async.client as client_module
from market_helper.providers.tws_ib_async import TwsIbAsyncClient, TwsIbAsyncError, choose_tws_account


class _FakeRawClient:
    def __init__(self) -> None:
        self.raw_account_updates_calls: list[tuple[bool, str]] = []

    def reqAccountUpdates(self, subscribe: bool, account: str = "") -> None:
        self.raw_account_updates_calls.append((subscribe, account))


class FakeIb:
    def __init__(
        self,
        *,
        connected: bool = True,
        empty_portfolio: bool = False,
    ) -> None:
        self.connected = connected
        self.connected_with: dict[str, object] | None = None
        self.disconnected = False
        self.async_account_updates_calls: list[str] = []
        self._empty_portfolio = empty_portfolio
        self._portfolio_refills: list[str] = []
        self.client = _FakeRawClient()

    def connect(
        self,
        *,
        host: str,
        port: int,
        clientId: int,
        timeout: float,
        readonly: bool,
        account: str,
    ) -> None:
        self.connected_with = {
            "host": host,
            "port": port,
            "clientId": clientId,
            "timeout": timeout,
            "readonly": readonly,
            "account": account,
        }

    def isConnected(self) -> bool:
        return self.connected

    def disconnect(self) -> None:
        self.disconnected = True

    def managedAccounts(self) -> list[str]:
        return ["U12345", "U99999"]

    async def reqAccountUpdatesAsync(self, account: str) -> None:
        self.async_account_updates_calls.append(account)
        # Simulate a successful re-subscribe: portfolio is now populated.
        self._portfolio_refills.append(account)

    def run(self, *awaitables, timeout: float | None = None) -> object:
        import asyncio

        future = awaitables[0]
        if timeout is not None:
            future = asyncio.wait_for(future, timeout)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(future)
        finally:
            loop.close()

    def portfolio(self, account: str = "") -> list[object]:
        if self._empty_portfolio and not self._portfolio_refills:
            return []
        return [{"account": account or "ALL"}]

    def accountValues(self, account: str = "") -> list[object]:
        return [
            {
                "account": account or "ALL",
                "tag": "TotalCashBalance",
                "value": "1234.56",
                "currency": "USD",
                "modelCode": "",
            }
        ]


def test_tws_ib_async_client_connects_and_reads_accounts_and_portfolio() -> None:
    fake_ib = FakeIb()
    client = TwsIbAsyncClient(
        host="127.0.0.1",
        port=7497,
        client_id=7,
        timeout=9.5,
        account="U12345",
        ib_factory=lambda: fake_ib,
    )

    client.connect()

    assert fake_ib.connected_with == {
        "host": "127.0.0.1",
        "port": 7497,
        "clientId": 7,
        "timeout": 9.5,
        "readonly": True,
        "account": "U12345",
    }
    assert client.list_accounts() == ["U12345", "U99999"]
    assert client.list_portfolio("U12345") == [{"account": "U12345"}]
    # Non-empty portfolio means no forced re-subscribe is needed.
    assert fake_ib.async_account_updates_calls == []
    assert fake_ib.client.raw_account_updates_calls == []
    assert client.list_account_values("U12345") == [
        {
            "account": "U12345",
            "tag": "TotalCashBalance",
            "value": "1234.56",
            "currency": "USD",
            "modelCode": "",
        }
    ]

    client.disconnect()
    assert fake_ib.disconnected is True


def test_list_portfolio_forces_resubscribe_when_portfolio_is_empty() -> None:
    fake_ib = FakeIb(empty_portfolio=True)
    client = TwsIbAsyncClient(
        host="127.0.0.1",
        port=7497,
        client_id=1,
        timeout=4.0,
        account="U12345",
        ib_factory=lambda: fake_ib,
    )

    client.connect()
    rows = client.list_portfolio("U12345")

    # First read returned empty, so the client should unsubscribe then
    # re-subscribe and retry the read.
    assert fake_ib.client.raw_account_updates_calls == [(False, "U12345")]
    assert fake_ib.async_account_updates_calls == ["U12345"]
    assert rows == [{"account": "U12345"}]


def test_ensure_ib_async_notebook_compat_patches_running_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    class RunningLoop:
        def is_running(self) -> bool:
            return True

    called = False

    def fake_patch() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(client_module.asyncio, "get_running_loop", lambda: RunningLoop())
    monkeypatch.setattr(client_module, "_patch_nested_asyncio", fake_patch)

    client_module._ensure_ib_async_notebook_compat()

    assert called is True


def test_ensure_ib_async_notebook_compat_skips_without_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_patch() -> None:
        nonlocal called
        called = True

    def raise_no_loop():
        raise RuntimeError("no running event loop")

    monkeypatch.setattr(client_module.asyncio, "get_running_loop", raise_no_loop)
    monkeypatch.setattr(client_module, "_patch_nested_asyncio", fake_patch)

    client_module._ensure_ib_async_notebook_compat()

    assert called is False


def test_tws_ib_async_client_raises_when_connection_never_becomes_ready() -> None:
    client = TwsIbAsyncClient(ib_factory=lambda: FakeIb(connected=False))

    with pytest.raises(TwsIbAsyncError):
        client.connect()


def test_choose_tws_account_prefers_requested_id_and_falls_back_to_first() -> None:
    assert choose_tws_account(["U12345", "U99999"], "U99999") == "U99999"
    assert choose_tws_account(["U12345", "U99999"], None) == "U12345"


def test_choose_tws_account_raises_for_unknown_requested_id() -> None:
    with pytest.raises(TwsIbAsyncError):
        choose_tws_account(["U12345"], "U99999")


class FakeContract:
    def __init__(
        self,
        *,
        con_id: int = 31662,
        symbol: str = "XLK",
        sec_type: str = "STK",
        currency: str = "USD",
        exchange: str = "SMART",
        primary_exchange: str = "ARCA",
        local_symbol: str = "XLK",
    ) -> None:
        self.conId = con_id
        self.symbol = symbol
        self.secType = sec_type
        self.currency = currency
        self.exchange = exchange
        self.primaryExchange = primary_exchange
        self.localSymbol = local_symbol


class FakePortfolioItem:
    def __init__(self, contract: object) -> None:
        self.contract = contract


class FakeModelGreeks:
    def __init__(
        self,
        *,
        delta: float | None = 0.42,
        und_price: float | None = 600.0,
        implied_vol: float | None = 0.2,
    ) -> None:
        self.delta = delta
        self.undPrice = und_price
        self.impliedVol = implied_vol


class FakeTicker:
    def __init__(self, model_greeks: object | None) -> None:
        self.modelGreeks = model_greeks


class FakeIbGreeks(FakeIb):
    def __init__(self, *, ticker: FakeTicker) -> None:
        super().__init__()
        self.ticker = ticker
        self.requested_contracts: list[object] = []
        self.cancelled_contracts: list[object] = []

    def reqMktData(self, contract, genericTickList, snapshot, regulatorySnapshot, mktDataOptions):
        self.requested_contracts.append(contract)
        return self.ticker

    def cancelMktData(self, contract) -> bool:
        self.cancelled_contracts.append(contract)
        return True

    def sleep(self, secs: float = 0.02) -> bool:
        return True


def test_fetch_option_model_greeks_reads_model_delta_and_cancels_market_data() -> None:
    contract = FakeContract(
        con_id=999001,
        symbol="SPY",
        sec_type="OPT",
        local_symbol="SPY   260618C00600000",
    )
    fake_ib = FakeIbGreeks(ticker=FakeTicker(FakeModelGreeks(delta=0.42, und_price=600.0, implied_vol=0.2)))
    client = TwsIbAsyncClient(ib_factory=lambda: fake_ib)
    client.connect()

    snapshots = client.fetch_option_model_greeks(
        [FakePortfolioItem(contract)],
        timeout_seconds=0.0,
    )

    assert snapshots == {
        "999001": {
            "source": "modelGreeks",
            "status": "available",
            "delta": 0.42,
            "underlying_price": 600.0,
            "implied_vol": 0.2,
        }
    }
    assert fake_ib.requested_contracts == [contract]
    assert fake_ib.cancelled_contracts == [contract]


def test_fetch_option_model_greeks_marks_missing_model_fields_and_skips_fop() -> None:
    option_contract = FakeContract(
        con_id=999001,
        symbol="SPY",
        sec_type="OPT",
        local_symbol="SPY   260618C00600000",
    )
    fop_contract = FakeContract(
        con_id=999002,
        symbol="MCL",
        sec_type="FOP",
        local_symbol="MCON6 C8525",
    )
    fake_ib = FakeIbGreeks(ticker=FakeTicker(FakeModelGreeks(delta=None, und_price=600.0)))
    client = TwsIbAsyncClient(ib_factory=lambda: fake_ib)
    client.connect()

    snapshots = client.fetch_option_model_greeks(
        [FakePortfolioItem(option_contract), FakePortfolioItem(fop_contract)],
        timeout_seconds=0.0,
    )

    assert snapshots["999001"]["status"] == "missing_delta"
    assert "999002" not in snapshots
    assert fake_ib.requested_contracts == [option_contract]


class FakeContractDetails:
    def __init__(self, contract: object | None = None) -> None:
        self.contract = contract or FakeContract()
        self.marketName = "SPDR Technology Select Sector ETF"
        self.minTick = 0.01
        self.priceMagnifier = 1
        self.orderTypes = "LMT"
        self.validExchanges = "SMART,ARCA"
        self.tradingHours = "20260326:0930-1600"
        self.liquidHours = "20260326:0400-2000"
        self.longName = "Technology Select Sector SPDR Fund"
        self.industry = "Technology"
        self.category = "Sector"
        self.subcategory = "Technology"


class FakeIbContractDetails(FakeIb):
    def __init__(self, *, details: list[object] | None = None) -> None:
        super().__init__()
        self.last_contract = None
        self.details = [FakeContractDetails()] if details is None else details

    def reqContractDetails(self, contract) -> list[object]:
        self.last_contract = contract
        assert getattr(contract, "symbol", None) == "XLK"
        return self.details


def test_tws_ib_async_client_search_securities_with_fake_contract() -> None:
    fake_ib = FakeIbContractDetails()
    client = TwsIbAsyncClient(ib_factory=lambda: fake_ib)

    client.connect()
    info = client.search_securities(contract=FakeContract())

    assert info[0]["symbol"] == "XLK"
    assert info[0]["conId"] == 31662
    assert info[0]["marketName"] == "SPDR Technology Select Sector ETF"
    assert info[0]["industry"] == "Technology"
    assert info[0]["primaryExchange"] == "ARCA"


def test_tws_ib_async_client_search_securities_builds_ib_async_contract() -> None:
    fake_ib = FakeIbContractDetails(details=[FakeContractDetails(FakeContract())])
    client = TwsIbAsyncClient(ib_factory=lambda: fake_ib)

    client.connect()
    info = client.search_securities(
        symbol="XLK",
        sec_type="STK",
        exchange="SMART",
        primary_exchange="ARCA",
        currency="USD",
        conid=31662,
        local_symbol="XLK",
    )

    assert fake_ib.last_contract is not None
    assert fake_ib.last_contract.conId == 31662
    assert fake_ib.last_contract.symbol == "XLK"
    assert fake_ib.last_contract.secType == "STK"
    assert fake_ib.last_contract.exchange == "SMART"
    assert fake_ib.last_contract.primaryExchange == "ARCA"
    assert fake_ib.last_contract.currency == "USD"
    assert fake_ib.last_contract.localSymbol == "XLK"
    assert info[0]["primaryExchange"] == "ARCA"


def test_tws_ib_async_client_lookup_security_returns_single_match() -> None:
    fake_ib = FakeIbContractDetails()
    client = TwsIbAsyncClient(ib_factory=lambda: fake_ib)

    client.connect()
    info = client.lookup_security(
        symbol="XLK",
        sec_type="STK",
        exchange="SMART",
        primary_exchange="ARCA",
        currency="USD",
    )

    assert info["conId"] == 31662
    assert info["primaryExchange"] == "ARCA"


def test_tws_ib_async_client_lookup_security_raises_for_no_matches() -> None:
    fake_ib = FakeIbContractDetails(details=[])
    client = TwsIbAsyncClient(ib_factory=lambda: fake_ib)

    client.connect()

    with pytest.raises(TwsIbAsyncError, match="No IBKR contract details found"):
        client.lookup_security(
            symbol="XLK",
            sec_type="STK",
            exchange="SMART",
            primary_exchange="ARCA",
            currency="USD",
        )


def test_tws_ib_async_client_lookup_security_raises_for_ambiguous_matches() -> None:
    details = [
        FakeContractDetails(FakeContract(con_id=31662, local_symbol="XLK")),
        FakeContractDetails(FakeContract(con_id=12345, local_symbol="XLK A")),
    ]
    fake_ib = FakeIbContractDetails(details=details)
    client = TwsIbAsyncClient(ib_factory=lambda: fake_ib)

    client.connect()

    with pytest.raises(TwsIbAsyncError, match="Ambiguous IBKR contract lookup"):
        client.lookup_security(
            symbol="XLK",
            sec_type="STK",
            exchange="SMART",
            primary_exchange="ARCA",
            currency="USD",
        )
