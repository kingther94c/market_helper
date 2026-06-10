"""The "Today" attention strip — pure synthesis of pre-gathered module states."""

from __future__ import annotations

from types import SimpleNamespace

from market_helper.presentation.dashboard.pages.trade_advisor.overview import (
    TAB_FX,
    TAB_OPTION,
    TAB_ROLL,
    build_attention_items,
)
from market_helper.trade_advisor.contracts import LABEL_RESEARCH_READY, LABEL_WATCHLIST


def _items(**kw):
    base = dict(today="2026-06-10", roll_rows=None, due_reviews=0,
                fx_panel=None, edge_date="", edge_count=0, scan=None)
    base.update(kw)
    return build_attention_items(**base)


def _by_key(items):
    return {it["key"]: it for it in items}


def test_roll_urgent_is_an_alert_and_ranks_first():
    rows = [
        {"label": LABEL_WATCHLIST, "subject": "ZN", "instrument": "Sep 2026"},
        {"label": LABEL_RESEARCH_READY, "subject": "NG", "instrument": "Aug 2026"},
        {"label": LABEL_RESEARCH_READY, "subject": "CL", "instrument": "Aug 2026"},
    ]
    items = _items(roll_rows=rows, scan={"suggestions": []})
    roll = _by_key(items)["roll"]
    assert roll["severity"] == "alert" and roll["tab"] == TAB_ROLL
    assert "NG Aug 2026" in roll["text"] and "+1 more" in roll["text"]
    assert items[0]["key"] == "roll"                       # alerts sort first


def test_roll_window_and_nothing_due():
    window = _by_key(_items(roll_rows=[{"label": LABEL_WATCHLIST, "subject": "ZN", "instrument": "U6"}]))["roll"]
    assert window["severity"] == "warn" and "Roll window: 1 position" in window["text"]
    quiet = _by_key(_items(roll_rows=[]))["roll"]
    assert quiet["severity"] == "ok"


def test_roll_absent_when_unreadable():
    assert "roll" not in _by_key(_items(roll_rows=None))   # never fabricate a status


def test_due_reviews_chip():
    item = _by_key(_items(due_reviews=3))["reviews"]
    assert item["severity"] == "warn" and "3 idea reviews due" in item["text"]
    assert "reviews" not in _by_key(_items(due_reviews=0))


def test_fx_stale_target_warns():
    panel = {"available": True, "data_mode": "cached_45d", "tilt_detail": {}}
    item = _by_key(_items(fx_panel=panel))["fx"]
    assert item["severity"] == "warn" and "45d" in item["text"] and item["tab"] == TAB_FX


def test_fx_fresh_tilt_headline():
    panel = {"available": True, "data_mode": "cached_5d",
             "tilt_detail": {"tilt": {"rows": [1], "carry_impact_bps": 23.4, "hedge_deviation_pct": 0.09}}}
    item = _by_key(_items(fx_panel=panel))["fx"]
    assert item["severity"] == "info" and "+23bps" in item["text"] and "9% deviation" in item["text"]


def test_fx_unavailable_is_info_not_invented():
    item = _by_key(_items(fx_panel={"available": False}))["fx"]
    assert item["severity"] == "info" and "no cached hedge target" in item["text"]


def test_edge_brief_fresh_vs_stale():
    fresh = _by_key(_items(edge_date="2026-06-09", edge_count=12))["edge"]
    assert fresh["severity"] == "info" and "12 cards" in fresh["text"]
    stale = _by_key(_items(edge_date="2026-06-01"))["edge"]
    assert stale["severity"] == "warn" and "9d old" in stale["text"]
    assert "edge" not in _by_key(_items(edge_date=""))     # folder not configured → no chip


def test_scan_chip_counts_ready_and_prompts_when_missing():
    sugs = [SimpleNamespace(label=LABEL_RESEARCH_READY), SimpleNamespace(label=LABEL_WATCHLIST)]
    have = _by_key(_items(scan={"saved_at": "2026-06-09T18:00:00", "suggestions": sugs}))["scan"]
    assert "2026-06-09" in have["text"] and "2 ideas (1 ready)" in have["text"]
    assert have["tab"] == TAB_OPTION
    none = _by_key(_items(scan=None))["scan"]
    assert "scan now" in none["text"]
