from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from market_helper.download import (
    build_url,
    download_feed_collection,
    download_fred_series_csv,
    download_fred_series,
    download_json,
    download_news_feed,
)


class FakeResponse:
    def __init__(self, payload: str):
        self.payload = payload.encode("utf-8")

    def read(self) -> bytes:
        return self.payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class DownloadTests(unittest.TestCase):
    def test_build_url_skips_empty_params(self) -> None:
        built = build_url(
            "https://example.com/data",
            {"series_id": "INDPRO", "frequency": None, "units": ""},
        )
        self.assertEqual(built, "https://example.com/data?series_id=INDPRO")

    @patch("market_helper.data_library.loader.urlopen")
    def test_download_json_parses_payload(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse('{"ok": true, "count": 2}')

        payload = download_json("https://example.com/data", params={"a": "b"})

        self.assertEqual(payload, {"ok": True, "count": 2})
        request = mock_urlopen.call_args[0][0]
        self.assertIn("https://example.com/data?a=b", request.full_url)

    @patch("market_helper.data_library.loader.urlopen")
    def test_download_fred_series_filters_missing_values(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(
            """
            {
              "units": "lin",
              "frequency_short": "M",
              "observation_start": "2024-01-01",
              "observation_end": "2024-03-01",
              "realtime_start": "2026-03-24",
              "realtime_end": "2026-03-24",
              "observations": [
                {"date": "2024-01-01", "value": "100.0"},
                {"date": "2024-02-01", "value": "."},
                {"date": "2024-03-01", "value": "101.5"}
              ]
            }
            """
        )

        series = download_fred_series(
            series_id="INDPRO",
            api_key="demo",
            observation_start="2024-01-01",
        )

        self.assertEqual(series.series_id, "INDPRO")
        self.assertEqual(series.frequency, "M")
        self.assertEqual(len(series.observations), 2)
        self.assertEqual(series.observations[1].value, 101.5)
        request = mock_urlopen.call_args[0][0]
        self.assertIn("series_id=INDPRO", request.full_url)
        self.assertIn("file_type=json", request.full_url)

    @patch("market_helper.data_library.loader.subprocess.run")
    def test_download_fred_series_csv_parses_graph_csv(self, mock_run) -> None:
        mock_run.return_value = SimpleNamespace(
            stdout="observation_date,INDPRO\n2024-01-01,100.0\n2024-02-01,.\n2024-03-01,101.5\n"
        )

        series = download_fred_series_csv(
            series_id="INDPRO",
            observation_start="2024-02-01",
        )

        self.assertEqual(series.series_id, "INDPRO")
        self.assertEqual(len(series.observations), 1)
        self.assertEqual(series.observations[0].date, "2024-03-01")
        self.assertEqual(series.observations[0].value, 101.5)
        self.assertIn("fredgraph.csv?id=INDPRO", mock_run.call_args[0][0][-1])

    @patch("market_helper.data_library.loader.subprocess.run")
    def test_download_fred_series_csv_empty_window_respects_allow_empty(
        self, mock_run
    ) -> None:
        from market_helper.data_library.loader import SourceParseError

        # fredgraph returns the full history; an incremental filter past the
        # last observation leaves nothing in range.
        mock_run.return_value = SimpleNamespace(
            stdout="observation_date,UNRATE\n2024-01-01,4.0\n2024-02-01,4.1\n"
        )

        # Default: an empty filtered window is an error — one-shot/initial
        # callers genuinely expect data.
        with self.assertRaises(SourceParseError):
            download_fred_series_csv("UNRATE", observation_start="2024-02-02")

        # allow_empty=True: an empty incremental window is a valid no-op and
        # returns a series with no observations instead of raising.
        series = download_fred_series_csv(
            "UNRATE", observation_start="2024-02-02", allow_empty=True
        )
        self.assertEqual(series.series_id, "UNRATE")
        self.assertEqual(series.observations, [])

    @patch("market_helper.data_library.loader.urlopen")
    def test_download_news_feed_parses_rss_items(self, mock_urlopen) -> None:
        mock_urlopen.return_value = FakeResponse(
            """
            <rss version="2.0">
              <channel>
                <title>Macro Desk</title>
                <item>
                  <title>CPI cools again</title>
                  <link>https://example.com/cpi</link>
                  <pubDate>Tue, 24 Mar 2026 09:00:00 GMT</pubDate>
                  <description><![CDATA[<p>Inflation slows.</p>]]></description>
                </item>
              </channel>
            </rss>
            """
        )

        items = download_news_feed("https://example.com/rss.xml")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, "Macro Desk")
        self.assertEqual(items[0].title, "CPI cools again")
        self.assertEqual(items[0].summary, "Inflation slows.")
        self.assertTrue(items[0].published_at.startswith("2026-03-24T09:00:00"))

    @patch("market_helper.data_library.loader.urlopen")
    def test_download_feed_collection_keeps_feed_names(self, mock_urlopen) -> None:
        mock_urlopen.side_effect = [
            FakeResponse(
                """
                <rss version="2.0">
                  <channel>
                    <title>Ignored</title>
                    <item>
                      <title>Fed holds rates</title>
                      <link>https://example.com/fed</link>
                    </item>
                  </channel>
                </rss>
                """
            ),
            FakeResponse(
                """
                <feed xmlns="http://www.w3.org/2005/Atom">
                  <title>Ignored Atom</title>
                  <entry>
                    <title>Risk appetite improves</title>
                    <link href="https://example.com/risk" />
                    <updated>2026-03-24T12:30:00Z</updated>
                    <summary>Credit spreads tighten</summary>
                  </entry>
                </feed>
                """
            ),
        ]

        collection = download_feed_collection(
            {
                "Fed": "https://example.com/fed.xml",
                "Markets": "https://example.com/markets.xml",
            },
            limit=5,
        )

        self.assertEqual(collection["Fed"][0].source, "Fed")
        self.assertEqual(collection["Markets"][0].source, "Markets")
        self.assertEqual(collection["Markets"][0].summary, "Credit spreads tighten")
        self.assertEqual(
            collection["Markets"][0].published_at,
            "2026-03-24T12:30:00+00:00",
        )

    def test_redact_url_secrets_hides_flex_token(self) -> None:
        from market_helper.data_library.loader import _redact_url_secrets

        url = (
            "https://ndcdyn.interactivebrokers.com/AccountManagement/"
            "FlexWebService/SendRequest?t=SUPERSECRETTOKEN&q=1462703&v=3"
            "&fd=20260101&td=20260529"
        )
        redacted = _redact_url_secrets(url)
        self.assertNotIn("SUPERSECRETTOKEN", redacted)
        self.assertIn("t=<redacted>", redacted)
        # Non-credential params stay for debuggability.
        self.assertIn("q=1462703", redacted)
        self.assertIn("fd=20260101", redacted)
        self.assertIn("td=20260529", redacted)
        # FRED / Alpha Vantage keys and an explicit token param are masked too.
        self.assertEqual(
            _redact_url_secrets("https://x/d?api_key=ABC&z=1"),
            "https://x/d?api_key=<redacted>&z=1",
        )
        self.assertNotIn("XYZ", _redact_url_secrets("https://x/d?token=XYZ"))


if __name__ == "__main__":
    unittest.main()
