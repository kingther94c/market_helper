"""Follow-ups from the comprehensive review — honesty, matching robustness, journal edges (hermetic)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from market_helper.domain.tactical_ideas.ai_tools import build_tactical_tool_registry
from market_helper.domain.tactical_ideas.tactical_edge import parse_tactical_edge
from market_helper.trade_advisor.adapters.fx_hedge import FxHedgeAdvisorPlugin
from market_helper.trade_advisor.adapters.tactical import TacticalIdeasPlugin
from market_helper.trade_advisor.contracts import AdvisorContext, Suggestion
from market_helper.trade_advisor.journal import DecisionJournal, decision_from_suggestion


def _edge(md: str) -> Suggestion:
    _, cards = parse_tactical_edge(md)
    res = TacticalIdeasPlugin().produce(
        AdvisorContext(as_of="t"), edge_cards=cards,
        prediction=SimpleNamespace(available=False), trending=SimpleNamespace(available=False),
    )
    return [s for s in res.suggestions if s.body_kind == "tactical_edge"][0]


def test_edge_risk_boundedness_ignores_spread_in_risk_prose():
    s = _edge("# t — d\n\n### #1. Directional macro — Developing\n\n"
              "- **Retail expression**: long EUR/USD futures (no options).\n"
              "- **Risk / stop**: the bid/ask spread can widen on risk-off.\n"
              "- **Scores**: Conviction-today 3/5\n")
    assert s.assessment.risk_boundedness == "undefined"   # "spread" in the RISK prose must not imply capped


def test_edge_actionability_not_fooled_by_benign_words():
    s = _edge("# t — d\n\n### #1. Idea — Developing\n\n"
              "- **Trigger / entry**: this is well-known and nowhere near a trigger yet.\n"
              "- **Scores**: Conviction-today 3/5\n")
    assert s.assessment.actionability == "watch"           # "known"/"nowhere" must not match \\bnow\\b/\\bact\\b


def test_edge_actionability_staged_on_act():
    s = _edge("# t — d\n\n### #1. Idea — Developing (act Mon)\n\n"
              "- **Trigger / entry**: open the pair Monday.\n"
              "- **Scores**: Conviction-today 4/5\n")
    assert s.assessment.actionability == "staged"          # external research → staged at most, never act_now


def test_get_tactical_edge_tool_is_registered_and_read_only():
    reg = build_tactical_tool_registry()
    assert "get_tactical_edge" in reg and reg.get("get_tactical_edge").read_only


def test_fx_missing_card_reports_missing_not_synthetic():
    res = FxHedgeAdvisorPlugin().produce(
        AdvisorContext(as_of="t"),
        provider=lambda **k: SimpleNamespace(allocation=None, error_message="no cache"),
    )
    s = res.suggestions[0]
    assert s.assessment.data_quality == "missing" and s.assessment.actionability == "parked"


def test_tactical_none_card_is_parked(tmp_path):
    snap = {"base_regime": "", "final_regime": "", "confidence": "Low", "risk_overlay_on": False,
            "final_growth_score": 0.0, "final_inflation_score": 0.0, "risk_score": 0.5}
    p = tmp_path / "regime_snapshots.json"
    p.write_text(json.dumps([snap]), encoding="utf-8")
    res = TacticalIdeasPlugin().produce(
        AdvisorContext(as_of="t"), regime_path=p,
        prediction=SimpleNamespace(available=False), trending=SimpleNamespace(available=False),
    )
    s = res.suggestions[0]
    assert s.label == "INFO" and s.assessment.actionability == "parked"


def _s(sid: str = "t:1") -> Suggestion:
    return Suggestion(advisor="tactical", suggestion_id=sid, as_of="2026-06-08",
                      title="T", subject="X", category="TACTICAL")


def test_due_for_review_fires_with_full_timestamp_as_of(tmp_path):
    j = DecisionJournal(tmp_path / "d.jsonl")
    j.record(decision_from_suggestion(_s(), "PROMOTE", ts="2026-06-08T10:00:00"))
    due = j.due_for_review("2026-07-08T09:30:00")          # the 30d milestone is 2026-07-08
    assert [m for _, m in due] == ["2026-07-08"]


def test_watch_then_dismiss_then_rewatch_reschedules(tmp_path):
    j = DecisionJournal(tmp_path / "d.jsonl")
    j.record(decision_from_suggestion(_s(), "WATCH", ts="2026-06-08T10:00:00"))
    j.record(decision_from_suggestion(_s(), "DISMISS", ts="2026-06-09T10:00:00"))
    assert j.due_for_review("2027-01-01") == []            # dismissed → no reviews
    j.record(decision_from_suggestion(_s(), "WATCH", ts="2026-06-10T10:00:00"))
    assert {m for _, m in j.due_for_review("2027-01-01")} == {"2026-07-10", "2026-08-09", "2026-09-08"}
