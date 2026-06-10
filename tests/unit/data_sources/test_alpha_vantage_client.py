"""Alpha Vantage client rate limiting — paced burst, not fixed 12s spacing.

AV's free tier rejects true back-to-back requests ("spread out your requests"
payload) and enforces a daily quota. The client paces consecutive requests at
a ~1s gap and keeps a conservative 5-per-minute sliding window; the request
that would exceed the window waits for the oldest one to age out. Small
batches therefore cost ~1s per request instead of the old 12s each.
"""

from __future__ import annotations

from market_helper.data_sources.alpha_vantage.client import AlphaVantageClient


class _FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _payload(_url: str) -> dict:
    return {"sectors": [{"sector": "Technology", "weight": "100%"}]}


def _client(fake: _FakeTime, **overrides) -> AlphaVantageClient:
    return AlphaVantageClient(
        api_key="k",
        downloader=_payload,
        clock=fake.clock,
        sleep=fake.sleep,
        **overrides,
    )


def test_consecutive_requests_pace_at_min_gap() -> None:
    fake = _FakeTime()
    client = _client(fake)
    for _ in range(3):
        client.fetch_etf_sector_weightings("SPY")
    # First request free; each subsequent one waits the 1.2s minimum gap.
    assert fake.sleeps == [1.2, 1.2]


def test_already_spaced_requests_never_sleep() -> None:
    fake = _FakeTime()
    client = _client(fake)
    for _ in range(5):
        client.fetch_etf_sector_weightings("SPY")
        fake.now += 2.0  # caller-side delay exceeds the min gap
    assert fake.sleeps == []


def test_request_beyond_window_limit_waits_for_oldest_to_age_out() -> None:
    fake = _FakeTime()
    client = _client(fake, min_request_interval_seconds=0.0)
    for _ in range(5):
        client.fetch_etf_sector_weightings("SPY")
        fake.now += 1.0
    # t=5 now; the oldest request was at t=0 and ages out at t=60.
    client.fetch_etf_sector_weightings("SPY")
    assert fake.sleeps == [55.0]


def test_window_frees_up_after_time_passes() -> None:
    fake = _FakeTime()
    client = _client(fake, min_request_interval_seconds=0.0)
    for _ in range(5):
        client.fetch_etf_sector_weightings("SPY")
        fake.now += 1.0
    fake.now = 120.0  # everything aged out
    client.fetch_etf_sector_weightings("SPY")
    assert fake.sleeps == []
