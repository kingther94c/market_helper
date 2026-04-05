from __future__ import annotations

"""Thin ib_async-based client for read-only TWS / IB Gateway access."""

import asyncio
from dataclasses import dataclass, field
from typing import Callable


IBFactory = Callable[[], object]


class TwsIbAsyncError(RuntimeError):
    """Raised when the local TWS / IB Gateway session is unavailable or invalid."""


class _FallbackContract:
    """Tiny contract shim for tests when ib_async is not installed.

    The real live connection path still requires ib_async in _default_ib_factory,
    but fake/test clients can work with any object exposing these attributes.
    """

    pass


def choose_tws_account(accounts: list[str], requested_account_id: str | None) -> str:
    """Resolve the account id to use for live portfolio/report workflows."""
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


def _patch_nested_asyncio() -> None:
    from ib_async import util as ib_util

    ib_util.patchAsyncio()


def _ensure_ib_async_notebook_compat() -> None:
    # ``ib_async`` may need the nested event-loop patch when called from a
    # notebook kernel that already owns the running asyncio loop.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    if not loop.is_running():
        return

    try:
        _patch_nested_asyncio()
    except ModuleNotFoundError:
        return


def _build_ib_contract(
    symbol: str = "",
    sec_type: str = "STK",
    exchange: str = "",
    primary_exchange: str = "",
    currency: str = "",
    conid: int | None = None,
    local_symbol: str | None = None,
) -> object:
    """Create the lightest contract object needed for contract-detail lookup."""
    try:
        from ib_async import Contract
    except ModuleNotFoundError:
        Contract = _FallbackContract

    contract = Contract()
    if conid is not None:
        contract.conId = int(conid)
    if symbol:
        contract.symbol = str(symbol).upper()
    if sec_type:
        contract.secType = str(sec_type).upper()
    if exchange:
        contract.exchange = str(exchange)
    if primary_exchange:
        contract.primaryExchange = str(primary_exchange).upper()
    if currency:
        contract.currency = str(currency).upper()
    if local_symbol is not None:
        contract.localSymbol = str(local_symbol)
    return contract


def _contract_details_to_dict(contract_details: object) -> dict[str, object]:
    contract = getattr(contract_details, "contract", None)
    return {
        "conId": getattr(contract, "conId", "") or getattr(contract, "conid", ""),
        "symbol": getattr(contract, "symbol", ""),
        "secType": getattr(contract, "secType", ""),
        "currency": getattr(contract, "currency", ""),
        "exchange": getattr(contract, "exchange", ""),
        "primaryExchange": getattr(contract, "primaryExchange", ""),
        "localSymbol": getattr(contract, "localSymbol", ""),
        "marketName": getattr(contract_details, "marketName", ""),
        "minTick": getattr(contract_details, "minTick", ""),
        "priceMagnifier": getattr(contract_details, "priceMagnifier", ""),
        "orderTypes": getattr(contract_details, "orderTypes", ""),
        "validExchanges": getattr(contract_details, "validExchanges", ""),
        "tradingHours": getattr(contract_details, "tradingHours", ""),
        "liquidHours": getattr(contract_details, "liquidHours", ""),
        "longName": getattr(contract_details, "longName", ""),
        "industry": getattr(contract_details, "industry", ""),
        "category": getattr(contract_details, "category", ""),
        "subcategory": getattr(contract_details, "subcategory", ""),
    }


def _lookup_description(
    *,
    symbol: str | None = None,
    sec_type: str = "",
    exchange: str = "",
    primary_exchange: str = "",
    currency: str = "",
    conid: int | None = None,
    local_symbol: str | None = None,
    contract: object | None = None,
) -> str:
    values = {
        "symbol": symbol or getattr(contract, "symbol", ""),
        "secType": sec_type or getattr(contract, "secType", ""),
        "exchange": exchange or getattr(contract, "exchange", ""),
        "primaryExchange": primary_exchange or getattr(contract, "primaryExchange", ""),
        "currency": currency or getattr(contract, "currency", ""),
        "conId": conid if conid is not None else getattr(contract, "conId", None),
        "localSymbol": local_symbol if local_symbol is not None else getattr(contract, "localSymbol", ""),
    }
    parts = [f"{key}={value}" for key, value in values.items() if value not in (None, "")]
    return ", ".join(parts) if parts else "contract lookup"


