"""FX Hedging adapter → hedge-target + carry-tilt suggestions (hermetic, injected provider)."""

from __future__ import annotations

from types import SimpleNamespace

from market_helper.trade_advisor.adapters.fx_hedge import FxHedgeAdvisorPlugin
from market_helper.trade_advisor.contracts import AdvisorContext
from market_helper.trade_advisor.registry import build_default_registry


def _leg(ccy, beta, contracts, notional, carry, on_rate, expiry="2026-09-16", instrument="6E"):
    return SimpleNamespace(
        currency=ccy, instrument=instrument, beta=beta, target_contracts=contracts,
        target_notional_usd=notional, expected_annual_carry_usd=carry, on_rate=on_rate, expiry=expiry,
    )


def _alloc():
    return SimpleNamespace(
        run_date="2026-06-03", hedge_target_pair="USD/SGD", hedge_notional_usd=1_000_000.0,
        hedge_notional_source="config_default", totals={"expected_annual_carry_bps": 35.0},
        regression={"r_squared": 0.88},
        legs=[
            _leg("EUR", 0.40, 3, 400_000, 6000, 0.025),   # carry 150 bps (top)
            _leg("CNH", 0.50, 5, 500_000, 1500, 0.018),   # carry 30 bps
            _leg("JPY", 0.10, 1, 100_000, -200, 0.001),   # carry -20 bps (bottom)
        ],
    )


def _state(alloc=None, *, computed_fresh=False, age_days=5, error=None):
    return SimpleNamespace(
        allocation=alloc, computed_fresh=computed_fresh, age_days=age_days,
        source_label="cache", error_message=error,
    )


def _ctx():
    return AdvisorContext(as_of="2026-06-03")


def test_emits_hedge_target_and_carry_tilt():
    res = FxHedgeAdvisorPlugin().produce(_ctx(), provider=lambda **k: _state(_alloc()))
    assert res.advisor == "fx_hedge" and len(res.suggestions) == 2
    assert {s.body_kind for s in res.suggestions} == {"fx_alloc", "fx_carry"}
    hedge = next(s for s in res.suggestions if s.body_kind == "fx_alloc")
    assert hedge.subject == "USD/SGD" and "1,000,000" in hedge.headline_metrics["notional"]
    assert hedge.headline_metrics["R2"] == "0.88"
    tilt = next(s for s in res.suggestions if s.body_kind == "fx_carry")
    assert tilt.headline_metrics["top"].startswith("EUR")     # highest carry
    assert tilt.headline_metrics["bottom"].startswith("JPY")  # lowest carry
    assert tilt.detail["ranking"][0]["currency"] == "EUR"


def test_default_mode_is_cached_no_network():
    captured = {}

    def fake(**k):
        captured.update(k)
        return _state(_alloc())

    FxHedgeAdvisorPlugin().produce(_ctx(), provider=fake)
    assert captured["mode"] == "cached"


def test_refresh_forces_recompute_and_marks_fresh():
    captured = {}

    def fake(**k):
        captured.update(k)
        return _state(_alloc(), computed_fresh=True, age_days=0)

    res = FxHedgeAdvisorPlugin().produce(_ctx(), provider=fake, refresh=True)
    assert captured["mode"] == "force-refresh" and res.data_mode == "fresh"


def test_missing_allocation_degrades_to_info():
    res = FxHedgeAdvisorPlugin().produce(_ctx(), provider=lambda **k: _state(None, error="no data"))
    assert res.data_mode == "missing"
    assert len(res.suggestions) == 1 and res.suggestions[0].label == "INFO"


def test_registered_in_default_registry():
    assert "fx_hedge" in build_default_registry()
