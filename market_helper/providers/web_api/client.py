from __future__ import annotations

"""Read-only Client Portal Web API adapter.

The client keeps transport, retry, and payload coercion in one place so that
domain code can work with normalized snapshots instead of raw endpoint shapes.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from market_helper.domain import AccountSnapshot, PositionSnapshot, QuoteSnapshot
from market_helper.providers.web_api.mappers import (
    map_account_summary,
    map_position,
    map_quote_snapshot,
)
from market_helper.providers.web_api.retry import with_retry
from market_helper.safety import assert_operation_allowed, assert_read_only_mode

WebApiTransport = Callable[
    [str, str, Mapping[str, object] | None, Mapping[str, object] | None],
    object,
]


def _default_transport(
    method: str,
    url: str,
    params: Mapping[str, object] | None,
    body: Mapping[str, object] | None,
) -> object:
    _ = (method, url, params, body)
    return {}


@dataclass
class WebApiClient:
    base_url: str
    mode: str = "read_only"
    transport: WebApiTransport = _default_transport
    retry_attempts: int = 3
    retry_delay_seconds: float = 0.2

    def __post_init__(self) -> None:
        # Keep the guard close to object construction so invalid modes fail
        # before any HTTP call can be attempted.
        assert_read_only_mode(self.mode)

    def session_status(self) -> dict[str, object]:
        assert_operation_allowed("get_session_status")
        payload = self._request("POST", "iserver/auth/status", body={})
        return _coerce_mapping(payload)

    def keepalive(self) -> dict[str, object]:
        assert_operation_allowed("get_keepalive")
        payload = self._request("POST", "tickle", body={})
        return _coerce_mapping(payload)

    def read_accounts(self) -> list[AccountSnapshot]:
        assert_operation_allowed("read_accounts")
        payload = self._request("GET", "portfolio/accounts")
        accounts: list[AccountSnapshot] = []
        for row in _coerce_rows(payload):
            account_id = str(_first_value(row, "accountId", "id", default=""))
            if not account_id:
                continue
            # Reuse the account-summary endpoint as the canonical normalized
            # shape rather than returning the lighter `/portfolio/accounts` rows.
            accounts.append(self.read_account_summary(account_id))
        return accounts

    def read_account_summary(self, account_id: str) -> AccountSnapshot:
        assert_operation_allowed("read_account_summary")
        payload = self._request("GET", f"portfolio/{account_id}/summary")
        row = dict(_coerce_mapping(payload))
        row.setdefault("accountId", account_id)
        return map_account_summary(row)

    def read_positions(self, account_id: str) -> list[PositionSnapshot]:
        assert_operation_allowed("read_positions")
        payload = self._request("GET", f"portfolio/{account_id}/positions/0")
        return [map_position(row) for row in _coerce_rows(payload, key="positions")]

    def read_snapshot(self, conids: list[str]) -> list[QuoteSnapshot]:
        assert_operation_allowed("read_snapshot")
        normalized_conids = [conid.removeprefix("IBKR:") for conid in conids]
        if not normalized_conids:
            return []
        payload = self._request(
            "GET",
            "iserver/marketdata/snapshot",
            params={
                "conids": ",".join(normalized_conids),
                "fields": "31,84,86",
            },
        )
        return [map_quote_snapshot(row) for row in _coerce_rows(payload)]

    def stream_quotes(self) -> None:
        assert_operation_allowed("stream_quotes")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> object:
        url = self._build_url(path)
        # Retry is deliberately centralized here so each read_* method stays
        # focused on endpoint semantics instead of transport concerns.
        return with_retry(
            lambda: self.transport(method, url, params, body),
            attempts=self.retry_attempts,
            delay_seconds=self.retry_delay_seconds,
        )

    def _build_url(self, path: str) -> str:
        return "{base}/{path}".format(
            base=self.base_url.rstrip("/"),
            path=path.lstrip("/"),
        )


def _coerce_mapping(payload: object) -> dict[str, object]:
    if isinstance(payload, Mapping):
        return dict(payload)
    rows = _coerce_rows(payload)
    if rows:
        return dict(rows[0])
    return {}


def _coerce_rows(payload: object, *, key: str | None = None) -> list[Mapping[str, object]]:
    """Accept either a top-level JSON list or a list nested under ``key``."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        if key and isinstance(payload.get(key), list):
            rows = payload.get(key)
            assert isinstance(rows, list)
            return [row for row in rows if isinstance(row, Mapping)]
    return []


def _first_value(payload: Mapping[str, object], *keys: str, default: object) -> object:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return default
