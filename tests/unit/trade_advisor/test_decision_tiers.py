"""Decision tiers + the RESEARCH_READY trust ceiling (hermetic).

Modules are not peers in trust: only operational (T1) / deterministic (T2) tiers may
reach RESEARCH_READY; model-overlay (T3) and research (T4) cap at WATCHLIST.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from market_helper.trade_advisor.adapters.ideas import TradeIdeasAdvisorPlugin
from market_helper.trade_advisor.adapters.roll import RollReminderPlugin
from market_helper.trade_advisor.adapters.tactical import TacticalIdeasPlugin
from market_helper.trade_advisor.contracts import (
    LABEL_RESEARCH_READY,
    LABEL_WATCHLIST,
    TIER_DETERMINISTIC,
    TIER_MODEL_OVERLAY,
    TIER_OPERATIONAL,
    TIER_RESEARCH,
    AdvisorContext,
    cap_label_for_tier,
)


def test_cap_label_for_tier_enforces_the_ceiling():
    assert cap_label_for_tier(LABEL_RESEARCH_READY, TIER_RESEARCH) == LABEL_WATCHLIST
    assert cap_label_for_tier(LABEL_RESEARCH_READY, TIER_MODEL_OVERLAY) == LABEL_WATCHLIST
    assert cap_label_for_tier(LABEL_RESEARCH_READY, TIER_OPERATIONAL) == LABEL_RESEARCH_READY
    assert cap_label_for_tier(LABEL_RESEARCH_READY, TIER_DETERMINISTIC) == LABEL_RESEARCH_READY
    assert cap_label_for_tier(LABEL_WATCHLIST, TIER_OPERATIONAL) == LABEL_WATCHLIST  # non-RR untouched


def test_roll_is_operational_and_urgent_can_be_research_ready():
    held = [{"underlying": "SPY", "right": "C", "strike": 740, "expiry": "2026-06-08", "qty": -1, "underlying_price": 759.0}]
    res = RollReminderPlugin().produce(AdvisorContext(as_of="2026-06-03", held_options=held), today="2026-06-03")
    s = res.suggestions[0]
    assert s.decision_tier == TIER_OPERATIONAL and s.label == LABEL_RESEARCH_READY


def test_ideas_is_research_tier_and_capped():
    res = TradeIdeasAdvisorPlugin().produce(AdvisorContext(as_of="t", regime_label="Goldilocks"))
    s = res.suggestions[0]
    assert s.decision_tier == TIER_RESEARCH and s.label != LABEL_RESEARCH_READY


def test_tactical_is_research_tier_and_never_research_ready(tmp_path):
    snap = {"base_regime": "Reflation", "confidence": "Medium", "risk_overlay_on": False,
            "final_growth_score": 0.1, "final_inflation_score": 0.2, "risk_score": 0.2}
    p = tmp_path / "regime_snapshots.json"
    p.write_text(json.dumps([snap]), encoding="utf-8")
    pred = SimpleNamespace(available=True, top_expert="Reflation", confidence=0.4, sleeve_weights={"CM": 20.0})
    res = TacticalIdeasPlugin().produce(
        AdvisorContext(as_of="t"), regime_path=p, prediction=pred,
        trending=SimpleNamespace(available=False, probabilities={}),
    )
    assert res.suggestions
    assert all(s.decision_tier == TIER_RESEARCH for s in res.suggestions)
    assert all(s.label != LABEL_RESEARCH_READY for s in res.suggestions)
