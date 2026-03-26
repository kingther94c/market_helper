import pytest

from market_helper.providers.web_api import WebApiClient
from market_helper.safety import ReadOnlyViolationError


def test_web_api_client_blocks_non_read_only_mode() -> None:
    with pytest.raises(ReadOnlyViolationError):
        WebApiClient(base_url="https://localhost:5000/v1/api", mode="trading")


def test_web_api_client_exposes_only_read_methods() -> None:
    client = WebApiClient(base_url="https://localhost:5000/v1/api")

    assert client.session_status() == {}
    assert client.keepalive() == {}
    assert client.read_accounts() == []
    assert client.read_positions("U1") == []
    assert client.read_snapshot(["1", "2"]) == []
    assert client.stream_quotes() is None


def test_web_api_client_reads_session_and_portfolio_endpoints() -> None:
    calls: list[tuple[str, str, object, object]] = []

    def transport(method: str, url: str, params: object, body: object) -> object:
        calls.append((method, url, params, body))
        if url.endswith("/iserver/auth/status"):
            return {"authenticated": True, "connected": True}
        if url.endswith("/portfolio/accounts"):
            return [{"accountId": "U12345"}]
        if url.endswith("/portfolio/U12345/summary"):
            return {
                "netLiquidation": "125000.50",
                "availableFunds": "40000.25",
                "currency": "USD",
            }
        if url.endswith("/portfolio/U12345/positions/0"):
            return [
                {
                    "account": "U12345",
                    "conid": "756733",
                    "position": "20",
                    "avgCost": "210.5",
                    "marketValue": "4300",
                }
            ]
        if url.endswith("/iserver/marketdata/snapshot"):
            return [
                {
                    "conid": "756733",
                    "31": "214.8",
                    "84": "214.75",
                    "86": "214.85",
                }
            ]
        raise AssertionError(f"Unexpected request: {method} {url}")

    client = WebApiClient(
        base_url="https://localhost:5000/v1/api",
        transport=transport,
        retry_delay_seconds=0.0,
    )

    status = client.session_status()
    accounts = client.read_accounts()
    positions = client.read_positions("U12345")
    quotes = client.read_snapshot(["IBKR:756733"])

    assert status["authenticated"] is True
    assert accounts[0].account_id == "U12345"
    assert accounts[0].net_liquidation == 125000.50
    assert positions[0].contract_id == "IBKR:756733"
    assert positions[0].market_value == 4300.0
    assert quotes[0].last == 214.8
    assert calls[0][0] == "POST"
    assert calls[0][3] == {}
    assert calls[-1][2] == {"conids": "756733", "fields": "31,84,86"}


def test_web_api_client_retries_transient_account_summary_failure() -> None:
    attempts = 0

    def transport(method: str, url: str, params: object, body: object) -> object:
        nonlocal attempts
        _ = (method, params, body)
        if url.endswith("/portfolio/U12345/summary"):
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary gateway issue")
            return {
                "netLiquidation": "100000",
                "availableFunds": "25000",
                "currency": "USD",
            }
        raise AssertionError(f"Unexpected request: {url}")

    client = WebApiClient(
        base_url="https://localhost:5000/v1/api",
        transport=transport,
        retry_attempts=2,
        retry_delay_seconds=0.0,
    )

    account = client.read_account_summary("U12345")

    assert account.account_id == "U12345"
    assert account.net_liquidation == 100000.0
    assert attempts == 2
