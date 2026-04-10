from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable
import xml.etree.ElementTree as ET

from market_helper.data_sources.base import DEFAULT_TIMEOUT, build_url, download_text

DEFAULT_IBKR_FLEX_BASE_URL = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
DEFAULT_IBKR_FLEX_API_VERSION = "3"
DEFAULT_IBKR_FLEX_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_IBKR_FLEX_MAX_ATTEMPTS = 10
SEND_REQUEST_PATH = "SendRequest"
GET_STATEMENT_PATH = "GetStatement"

RETRYABLE_FLEX_ERROR_CODES = frozenset(
    {
        "1001",
        "1004",
        "1005",
        "1006",
        "1007",
        "1008",
        "1009",
        "1018",
        "1019",
        "1021",
    }
)
RETRYABLE_FLEX_ERROR_MESSAGES = (
    "generation in progress",
    "try again shortly",
    "statement is not available",
)


class FlexWebServiceError(RuntimeError):
    """Base exception for Flex Web Service request failures."""


class FlexWebServicePendingError(FlexWebServiceError):
    """Raised when IBKR reports that the statement is not ready yet."""


@dataclass(frozen=True)
class FlexStatusResponse:
    status: str
    reference_code: str
    error_code: str
    error_message: str


@dataclass(frozen=True)
class FlexWebServiceClient:
    token: str
    downloader: Callable[[str], str] | None = None
    base_url: str = DEFAULT_IBKR_FLEX_BASE_URL
    timeout: int = DEFAULT_TIMEOUT
    api_version: str = DEFAULT_IBKR_FLEX_API_VERSION
    sleep: Callable[[float], None] = time.sleep

    def send_request(self, query_id: str) -> str:
        normalized_query_id = str(query_id).strip()
        normalized_token = str(self.token).strip()
        if not normalized_query_id:
            raise ValueError("query_id is required")
        if not normalized_token:
            raise ValueError("token is required")

        payload = self._download(
            SEND_REQUEST_PATH,
            {"t": normalized_token, "q": normalized_query_id, "v": self.api_version},
        )
        response = _parse_status_response(payload)
        if response is None:
            raise FlexWebServiceError("Flex SendRequest did not return a status response")
        if response.status.lower() != "success":
            raise _build_flex_error(response)
        if not response.reference_code:
            raise FlexWebServiceError("Flex SendRequest succeeded but did not include ReferenceCode")
        return response.reference_code

    def get_statement(self, reference_code: str) -> str:
        normalized_reference_code = str(reference_code).strip()
        normalized_token = str(self.token).strip()
        if not normalized_reference_code:
            raise ValueError("reference_code is required")
        if not normalized_token:
            raise ValueError("token is required")

        payload = self._download(
            GET_STATEMENT_PATH,
            {"t": normalized_token, "q": normalized_reference_code, "v": self.api_version},
        )
        response = _parse_status_response(payload)
        if response is None:
            return payload
        raise _build_flex_error(response)

    def fetch_statement(
        self,
        query_id: str,
        *,
        poll_interval_seconds: float = DEFAULT_IBKR_FLEX_POLL_INTERVAL_SECONDS,
        max_attempts: int = DEFAULT_IBKR_FLEX_MAX_ATTEMPTS,
    ) -> str:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must be >= 0")

        reference_code = self.send_request(query_id)
        last_error: FlexWebServicePendingError | None = None
        for attempt in range(max_attempts):
            try:
                return self.get_statement(reference_code)
            except FlexWebServicePendingError as error:
                last_error = error
                if attempt < max_attempts - 1:
                    self.sleep(poll_interval_seconds)

        if last_error is not None:
            raise last_error
        raise FlexWebServiceError("Flex statement polling exhausted without a terminal response")

    def _download(self, path: str, params: dict[str, object]) -> str:
        url = "{base}/{path}".format(
            base=self.base_url.rstrip("/"),
            path=path.lstrip("/"),
        )
        if self.downloader is not None:
            return str(self.downloader(build_url(url, params)))
        return download_text(url, params=params, timeout=self.timeout)


def _parse_status_response(payload: str) -> FlexStatusResponse | None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise FlexWebServiceError(f"Could not parse Flex XML response: {exc}") from exc

    if _local_name(root.tag) != "FlexStatementResponse":
        return None

    return FlexStatusResponse(
        status=_child_text(root, "Status"),
        reference_code=_child_text(root, "ReferenceCode"),
        error_code=_child_text(root, "ErrorCode"),
        error_message=_child_text(root, "ErrorMessage"),
    )


def _build_flex_error(response: FlexStatusResponse) -> FlexWebServiceError:
    status = response.status or "Unknown"
    details = []
    if response.error_code:
        details.append(f"code={response.error_code}")
    if response.error_message:
        details.append(response.error_message)
    message = "Flex Web Service response {status}".format(status=status)
    if details:
        message = "{message}: {details}".format(message=message, details="; ".join(details))

    if _is_retryable_flex_error(response):
        return FlexWebServicePendingError(message)
    return FlexWebServiceError(message)


def _is_retryable_flex_error(response: FlexStatusResponse) -> bool:
    if response.error_code in RETRYABLE_FLEX_ERROR_CODES:
        return True
    message = response.error_message.lower()
    return any(fragment in message for fragment in RETRYABLE_FLEX_ERROR_MESSAGES)


def _child_text(root: ET.Element, name: str) -> str:
    for child in root:
        if _local_name(child.tag) == name:
            return (child.text or "").strip()
    return ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
