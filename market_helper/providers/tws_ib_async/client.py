from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


IBFactory = Callable[[], object]


class TwsIbAsyncError(RuntimeError):
    """Raised when the local TWS / IB Gateway session is unavailable or invalid."""


@dataclass
class TwsIbAsyncClient:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    timeout: float = 4.0
    readonly: bool = True
    account: str = ""
    ib_factory: IBFactory | None = None
    _ib: object | None = field(default=None, init=False, repr=False)

    def connect(self) -> None:
        if self._ib is not None and _is_connected(self._ib):
            return

        ib = self.ib_factory() if self.ib_factory is not None else _default_ib_factory()

        try:
            ib.connect(
                host=self.host,
                port=self.port,
                clientId=self.client_id,
                timeout=self.timeout,
                readonly=self.readonly,
                account=self.account,
            )
        except Exception as error:
            raise TwsIbAsyncError(
                "TWS / IB Gateway connection failed for {host}:{port} client_id={client_id}: {reason}".format(
                    host=self.host,
                    port=self.port,
                    client_id=self.client_id,
                    reason=error,
                )
            ) from error

        if not _is_connected(ib):
            raise TwsIbAsyncError(
                "TWS / IB Gateway connection did not become ready for {host}:{port} client_id={client_id}.".format(
                    host=self.host,
                    port=self.port,
                    client_id=self.client_id,
                )
            )

        self._ib = ib

    def disconnect(self) -> None:
        if self._ib is None:
            return

        disconnect = getattr(self._ib, "disconnect", None)
        if callable(disconnect):
            disconnect()
        self._ib = None

    def list_accounts(self) -> list[str]:
        ib = self._require_connected()
        managed_accounts = getattr(ib, "managedAccounts", None)
        if not callable(managed_accounts):
            raise TwsIbAsyncError("Connected ib_async client does not expose managedAccounts().")

        return _unique_non_empty_strings(managed_accounts())

    def list_portfolio(self, account_id: str | None = None) -> list[object]:
        ib = self._require_connected()
        portfolio = getattr(ib, "portfolio", None)
        if not callable(portfolio):
            raise TwsIbAsyncError("Connected ib_async client does not expose portfolio().")

        try:
            rows = portfolio(account_id or "")
        except Exception as error:
            raise TwsIbAsyncError(
                "Failed to fetch TWS / IB Gateway portfolio for account={account_id}: {reason}".format(
                    account_id=account_id or "",
                    reason=error,
                )
            ) from error

        return list(rows)

    def _require_connected(self) -> object:
        if self._ib is None or not _is_connected(self._ib):
            raise TwsIbAsyncError("TWS / IB Gateway client is not connected.")
        return self._ib


def choose_tws_account(accounts: list[str], requested_account_id: str | None) -> str:
    if requested_account_id:
        if accounts and requested_account_id not in accounts:
            raise TwsIbAsyncError(
                "Requested account_id {account_id} was not returned by managedAccounts().".format(
                    account_id=requested_account_id
                )
            )
        return requested_account_id

    if not accounts:
        raise TwsIbAsyncError("No accounts returned by TWS / IB Gateway.")

    return accounts[0]


def _default_ib_factory() -> object:
    try:
        from ib_async import IB
    except ModuleNotFoundError as error:
        raise TwsIbAsyncError(
            "ib_async is required for the TWS live report path. Install dependencies in the py313 environment first."
        ) from error

    return IB()


def _is_connected(ib: object) -> bool:
    is_connected = getattr(ib, "isConnected", None)
    if callable(is_connected):
        return bool(is_connected())
    return True


def _unique_non_empty_strings(values: object) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()

    if not isinstance(values, list):
        values = list(values)

    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        unique.append(item)

    return unique
