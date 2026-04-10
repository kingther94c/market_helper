import pytest

from market_helper.providers.flex import FlexWebServiceClient, FlexWebServiceError, FlexWebServicePendingError


def test_flex_web_service_client_send_request_returns_reference_code() -> None:
    seen_urls: list[str] = []

    def downloader(url: str) -> str:
        seen_urls.append(url)
        return """
<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>ABC123</ReferenceCode>
</FlexStatementResponse>
""".strip()

    client = FlexWebServiceClient(token="secret-token", downloader=downloader)

    reference_code = client.send_request("1462703")

    assert reference_code == "ABC123"
    assert "/SendRequest" in seen_urls[0]
    assert "q=1462703" in seen_urls[0]


def test_flex_web_service_client_send_request_supports_date_range_override() -> None:
    seen_urls: list[str] = []

    def downloader(url: str) -> str:
        seen_urls.append(url)
        return """
<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>ABC123</ReferenceCode>
</FlexStatementResponse>
""".strip()

    client = FlexWebServiceClient(token="secret-token", downloader=downloader)

    reference_code = client.send_request("1462703", from_date="2025-01-01", to_date="2025-12-31")

    assert reference_code == "ABC123"
    assert "fd=20250101" in seen_urls[0]
    assert "td=20251231" in seen_urls[0]


def test_flex_web_service_client_send_request_supports_period_override() -> None:
    seen_urls: list[str] = []

    def downloader(url: str) -> str:
        seen_urls.append(url)
        return """
<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>ABC123</ReferenceCode>
</FlexStatementResponse>
""".strip()

    client = FlexWebServiceClient(token="secret-token", downloader=downloader)

    reference_code = client.send_request("1462703", period="LAST365")

    assert reference_code == "ABC123"
    assert "p=LAST365" in seen_urls[0]


def test_flex_web_service_client_send_request_rejects_partial_date_range() -> None:
    client = FlexWebServiceClient(token="secret-token", downloader=lambda _url: "")

    with pytest.raises(ValueError, match="from_date and to_date must be provided together"):
        client.send_request("1462703", from_date="2025-01-01")


def test_flex_web_service_client_send_request_rejects_period_plus_date_range() -> None:
    client = FlexWebServiceClient(token="secret-token", downloader=lambda _url: "")

    with pytest.raises(ValueError, match="period cannot be combined"):
        client.send_request(
            "1462703",
            from_date="2025-01-01",
            to_date="2025-12-31",
            period="LAST365",
        )


def test_flex_web_service_client_get_statement_returns_statement_xml() -> None:
    statement_xml = """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement />
  </FlexStatements>
</FlexQueryResponse>
""".strip()
    client = FlexWebServiceClient(token="secret-token", downloader=lambda _url: statement_xml)

    payload = client.get_statement("ABC123")

    assert payload == statement_xml


def test_flex_web_service_client_get_statement_raises_pending_error_for_retryable_status() -> None:
    client = FlexWebServiceClient(
        token="secret-token",
        downloader=lambda _url: """
<FlexStatementResponse>
  <Status>Fail</Status>
  <ErrorCode>1019</ErrorCode>
  <ErrorMessage>Statement generation in progress</ErrorMessage>
</FlexStatementResponse>
""".strip(),
    )

    with pytest.raises(FlexWebServicePendingError):
        client.get_statement("ABC123")


def test_flex_web_service_client_get_statement_treats_error_1003_as_pending() -> None:
    client = FlexWebServiceClient(
        token="secret-token",
        downloader=lambda _url: """
<FlexStatementResponse>
  <Status>Fail</Status>
  <ErrorCode>1003</ErrorCode>
  <ErrorMessage>Statement is not available.</ErrorMessage>
</FlexStatementResponse>
""".strip(),
    )

    with pytest.raises(FlexWebServicePendingError):
        client.get_statement("ABC123")


def test_flex_web_service_client_fetch_statement_polls_until_ready() -> None:
    responses = iter(
        [
            """
<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>ABC123</ReferenceCode>
</FlexStatementResponse>
""".strip(),
            """
<FlexStatementResponse>
  <Status>Fail</Status>
  <ErrorCode>1019</ErrorCode>
  <ErrorMessage>Statement generation in progress</ErrorMessage>
</FlexStatementResponse>
""".strip(),
            """
<FlexQueryResponse>
  <FlexStatements>
    <FlexStatement />
  </FlexStatements>
</FlexQueryResponse>
""".strip(),
        ]
    )
    sleeps: list[float] = []
    client = FlexWebServiceClient(
        token="secret-token",
        downloader=lambda _url: next(responses),
        sleep=sleeps.append,
    )

    payload = client.fetch_statement("1462703", poll_interval_seconds=2.5, max_attempts=3)

    assert "<FlexQueryResponse>" in payload
    assert sleeps == [2.5]


def test_flex_web_service_client_fetch_statement_surfaces_polling_guidance_on_timeout() -> None:
    responses = iter(
        [
            """
<FlexStatementResponse>
  <Status>Success</Status>
  <ReferenceCode>ABC123</ReferenceCode>
</FlexStatementResponse>
""".strip(),
            """
<FlexStatementResponse>
  <Status>Fail</Status>
  <ErrorCode>1003</ErrorCode>
  <ErrorMessage>Statement is not available.</ErrorMessage>
</FlexStatementResponse>
""".strip(),
            """
<FlexStatementResponse>
  <Status>Fail</Status>
  <ErrorCode>1003</ErrorCode>
  <ErrorMessage>Statement is not available.</ErrorMessage>
</FlexStatementResponse>
""".strip(),
        ]
    )
    sleeps: list[float] = []
    client = FlexWebServiceClient(
        token="secret-token",
        downloader=lambda _url: next(responses),
        sleep=sleeps.append,
    )

    with pytest.raises(FlexWebServicePendingError, match="Polling exhausted after 2 attempts"):
        client.fetch_statement("1462703", poll_interval_seconds=7.5, max_attempts=2)

    assert sleeps == [7.5]


def test_flex_web_service_client_send_request_raises_non_retryable_error() -> None:
    client = FlexWebServiceClient(
        token="secret-token",
        downloader=lambda _url: """
<FlexStatementResponse>
  <Status>Fail</Status>
  <ErrorCode>2000</ErrorCode>
  <ErrorMessage>Token is invalid</ErrorMessage>
</FlexStatementResponse>
""".strip(),
    )

    with pytest.raises(FlexWebServiceError, match="Token is invalid"):
        client.send_request("1462703")
