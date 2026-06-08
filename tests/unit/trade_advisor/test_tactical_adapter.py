"""Tactical Trade Ideas adapter → WATCHLIST-capped idea suggestions (hermetic)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from market_helper.trade_advisor.adapters.tactical import TacticalIdeasPlugin
from market_helper.trade_advisor.contracts import AdvisorContext
from market_helper.trade_advisor.registry import build_default_registry


def _snapshot(tmp_path, **fields):
    snap = {"base_regime": "Reflation", "confidence": "Medium", "risk_overlay_on": False,
            "final_growth_score": 0.1, "final_inflation_score": 0.2, "risk_score": 0.2}
    snap.update(fields)
    p = tmp_path / "regime_snapshots.json"
    p.write_text(json.dumps([snap]), encoding="utf-8")
    return p


def test_adapter_emits_monitor_capped_tactical_ideas(tmp_path):
    p = _snapshot(tmp_path)
    pred = SimpleNamespace(available=True, top_expert="Reflation", confidence=0.4, sleeve_weights={"CM": 20.0})
    trend = SimpleNamespace(available=False, probabilities={})
    res = TacticalIdeasPlugin().produce(AdvisorContext(as_of="t"), regime_path=p, prediction=pred, trending=trend)
    assert res.advisor == "tactical" and res.suggestions
    assert all(s.body_kind == "tactical" for s in res.suggestions)
    # Independent directional trades are advisory only — never RESEARCH_READY.
    assert all(s.label in ("WATCHLIST", "INFO") for s in res.suggestions)
    assert any("SHORT_USD" in s.suggestion_id for s in res.suggestions)


def test_adapter_no_signals_is_info(tmp_path):
    # An unknown/blank regime fires no grounded anchor → a single INFO card.
    p = _snapshot(tmp_path, base_regime="", final_regime="", final_growth_score=0.0,
                  final_inflation_score=0.0, risk_score=0.5)
    res = TacticalIdeasPlugin().produce(
        AdvisorContext(as_of="t"), regime_path=p,
        prediction=SimpleNamespace(available=False), trending=SimpleNamespace(available=False),
    )
    assert len(res.suggestions) == 1 and res.suggestions[0].label == "INFO"


def test_registered_in_default_registry():
    assert "tactical" in build_default_registry()


def test_suggestions_carry_assessment_and_research_fields(tmp_path):
    p = _snapshot(tmp_path)
    pred = SimpleNamespace(available=True, top_expert="Reflation", confidence=0.4, sleeve_weights={"CM": 20.0})
    res = TacticalIdeasPlugin().produce(
        AdvisorContext(as_of="t"), regime_path=p, prediction=pred,
        trending=SimpleNamespace(available=False, probabilities={}),
    )
    assert res.suggestions
    for s in res.suggestions:
        a = s.assessment
        assert a.actionability == "watch"               # research-tier never act_now from a rule anchor
        assert a.confidence in ("high", "medium", "low")
        assert a.data_quality in ("recent", "stale")     # regime / regime+model
        assert s.instrument_family and s.risk and s.invalidation and s.portfolio_interaction
