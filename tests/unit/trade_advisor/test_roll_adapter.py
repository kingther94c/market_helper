"""Roll Reminder advisor: DTE/ITM/assignment flags + labels (hermetic)."""

from __future__ import annotations

from market_helper.trade_advisor.adapters.roll import RollReminderPlugin
from market_helper.trade_advisor.contracts import AdvisorContext
from market_helper.trade_advisor.registry import build_default_registry

TODAY = "2026-06-03"


def _ctx(held):
    return AdvisorContext(as_of=TODAY, held_options=held)


def test_empty_book_returns_info():
    res = RollReminderPlugin().produce(_ctx([]), today=TODAY)
    assert res.advisor == "roll"
    assert len(res.suggestions) == 1 and res.suggestions[0].label == "INFO"


def test_short_itm_near_expiry_is_proceed_with_assignment_flag():
    held = [{"underlying": "SPY", "right": "C", "strike": 740, "expiry": "2026-06-08", "qty": -1, "underlying_price": 759.0}]
    res = RollReminderPlugin().produce(_ctx(held), today=TODAY)  # 5 DTE, short call ITM
    s = res.suggestions[0]
    assert s.label == "PROCEED"
    assert s.subject == "SPY" and s.category == "ROLL" and s.body_kind == "roll"
    assert any(a.name == "assignment_risk" for a in s.audit)
    assert s.headline_metrics["moneyness"] == "ITM"


def test_in_window_is_monitor():
    held = [{"underlying": "QQQ", "right": "P", "strike": 700, "expiry": "2026-06-18", "qty": -1, "underlying_price": 760.0}]
    res = RollReminderPlugin().produce(_ctx(held), today=TODAY)  # 15 DTE, OTM short put
    assert res.suggestions[0].label == "MONITOR"


def test_far_expiry_is_info():
    held = [{"underlying": "AAPL", "right": "C", "strike": 300, "expiry": "2026-09-18", "qty": 1, "underlying_price": 315.0}]
    res = RollReminderPlugin().produce(_ctx(held), today=TODAY)  # ~107 DTE
    assert res.suggestions[0].label == "INFO"


def test_registered_and_runs_via_registry():
    reg = build_default_registry()
    assert "roll" in reg
    res = reg.get("roll").produce(_ctx([]), today=TODAY)
    assert res.advisor == "roll" and res.suggestions
