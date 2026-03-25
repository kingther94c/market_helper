from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Dict, Iterable, List, Mapping, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import EconomicSeries, NewsItem, Observation

DEFAULT_TIMEOUT = 20
DEFAULT_HEADERS = {
    "Accept": "application/json, application/xml, text/xml, text/plain, */*",
    "User-Agent": "market-helper/0.1",
}
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


class DownloadError(RuntimeError):
    pass


class SourceParseError(DownloadError):
    pass


def build_url(base_url: str, params: Optional[Mapping[str, object]] = None) -> str:
    if not params:
        return base_url

    filtered_params = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }
    if not filtered_params:
        return base_url

    return "{base}?{query}".format(base=base_url, query=urlencode(filtered_params))


def _request_bytes(
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> bytes:
    request_url = build_url(url, params)
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    request = Request(request_url, headers=merged_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        raise DownloadError(
            "HTTP error while requesting {url}: {status} {reason}. {message}".format(
                url=request_url,
                status=exc.code,
                reason=exc.reason,
                message=message.strip(),
            )
        ) from exc
    except URLError as exc:
        raise DownloadError(
            "Network error while requesting {url}: {reason}".format(
                url=request_url,
                reason=exc.reason,
            )
        ) from exc


def download_text(
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    payload = _request_bytes(url, params=params, headers=headers, timeout=timeout)
    return payload.decode("utf-8", errors="replace")


def download_json(
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> object:
    try:
        return json.loads(
            download_text(url, params=params, headers=headers, timeout=timeout)
        )
    except json.JSONDecodeError as exc:
        raise SourceParseError(
            "Could not parse JSON from {url}: {error}".format(url=url, error=exc)
        ) from exc


def download_csv(
    url: str,
    *,
    params: Optional[Mapping[str, object]] = None,
    headers: Optional[Mapping[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[Dict[str, str]]:
    csv_text = download_text(url, params=params, headers=headers, timeout=timeout)
    reader = csv.DictReader(io.StringIO(csv_text))
    return [dict(row) for row in reader]


def download_fred_series(
    series_id: str,
    api_key: str,
    *,
    title: Optional[str] = None,
    units: str = "lin",
    frequency: Optional[str] = None,
    aggregation_method: Optional[str] = None,
    observation_start: Optional[str] = None,
    observation_end: Optional[str] = None,
    limit: int = 100000,
    timeout: int = DEFAULT_TIMEOUT,
) -> EconomicSeries:
    if not api_key:
        raise ValueError("api_key is required for FRED downloads")

    payload = download_json(
        FRED_OBSERVATIONS_URL,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "sort_order": "asc",
            "units": units,
            "frequency": frequency,
            "aggregation_method": aggregation_method,
            "observation_start": observation_start,
            "observation_end": observation_end,
            "limit": limit,
        },
        timeout=timeout,
    )

    if not isinstance(payload, dict):
        raise SourceParseError(
            "Unexpected FRED response type for series {series_id}".format(
                series_id=series_id
            )
        )

    raw_observations = payload.get("observations")
    if not isinstance(raw_observations, list):
        raise SourceParseError(
            "FRED response for {series_id} did not include observations".format(
                series_id=series_id
            )
        )

    observations: List[Observation] = []
    for item in raw_observations:
        if not isinstance(item, dict):
            continue

        raw_value = item.get("value")
        raw_date = item.get("date")
        if raw_value in (None, ".") or not raw_date:
            continue

        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            continue

        observations.append(Observation(date=str(raw_date), value=numeric_value))

    return EconomicSeries(
        series_id=series_id,
        title=title or series_id,
        units=str(payload.get("units", units)),
        frequency=str(payload.get("frequency_short", frequency or "")),
        observations=observations,
        metadata={
            "observation_start": str(payload.get("observation_start", "")),
            "observation_end": str(payload.get("observation_end", "")),
            "realtime_start": str(payload.get("realtime_start", "")),
            "realtime_end": str(payload.get("realtime_end", "")),
        },
    )


def download_fred_series_batch(
    requests: Iterable[Mapping[str, object]],
    api_key: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, EconomicSeries]:
    series_map: Dict[str, EconomicSeries] = {}
    for item in requests:
        series_id = str(item["series_id"])
        series_map[series_id] = download_fred_series(
            series_id=series_id,
            api_key=api_key,
            title=item.get("title"),
            units=str(item.get("units", "lin")),
            frequency=item.get("frequency"),
            aggregation_method=item.get("aggregation_method"),
            observation_start=item.get("observation_start"),
            observation_end=item.get("observation_end"),
            limit=int(item.get("limit", 100000)),
            timeout=timeout,
        )
    return series_map


def download_news_feed(
    url: str,
    *,
    source_name: Optional[str] = None,
    limit: Optional[int] = 10,
    timeout: int = DEFAULT_TIMEOUT,
) -> List[NewsItem]:
    raw_xml = download_text(
        url,
        headers={"Accept": "application/rss+xml, application/atom+xml, application/xml"},
        timeout=timeout,
    )
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        raise SourceParseError(
            "Could not parse XML feed from {url}: {error}".format(url=url, error=exc)
        ) from exc

    if _is_atom_feed(root):
        items = _parse_atom_feed(root, url, source_name)
    else:
        items = _parse_rss_feed(root, url, source_name)

    if limit is None:
        return items
    return items[:limit]


def download_feed_collection(
    feeds: Mapping[str, str],
    *,
    limit: Optional[int] = 10,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, List[NewsItem]]:
    return {
        name: download_news_feed(
            feed_url,
            source_name=name,
            limit=limit,
            timeout=timeout,
        )
        for name, feed_url in feeds.items()
    }


def _is_atom_feed(root: ET.Element) -> bool:
    return root.tag.endswith("feed")


def _parse_rss_feed(
    root: ET.Element,
    feed_url: str,
    source_name: Optional[str],
) -> List[NewsItem]:
    channel = root.find("channel")
    if channel is None:
        raise SourceParseError(
            "RSS feed from {url} did not include a channel element".format(url=feed_url)
        )

    resolved_source = source_name or _child_text(channel, "title") or feed_url
    items: List[NewsItem] = []
    for item in channel.findall("item"):
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if not title or not link:
            continue

        items.append(
            NewsItem(
                source=resolved_source,
                title=title,
                url=link,
                published_at=_normalize_datetime(_child_text(item, "pubDate")),
                summary=_clean_html_text(_child_text(item, "description") or ""),
            )
        )
    return items


def _parse_atom_feed(
    root: ET.Element,
    feed_url: str,
    source_name: Optional[str],
) -> List[NewsItem]:
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    resolved_source = source_name or _xml_text(root.find("atom:title", namespace)) or feed_url
    items: List[NewsItem] = []
    for entry in root.findall("atom:entry", namespace):
        title = _xml_text(entry.find("atom:title", namespace))
        link_element = entry.find("atom:link[@rel='alternate']", namespace) or entry.find(
            "atom:link",
            namespace,
        )
        link = ""
        if link_element is not None:
            link = link_element.attrib.get("href", "")

        if not title or not link:
            continue

        summary = _xml_text(entry.find("atom:summary", namespace)) or _xml_text(
            entry.find("atom:content", namespace)
        )
        published = _xml_text(entry.find("atom:published", namespace)) or _xml_text(
            entry.find("atom:updated", namespace)
        )

        items.append(
            NewsItem(
                source=resolved_source,
                title=title,
                url=link,
                published_at=_normalize_datetime(published),
                summary=_clean_html_text(summary or ""),
            )
        )
    return items


def _child_text(element: ET.Element, tag: str) -> Optional[str]:
    child = element.find(tag)
    return _xml_text(child)


def _xml_text(element: Optional[ET.Element]) -> Optional[str]:
    if element is None or element.text is None:
        return None
    text = element.text.strip()
    return text or None


def _clean_html_text(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    normalized = re.sub(r"\s+", " ", unescape(without_tags))
    return normalized.strip()


def _normalize_datetime(raw_value: Optional[str]) -> Optional[str]:
    if not raw_value:
        return None

    try:
        return parsedate_to_datetime(raw_value).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        try:
            return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return raw_value.strip() or None
