"""CBOE response cache: a second fetch within TTL is served without re-hitting the CDN."""

from __future__ import annotations

import json

from market_helper.domain.option_advisor import providers


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self, *args):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_cboe_response_is_cached(monkeypatch):
    providers.clear_cboe_cache()
    payload = {
        "timestamp": "2026-06-03T10:00:00",
        "data": {
            "current_price": 100.0,
            "options": [{
                "option": "ABC260619C00100000", "bid": 1.0, "ask": 1.2, "last_trade_price": 1.1,
                "iv": 0.2, "delta": 0.5, "gamma": 0.01, "theta": -0.02, "vega": 0.1,
                "open_interest": 500, "volume": 50,
            }],
        },
    }
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        return _FakeResp(payload)

    monkeypatch.setattr(providers.urllib.request, "urlopen", fake_urlopen)
    s1 = providers.fetch_cboe_chain("ABC")
    s2 = providers.fetch_cboe_chain("ABC")
    assert calls["n"] == 1            # second call served from cache (no second CDN hit)
    assert s1 is s2                   # same cached object
    assert s1.spot == 100.0 and s1.quotes
    providers.clear_cboe_cache()
