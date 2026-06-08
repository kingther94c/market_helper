"""Decision journal: record / read / latest-wins / inbox ordering (hermetic)."""

from __future__ import annotations

from market_helper.trade_advisor.contracts import Suggestion
from market_helper.trade_advisor.journal import Decision, DecisionJournal, decision_from_suggestion


def _d(ts, sid, decision, note=""):
    return Decision(ts=ts, suggestion_id=sid, advisor="option", subject="SPY", title="t", decision=decision, note=note)


def test_record_read_and_latest_wins(tmp_path):
    j = DecisionJournal(tmp_path / "decisions.jsonl")
    assert j.all() == []
    j.record(_d("2026-06-03T10:00:00", "SPY:COLLAR", "WATCH", "watch IV"))
    j.record(_d("2026-06-03T11:00:00", "SPY:COLLAR", "PROMOTE", "do it"))
    assert len(j.all()) == 2
    latest = j.latest_by_suggestion()
    assert latest["SPY:COLLAR"].decision == "PROMOTE"  # last write wins
    assert latest["SPY:COLLAR"].note == "do it"


def test_inbox_filters_rejects_and_orders(tmp_path):
    j = DecisionJournal(tmp_path / "decisions.jsonl")
    j.record(_d("t1", "a", "DISMISS"))
    j.record(_d("t2", "b", "WATCH"))
    j.record(_d("t3", "c", "PROMOTE"))
    ids = [d.suggestion_id for d in j.inbox()]
    assert "a" not in ids          # DISMISS excluded
    assert ids[0] == "c"           # PROMOTE first
    assert "b" in ids


def test_corrupt_line_is_skipped(tmp_path):
    path = tmp_path / "decisions.jsonl"
    path.write_text('{"bad json\n' + '{"ts":"t","suggestion_id":"x","advisor":"option","subject":"S","title":"T","decision":"PROMOTE"}\n', encoding="utf-8")
    j = DecisionJournal(path)
    alld = j.all()
    assert len(alld) == 1 and alld[0].suggestion_id == "x"


def test_decision_from_suggestion():
    s = Suggestion(advisor="option", suggestion_id="X", as_of="2026-06-03", title="T", subject="SPY", category="HEDGE", score=0.9)
    d = decision_from_suggestion(s, "PROMOTE", ts="2026-06-03T12:00:00", note="ok")
    assert d.decision == "PROMOTE" and d.subject == "SPY" and d.note == "ok" and d.score == 0.9


def test_default_journal_path_resolves():
    from market_helper.application.trade_advisor import default_decision_journal

    j = default_decision_journal()
    assert j.path.name == "decision_journal.jsonl"
    assert "trade_advisor" in str(j.path)
