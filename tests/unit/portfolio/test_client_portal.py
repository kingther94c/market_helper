import json
from urllib.request import Request

import pytest

from market_helper.portfolio.client_portal import (
    ClientPortalClient,
    ClientPortalError,
    choose_account,
    ensure_authenticated_session,
    position_rows_to_price_rows,
)


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        return None


def test_client_portal_client_requests_auth_and_positions() -> None:
    calls: list[tuple[str, str, str | None]] = []

    def fake_open(request: Request) -> FakeResponse:
        body = request.data.decode("utf-8") if request.data else None
        calls.append((request.get_method(), request.full_url, body))
        if request.full_url.endswith("/iserver/auth/status"):
            return FakeResponse({"authenticated": True, "connected": True})
        if request.full_url.endswith("/portfolio/accounts"):
            return FakeResponse([{"accountId": "U12345"}])
        if request.full_url.endswith("/portfolio2/U12345/positions"):
            return FakeResponse([{"conid": 756733, "position": 20, "mktPrice": 214.8}])
        if request.full_url.endswith("/tickle"):
            return FakeResponse({"session": "abc"})
        raise AssertionError(request.full_url)

    client = ClientPortalClient(opener=fake_open)

    assert client.auth_status()["authenticated"] is True
    assert client.list_accounts()[0]["accountId"] == "U12345"
    assert client.list_positions("U12345")[0]["conid"] == 756733
    assert client.tickle()["session"] == "abc"
    assert calls[0][0] == "GET"
    assert calls[-1][0] == "POST"
    assert calls[-1][2] == "{}"


def test_ensure_authenticated_session_raises_when_not_authenticated() -> None:
    client = ClientPortalClient(opener=lambda request: FakeResponse({"connected": True, "authenticated": False}))

    with pytest.raises(ClientPortalError):
        ensure_authenticated_session(client)


def test_choose_account_prefers_requested_id_and_falls_back_to_first() -> None:
    accounts = [{"accountId": "U12345"}, {"accountId": "U99999"}]

    assert choose_account(accounts, "U99999") == "U99999"
    assert choose_account(accounts, None) == "U12345"


def test_position_rows_to_price_rows_uses_market_price() -> None:
    rows = position_rows_to_price_rows(
        [
            {"conid": "756733", "mktPrice": "214.8"},
            {"conid": "265598", "marketPrice": "530.1"},
            {"conid": "123", "mktPrice": ""},
        ]
    )

    assert rows == [
        {"conid": "756733", "last": "214.8"},
        {"conid": "265598", "last": "530.1"},
    ]
