from __future__ import annotations

import json
import ssl
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, HTTPSHandler, OpenerDirector, Request, build_opener


JsonObject = dict[str, object]
OpenUrl = Callable[[Request], object]


class ClientPortalError(RuntimeError):
    """Raised when the local Client Portal Gateway session is unavailable or invalid."""


@dataclass
class ClientPortalClient:
    base_url: str = "https://localhost:5000/v1/api"
    verify_ssl: bool = False
    opener: OpenUrl | None = None
    _cookie_jar: CookieJar = field(default_factory=CookieJar, init=False, repr=False)

    def auth_status(self) -> JsonObject:
        payload = self.get_json("/iserver/auth/status")
        if not isinstance(payload, dict):
            raise ClientPortalError("Unexpected auth/status response payload.")
        return dict(payload)

    def tickle(self) -> JsonObject:
        payload = self.post_json("/tickle", {})
        if not isinstance(payload, dict):
            raise ClientPortalError("Unexpected /tickle response payload.")
        return dict(payload)

    def list_accounts(self) -> list[JsonObject]:
        payload = self.get_json("/portfolio/accounts")
        return _coerce_rows(payload, endpoint="/portfolio/accounts")

    def list_positions(self, account_id: str) -> list[JsonObject]:
        payload = self.get_json(f"/portfolio2/{account_id}/positions")
        return _coerce_rows(payload, endpoint=f"/portfolio2/{account_id}/positions")

    def get_json(self, path: str) -> object:
        return self._request_json("GET", path)

    def post_json(self, path: str, body: JsonObject) -> object:
        return self._request_json("POST", path, body=body)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        body: JsonObject | None = None,
    ) -> object:
        request = Request(
            self._build_url(path),
            method=method,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        open_url = self.opener or self._build_default_opener().open
        try:
            response = open_url(request)
            try:
                payload = response.read().decode("utf-8")
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise ClientPortalError(
                "Client Portal request failed for {path}: HTTP {code} {detail}".format(
                    path=path,
                    code=error.code,
                    detail=detail,
                )
            ) from error
        except URLError as error:
            raise ClientPortalError(
                "Client Portal request failed for {path}: {reason}".format(
                    path=path,
                    reason=error.reason,
                )
            ) from error

        if not payload.strip():
            return {}
        return json.loads(payload)

    def _build_default_opener(self) -> OpenerDirector:
        context = ssl.create_default_context()
        if not self.verify_ssl:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        return build_opener(
            HTTPCookieProcessor(self._cookie_jar),
            HTTPSHandler(context=context),
        )

    def _build_url(self, path: str) -> str:
        return "{base}/{path}".format(
            base=self.base_url.rstrip("/"),
            path=path.lstrip("/"),
        )


def ensure_authenticated_session(client: ClientPortalClient) -> JsonObject:
    status = client.auth_status()
    if not status.get("connected"):
        raise ClientPortalError(
            "Client Portal Gateway is not connected. Launch the local gateway and sign in at https://localhost:5000."
        )
    if not status.get("authenticated"):
        raise ClientPortalError(
            "Client Portal brokerage session is not authenticated. Sign in at https://localhost:5000 and complete 2FA first."
        )
    return status


def choose_account(accounts: list[JsonObject], requested_account_id: Optional[str]) -> str:
    if requested_account_id:
        for row in accounts:
            if str(row.get("accountId", row.get("id", ""))) == requested_account_id:
                return requested_account_id
        raise ClientPortalError(
            "Requested account_id {account_id} was not returned by /portfolio/accounts.".format(
                account_id=requested_account_id
            )
        )

    if not accounts:
        raise ClientPortalError("No accounts returned by /portfolio/accounts.")

    return str(accounts[0].get("accountId", accounts[0].get("id", "")))


def position_rows_to_price_rows(position_rows: list[JsonObject]) -> list[JsonObject]:
    prices: list[JsonObject] = []
    for row in position_rows:
        conid = row.get("conid", row.get("conId", row.get("con_id")))
        if conid in (None, ""):
            continue
        last_price = row.get("mktPrice", row.get("marketPrice", row.get("last")))
        if last_price in (None, ""):
            continue
        prices.append({"conid": conid, "last": last_price})
    return prices


def _coerce_rows(payload: object, *, endpoint: str) -> list[JsonObject]:
    if not isinstance(payload, list):
        raise ClientPortalError(
            "Unexpected response payload for {endpoint}; expected a JSON array.".format(
                endpoint=endpoint
            )
        )
    return [dict(row) for row in payload if isinstance(row, dict)]
