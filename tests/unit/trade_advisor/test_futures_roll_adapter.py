"""Futures Roll & Carry Calendar adapter → roll-reminder suggestions (hermetic)."""

from __future__ import annotations

from market_helper.trade_advisor.adapters.futures_roll import FuturesRollPlugin
from market_helper.trade_advisor.contracts import AdvisorContext
from market_helper.trade_advisor.registry import build_default_registry


def test_empty_book_is_info():
    res = FuturesRollPlugin().produce(AdvisorContext(as_of="t"))
    assert res.advisor == "futures_roll"
    assert len(res.suggestions) == 1 and res.suggestions[0].label == "INFO"
    assert res.suggestions[0].body_kind == "futures_roll"


def test_emits_roll_suggestions_by_schedule():
    ctx = AdvisorContext(
        as_of="t",
        held_futures=[
            {"root": "NG", "contract": "NGQ26", "exchange": "NYMEX", "qty": -1.0},
            {"root": "ZN", "contract": "10Y US", "exchange": "CBOT", "qty": 1.0},
        ],
    )
    res = FuturesRollPlugin().produce(ctx, today="2026-07-06")
    assert {s.body_kind for s in res.suggestions} == {"futures_roll"}
    ng = next(s for s in res.suggestions if s.subject == "NG")
    assert ng.label == "PROCEED" and ng.headline_metrics["schedule"] == "GSCI"
    assert ng.detail["delivery_label"] == "Aug 2026"
    zn = next(s for s in res.suggestions if s.subject == "ZN")
    assert zn.label == "INFO"  # unparseable contract month → manual review


def test_registered_in_default_registry():
    reg = build_default_registry()
    assert "futures_roll" in reg
