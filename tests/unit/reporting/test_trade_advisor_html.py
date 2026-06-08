"""Trade-advisor static snapshot renderer + writer (hermetic)."""

from __future__ import annotations

from market_helper.reporting.trade_advisor_html import (
    render_trade_advisor_section_body,
    render_trade_advisor_snapshot,
)
from market_helper.trade_advisor.journal import Decision, DecisionJournal


def test_empty_snapshot_has_empty_state():
    assert "No flagged ideas" in render_trade_advisor_section_body([])
    doc = render_trade_advisor_snapshot([], as_of="2026-06-03")
    assert "<html" in doc and "Trade Advisor" in doc and "2026-06-03" in doc


def test_snapshot_lists_decisions_and_escapes_notes():
    decs = [
        Decision(
            ts="2026-06-03T10:00:00", suggestion_id="SPY:COLLAR", advisor="option",
            subject="SPY", title="COLLAR · SPY", decision="PROMOTE", note="<b>watch</b>",
        )
    ]
    body = render_trade_advisor_section_body(decs)
    assert "PROMOTE" in body and "COLLAR · SPY" in body
    assert "&lt;b&gt;watch&lt;/b&gt;" in body and "<b>watch</b>" not in body  # escaped


def test_write_decision_snapshot_to_disk(tmp_path):
    from market_helper.application.trade_advisor import write_decision_snapshot

    journal = DecisionJournal(tmp_path / "j.jsonl")
    journal.record(
        Decision(ts="2026-06-03T10:00:00", suggestion_id="X", advisor="option",
                 subject="SPY", title="COLLAR · SPY", decision="WATCH")
    )
    out = write_decision_snapshot(journal, output_path=tmp_path / "snap.html", mirror=False)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "COLLAR · SPY" in text and "WATCH" in text
