"""Ex-ante decision journal + the 30/60/90 review loop (hermetic) — the decision validation."""

from __future__ import annotations

from market_helper.trade_advisor.contracts import IdeaAssessment, Suggestion
from market_helper.trade_advisor.journal import (
    DecisionJournal,
    Review,
    decision_from_suggestion,
    review_dates,
)


def _sugg() -> Suggestion:
    return Suggestion(
        advisor="tactical", suggestion_id="tactical_edge:1:permafrost", as_of="2026-06-08",
        title="Edge #1: Permafrost steepener", subject="rates", category="TACTICAL",
        label="WATCHLIST", decision_tier="T4 · research", data_mode="tactical_edge",
        thesis="Repatriation steepens 5s30s.", instrument_family="rates_curve",
        risk="Risk-off bull-flattening.", invalidation="5s30s flattens 8bp.",
        assessment=IdeaAssessment(confidence="low", actionability="watch",
                                  risk_boundedness="undefined", data_quality="recent"),
    )


def test_review_dates_are_30_60_90():
    assert review_dates("2026-06-08") == ["2026-07-08", "2026-08-07", "2026-09-06"]
    assert review_dates("2026-06-08T10:00:00") == ["2026-07-08", "2026-08-07", "2026-09-06"]
    assert review_dates("not-a-date") == []


def test_decision_freezes_ex_ante_snapshot():
    d = decision_from_suggestion(_sugg(), "PROMOTE", ts="2026-06-08T10:00:00", note="curve story")
    assert d.ex_ante_thesis.startswith("Repatriation") and d.confidence == "low"
    assert d.label == "WATCHLIST" and d.instrument_family == "rates_curve" and d.invalidation
    assert d.review_after == ["2026-07-08", "2026-08-07", "2026-09-06"]
    # A dismissal schedules no reviews.
    assert decision_from_suggestion(_sugg(), "DISMISS", ts="2026-06-08T10:00:00").review_after == []


def test_due_for_review_and_recording_closes_a_milestone(tmp_path):
    j = DecisionJournal(tmp_path / "decisions.jsonl")
    j.record(decision_from_suggestion(_sugg(), "PROMOTE", ts="2026-06-08T10:00:00"))
    assert j.due_for_review("2026-07-01") == []                 # before the 30d milestone
    due = j.due_for_review("2026-07-10")
    assert len(due) == 1 and due[0][1] == "2026-07-08"          # 30d milestone owed
    j.record_review(Review(ts="2026-07-10T09:00:00", suggestion_id="tactical_edge:1:permafrost",
                           milestone="2026-07-08", verdict="partly", note="curve flat, not steep yet"))
    assert j.due_for_review("2026-07-10") == []                 # that milestone now closed
    later = {m for _, m in j.due_for_review("2026-09-30")}       # 60 + 90 now owed
    assert later == {"2026-08-07", "2026-09-06"}
    assert j.all_reviews()[0].verdict == "partly"


def test_dismissed_idea_is_never_reviewed(tmp_path):
    j = DecisionJournal(tmp_path / "decisions.jsonl")
    j.record(decision_from_suggestion(_sugg(), "DISMISS", ts="2026-06-08T10:00:00"))
    assert j.due_for_review("2027-01-01") == []


def test_old_decision_lines_without_new_fields_still_read(tmp_path):
    # Schema drift: a pre-ex-ante line (only the original fields) must still parse.
    p = tmp_path / "decisions.jsonl"
    p.write_text('{"ts":"t","suggestion_id":"x","advisor":"option","subject":"S",'
                 '"title":"T","decision":"PROMOTE"}\n', encoding="utf-8")
    j = DecisionJournal(p)
    rows = j.all()
    assert len(rows) == 1 and rows[0].review_after == [] and rows[0].confidence == ""
