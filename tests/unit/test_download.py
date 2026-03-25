from __future__ import annotations

import unittest
from unittest.mock import patch

from market_helper.download import (
    build_url,
    download_feed_collection,
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


if __name__ == "__main__":
    unittest.main()