def _summarize_contract_match(detail: dict[str, object]) -> str:
    fields = (
        ("conId", detail.get("conId")),
        ("symbol", detail.get("symbol")),
        ("secType", detail.get("secType")),
        ("exchange", detail.get("exchange")),
        ("primaryExchange", detail.get("primaryExchange")),
        ("currency", detail.get("currency")),
        ("localSymbol", detail.get("localSymbol")),
    )
    parts = [f"{key}={value}" for key, value in fields if value not in (None, "")]
    return ", ".join(parts) if parts else "<empty contract match>"


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

        # Keep notebook compatibility here so all higher-level workflows can
        # reuse the same client without caring where they are executed from.
        _ensure_ib_async_notebook_compat()
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

    def list_account_values(self, account_id: str | None = None) -> list[object]:
        ib = self._require_connected()
        account_values = getattr(ib, "accountValues", None)
        account_summary = getattr(ib, "accountSummary", None)
        selected_account = account_id or ""

        if callable(account_values):
            try:
                rows = list(account_values(selected_account))
            except Exception as error:
                raise TwsIbAsyncError(
                    "Failed to fetch TWS / IB Gateway account values for account={account_id}: {reason}".format(
                        account_id=selected_account,
                        reason=error,
                    )
                ) from error
            if rows:
                return rows

        if callable(account_summary):
            try:
                return list(account_summary(selected_account))
            except Exception as error:
                raise TwsIbAsyncError(
                    "Failed to fetch TWS / IB Gateway account summary for account={account_id}: {reason}".format(
                        account_id=selected_account,
                        reason=error,
                    )
                ) from error

        if callable(account_values):
            return []

        raise TwsIbAsyncError(
            "Connected ib_async client does not expose accountValues() or accountSummary()."
        )

    def search_securities(
        self,
        symbol: str | None = None,
        sec_type: str = "STK",
        exchange: str = "",
        primary_exchange: str = "",
        currency: str = "",
        conid: int | None = None,
        local_symbol: str | None = None,
        contract: object | None = None,
    ) -> list[dict[str, object]]:
        """Fetch contract details from IBKR using ib_async style API.

        Example: search_securities(
            symbol="XLK",
            sec_type="STK",
            exchange="SMART",
            primary_exchange="ARCA",
            currency="USD",
        )
        """
        ib = self._require_connected()
        _ensure_ib_async_notebook_compat()

        if contract is None:
            contract = _build_ib_contract(
                symbol=symbol or "",
                sec_type=sec_type,
                exchange=exchange,
                primary_exchange=primary_exchange,
                currency=currency,
                conid=conid,
                local_symbol=local_symbol,
            )

        req_contract_details = getattr(ib, "reqContractDetails", None)
        if not callable(req_contract_details):
            raise TwsIbAsyncError(
                "Connected ib_async client does not expose reqContractDetails()."
            )

        try:
            details = req_contract_details(contract)
            # Support both synchronous and coroutine-returning ib_async shims so
            # tests can fake the method without perfectly matching the runtime.
            if hasattr(details, "__await__"):
                import asyncio

                details = asyncio.get_event_loop().run_until_complete(details)

            if details is None:
                return []

            return [_contract_details_to_dict(item) for item in details]
        except Exception as error:
            raise TwsIbAsyncError(
                "Failed to fetch contract details for {lookup}: {reason}".format(
                    lookup=_lookup_description(
                        symbol=symbol,
                        sec_type=sec_type,
                        exchange=exchange,
                        primary_exchange=primary_exchange,
                        currency=currency,
                        conid=conid,
                        local_symbol=local_symbol,
                        contract=contract,
                    ),
                    reason=error,
                )
            ) from error

    def fetch_security_info(
        self,
        symbol: str | None = None,
        sec_type: str = "STK",
        exchange: str = "",
        primary_exchange: str = "",
        currency: str = "",
        conid: int | None = None,
        local_symbol: str | None = None,
        contract: object | None = None,
    ) -> list[dict[str, object]]:
        """Backward-compatible alias for search_securities()."""
        return self.search_securities(
            symbol=symbol,
            sec_type=sec_type,
            exchange=exchange,
            primary_exchange=primary_exchange,
            currency=currency,
            conid=conid,
            local_symbol=local_symbol,
            contract=contract,
        )

    def lookup_security(
        self,
        symbol: str | None = None,
        sec_type: str = "STK",
        exchange: str = "",
        primary_exchange: str = "",
        currency: str = "",
        conid: int | None = None,
        local_symbol: str | None = None,
        contract: object | None = None,
    ) -> dict[str, object]:
        """Return exactly one contract match or fail with a diagnostic error."""
        details = self.search_securities(
            symbol=symbol,
            sec_type=sec_type,
            exchange=exchange,
            primary_exchange=primary_exchange,
            currency=currency,
            conid=conid,
            local_symbol=local_symbol,
            contract=contract,
        )
        lookup = _lookup_description(
            symbol=symbol,
            sec_type=sec_type,
            exchange=exchange,
            primary_exchange=primary_exchange,
            currency=currency,
            conid=conid,
            local_symbol=local_symbol,
            contract=contract,
        )
        if not details:
            raise TwsIbAsyncError(
                "No IBKR contract details found for {lookup}. Tighten symbol/sec_type/exchange/primary_exchange/currency or use conid.".format(
                    lookup=lookup
                )
            )
        if len(details) > 1:
            candidates = "; ".join(_summarize_contract_match(item) for item in details[:5])
            if len(details) > 5:
                candidates = "{candidates}; ... ({remaining} more)".format(
                    candidates=candidates,
                    remaining=len(details) - 5,
                )
            raise TwsIbAsyncError(
                "Ambiguous IBKR contract lookup for {lookup}. Returned {count} matches: {candidates}".format(
                    lookup=lookup,
                    count=len(details),
                    candidates=candidates,
                )
            )
        return details[0]

    def require_security_info(
        self,
        symbol: str | None = None,
        sec_type: str = "STK",
        exchange: str = "",
        primary_exchange: str = "",
        currency: str = "",
        conid: int | None = None,
        local_symbol: str | None = None,
        contract: object | None = None,
    ) -> dict[str, object]:
        """Backward-compatible alias for lookup_security()."""
        return self.lookup_security(
            symbol=symbol,
            sec_type=sec_type,
            exchange=exchange,
            primary_exchange=primary_exchange,
            currency=currency,
            conid=conid,
            local_symbol=local_symbol,
            contract=contract,
        )

    def _require_connected(self) -> object:
        if self._ib is None or not _is_connected(self._ib):
            raise TwsIbAsyncError("TWS / IB Gateway client is not connected.")
        return self._ib
