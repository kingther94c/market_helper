"""Data-honesty validation — synthetic/cached/missing data is never presented as live."""

from __future__ import annotations

from market_helper.trade_advisor.adapters.option import OptionAdvisorPlugin
from market_helper.trade_advisor.contracts import AdvisorContext, data_quality_for_mode


def test_unreal_data_modes_never_map_to_live():
    for mode in ("synthetic", "user_override", "cached", "cached_5d", "missing", "regime", "stale", ""):
        assert data_quality_for_mode(mode) != "live"


def test_option_synthetic_run_reports_synthetic_not_live():
    res = OptionAdvisorPlugin().produce(
        AdvisorContext(as_of="2026-06-03", holdings={"NVDA": 100.0}, aum=500_000.0, regime_label="Reflation"),
        overrides={"NVDA": {"spot": 120.0, "iv": 0.45}}, fetch_realized=False,
    )
    assert res.data_mode == "user_override"
    for s in res.suggestions:
        assert s.data_mode == "user_override"             # the honesty tag rides on the idea
        assert s.assessment.data_quality == "synthetic"   # user_override → synthetic, never live
