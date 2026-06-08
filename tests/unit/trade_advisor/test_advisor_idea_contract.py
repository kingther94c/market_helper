"""AdvisorIdea v1 contract — four orthogonal axes, never one score (hermetic)."""

from __future__ import annotations

from market_helper.trade_advisor.contracts import (
    ACTIONABILITY_LEVELS,
    CONFIDENCE_LEVELS,
    DATA_QUALITY_LEVELS,
    RISK_BOUNDEDNESS_LEVELS,
    IdeaAssessment,
    Suggestion,
    data_quality_for_mode,
)


def test_assessment_defaults_are_conservative():
    a = IdeaAssessment()
    assert (a.confidence, a.actionability, a.risk_boundedness, a.data_quality) == (
        "low", "watch", "undefined", "synthetic",
    )


def test_axes_are_independent():
    # A high-confidence signal can still be un-actionable with an undefined risk on fresh data —
    # the whole point of keeping them separate.
    a = IdeaAssessment(confidence="high", actionability="parked", risk_boundedness="undefined", data_quality="recent")
    assert a.confidence in CONFIDENCE_LEVELS and a.actionability in ACTIONABILITY_LEVELS
    assert a.risk_boundedness in RISK_BOUNDEDNESS_LEVELS and a.data_quality in DATA_QUALITY_LEVELS


def test_idea_id_and_module_are_canonical_aliases():
    s = Suggestion(advisor="tactical", suggestion_id="tactical:SHORT_USD", as_of="t",
                   title="T", subject="USD", category="TACTICAL")
    assert s.idea_id == "tactical:SHORT_USD" and s.module == "tactical"


def test_research_fields_default_empty_and_assessment_present():
    s = Suggestion(advisor="x", suggestion_id="y", as_of="t", title="T", subject="S", category="C")
    assert s.instrument_family == "" and s.evidence == [] and s.risk == "" and s.invalidation == ""
    assert s.missing_data == [] and s.portfolio_interaction == "" and s.review_after == [] and s.journal_note == ""
    assert isinstance(s.assessment, IdeaAssessment)


def test_data_quality_for_mode_ladder():
    assert data_quality_for_mode("live_chain") == "live"
    assert data_quality_for_mode("regime+model") == "recent"   # must beat the bare 'regime' prefix
    assert data_quality_for_mode("regime") == "stale"
    assert data_quality_for_mode("cached_3d") == "stale"
    assert data_quality_for_mode("user_override") == "synthetic"
    assert data_quality_for_mode("") == "synthetic"
