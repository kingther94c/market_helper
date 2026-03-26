import pytest

from market_helper.providers.tws_ib_async import TwsIbAsyncClient, TwsIbAsyncError, choose_tws_account


class FakeIb:
    def __init__(self, *, connected: bool = True) -> None:
        self.connected = connected
        self.connected_with: dict[str, object] | None = None
        self.disconnected = False

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

    def portfolio(self, account: str = "") -> list[object]:
        return [{"account": account or "ALL"}]


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

    client.disconnect()
    assert fake_ib.disconnected is True


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
