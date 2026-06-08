"""Tactical signal layer: offline context assembly + grounded idea rules (hermetic)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from market_helper.domain.tactical_ideas.signals import (
    TacticalContext,
    build_tactical_context,
    generate_tactical_ideas,
)


def _snapshot(tmp_path, **fields):
    snap = {
        "base_regime": "Reflation", "confidence": "Medium", "risk_overlay_on": False,
        "final_growth_score": 0.1, "final_inflation_score": 0.2, "risk_score": 0.2, "as_of": "2026-06-07",
    }
    snap.update(fields)
    p = tmp_path / "regime_snapshots.json"
    p.write_text(json.dumps([snap]), encoding="utf-8")
    return p


def test_build_context_merges_regime_and_model(tmp_path):
    p = _snapshot(tmp_path)
    pred = SimpleNamespace(available=True, top_expert="Reflation", confidence=0.42,
                           sleeve_weights={"EQ": 60.0, "CM": 20.0, "FI": 10.0})
    trend = SimpleNamespace(available=True, probabilities={"Reflation": 0.4, "Goldilocks": 0.3, "Stagflation": 0.2})
    ctx = build_tactical_context(regime_path=p, prediction=pred, trending=trend)
    assert ctx.regime == "Reflation" and ctx.inflation_score == 0.2 and ctx.crisis is False
    assert ctx.expert_available and ctx.top_expert == "Reflation" and ctx.sleeve_weights["CM"] == 20.0
    assert ctx.trend_available and ctx.trend_top == "Reflation"
    assert {"regime_snapshot", "policy_expert_predictor", "policy_expert_trending"} <= set(ctx.sources)


def test_reflation_generates_expected_anchors():
    ctx = TacticalContext(
        regime="Reflation", confidence="Medium", crisis=False, growth_score=0.1, inflation_score=0.2,
        risk_score=0.2, expert_available=True, top_expert="Reflation", expert_confidence=0.4,
        sleeve_weights={"CM": 20.0}, trend_available=True, trend_top="Reflation",
        trend_probabilities={"Reflation": 0.4},
    )
    ideas = generate_tactical_ideas(ctx)
    # Scarcity: a decision filter, not a story machine — at most 3, the top-priority anchors.
    assert len(ideas) == 3
    themes = {i.theme for i in ideas}
    assert themes == {"SHORT_USD", "SECTOR_ROTATION", "STEEPENER"}
    assert all(i.data_mode == "regime+model" for i in ideas)
    # Every surviving idea is grounded (evidence), falsifiable (invalidation), and answers
    # the five decision questions.
    assert all(i.evidence and i.invalidation for i in ideas)
    assert all(i.edge and i.disqualifier and i.overlap and i.regime_kill and i.confirm for i in ideas)


def test_crisis_is_risk_off_not_short_vol():
    ctx = TacticalContext(regime="Deflationary Slowdown", crisis=True, risk_score=0.85)
    themes = {i.theme for i in generate_tactical_ideas(ctx)}
    assert "RISK_OFF" in themes
    assert "SHORT_VIX" not in themes      # never short vol mid-crisis
    assert "STEEPENER" not in themes      # deflationary → not a steepener
    assert "SECTOR_ROTATION" in themes    # regime-keyed rotation still applies


def test_calm_tape_allows_short_vix_carry():
    ctx = TacticalContext(regime="Goldilocks", crisis=False, risk_score=0.2, growth_score=0.1)
    themes = {i.theme for i in generate_tactical_ideas(ctx)}
    assert "SHORT_VIX" in themes
    assert "RISK_OFF" not in themes


def test_neutral_mixed_label_derives_quadrant_for_rotation(tmp_path):
    # The live engine emits "Neutral/Mixed …" (not one of the 4 quadrants). The advisor
    # must derive a quadrant from the axis scores so sector rotation still fires + the
    # regime isn't blank — and stay honest that it was derived.
    p = _snapshot(tmp_path, base_regime="Neutral/Mixed Growth / Neutral/Mixed Inflation",
                  final_regime="Neutral/Mixed Growth / Neutral/Mixed Inflation",
                  final_growth_score=0.16, final_inflation_score=0.35)
    ctx = build_tactical_context(regime_path=p, prediction=SimpleNamespace(available=False),
                                 trending=SimpleNamespace(available=False))
    assert ctx.regime == ""                      # not a known quadrant → blank mapped label
    assert ctx.regime_effective == "Reflation"   # derived from +growth / +inflation
    assert "Neutral/Mixed" in ctx.regime_label_raw
    ideas = generate_tactical_ideas(ctx)
    sect = [i for i in ideas if i.theme == "SECTOR_ROTATION"]
    assert sect, "sector rotation must fire via the derived quadrant"
    assert "derived from scores" in " ".join(sect[0].evidence)  # honest about the derivation
