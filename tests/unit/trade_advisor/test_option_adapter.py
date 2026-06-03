"""Option adapter maps OptionIdea → shared Suggestion (hermetic: override path)."""

from __future__ import annotations

from market_helper.trade_advisor.adapters.option import OptionAdvisorPlugin
from market_helper.trade_advisor.contracts import AdvisorContext, Suggestion
from market_helper.trade_advisor.registry import build_default_registry


def _ctx():
    return AdvisorContext(
        as_of="2026-06-03",
        holdings={"NVDA": 100.0},
        aum=500_000.0,
        regime_label="Reflation",
        regime_confidence="Medium",
    )


def _run():
    plugin = OptionAdvisorPlugin()
    # user-override path → synthetic chain, fully offline (no network).
    return plugin.produce(
        _ctx(),
        overrides={"NVDA": {"spot": 120.0, "iv": 0.45}},
        fetch_realized=False,
    )


def test_adapter_returns_shared_result_shape():
    result = _run()
    assert result.advisor == "option"
    assert result.data_mode == "user_override"
    assert result.suggestions
    assert all(isinstance(s, Suggestion) for s in result.suggestions)


def test_suggestions_carry_uniform_fields():
    result = _run()
    for s in result.suggestions:
        assert s.advisor == "option"
        assert s.title and s.subject == "NVDA"
        assert s.label in ("PROCEED", "MONITOR", "REJECT", "INFO")
        assert s.body_kind == "option_payoff"
        assert s.audit  # filter trail projected
        assert "legs" in s.detail  # advisor-specific payload preserved
    # model-only data must never PROCEED (honesty rule)
    assert all(s.label != "PROCEED" for s in result.suggestions)


def test_headline_metrics_populated():
    result = _run()
    # at least one idea exposes net / max_loss style one-liners for the card
    assert any(s.headline_metrics for s in result.suggestions)


def test_runs_via_registry():
    reg = build_default_registry()
    result = reg.get("option").produce(
        _ctx(), overrides={"NVDA": {"spot": 120.0, "iv": 0.45}}, fetch_realized=False
    )
    assert result.advisor == "option" and result.suggestions
