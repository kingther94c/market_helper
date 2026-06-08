"""Trade Ideas advisor: regime-aligned tilt from the policy map (hermetic)."""

from __future__ import annotations

from market_helper.trade_advisor.adapters.ideas import TradeIdeasAdvisorPlugin
from market_helper.trade_advisor.contracts import AdvisorContext
from market_helper.trade_advisor.registry import build_default_registry

_POLICY = {
    "Reflation": {
        "vol_multiplier": 0.95,
        "asset_class_targets": {"EQ": 0.76, "FI": 0.10, "GOLD": 0.06, "CM": 0.05, "CASH": 0.03},
        "notes": "Reflation — stay with equities but cap duration.",
    }
}


def test_emits_regime_tilt():
    res = TradeIdeasAdvisorPlugin().produce(AdvisorContext(as_of="t", regime_label="Reflation"), policy=_POLICY)
    assert res.advisor == "ideas" and len(res.suggestions) == 1
    s = res.suggestions[0]
    assert s.label == "WATCHLIST" and s.category == "TILT" and s.body_kind == "ideas"
    assert "EQ" in s.thesis and s.detail["asset_class_targets"]["EQ"] == 0.76
    assert s.headline_metrics["vol_mult"] == "0.95"


def test_no_regime_is_info():
    res = TradeIdeasAdvisorPlugin().produce(AdvisorContext(as_of="t", regime_label=""), policy=_POLICY)
    assert res.suggestions[0].label == "INFO"


def test_unknown_regime_is_info():
    res = TradeIdeasAdvisorPlugin().produce(AdvisorContext(as_of="t", regime_label="Nonsense"), policy=_POLICY)
    assert res.suggestions[0].label == "INFO"


def test_default_policy_loads_without_io():
    # load_quadrant_policy(None) returns in-code defaults; Goldilocks is a known regime.
    res = TradeIdeasAdvisorPlugin().produce(AdvisorContext(as_of="t", regime_label="Goldilocks"))
    s = res.suggestions[0]
    assert s.category == "TILT" and s.detail.get("asset_class_targets")


def test_registered_in_default_registry():
    assert "ideas" in build_default_registry()
