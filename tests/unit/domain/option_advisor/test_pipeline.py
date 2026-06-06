"""Filters, sizing, ranking, and the end-to-end service (no network)."""

from __future__ import annotations

from dataclasses import replace

from market_helper.domain.option_advisor import providers, service
from market_helper.domain.option_advisor.config import load_rules


def test_user_override_path_is_capped_at_monitor():
    """Model-only data (no live chain) must never PROCEED — the honesty rule."""
    res = service.run_advisor(
        ["NVDA"], aum=1_000_000, holdings={"NVDA": 100},
        overrides={"NVDA": {"spot": 120.0, "iv": 0.45}}, fetch_realized=False,
    )
    assert res.data_mode == "user_override"
    assert res.ideas
    assert all(i.label != "PROCEED" for i in res.ideas)
    assert all(i.data_status == "model_only" for i in res.ideas)


def test_sizing_hard_rejects_when_too_large_for_aum():
    res = service.run_advisor(
        ["NVDA"], aum=2_000,
        overrides={"NVDA": {"spot": 120.0, "iv": 0.45}}, fetch_realized=False,
    )
    csp = [i for i in res.ideas if i.structure_type == "CASH_SECURED_PUT"]
    assert csp and csp[0].label == "REJECT"
    assert any(not f.passed and f.severity == "hard" for f in csp[0].filters_applied)


def test_audit_trail_present_on_every_idea():
    res = service.run_advisor(
        ["NVDA"], aum=500_000,
        overrides={"NVDA": {"spot": 120.0, "iv": 0.45}}, fetch_realized=False,
    )
    for idea in res.ideas:
        assert idea.filters_applied  # each idea carries its filter outcomes
        assert idea.rationale
        assert idea.sizing is not None


def _fake_live_chain():
    base = providers.build_synthetic_chain(
        "ABC", 100.0, 0.25, expiries_dte=(35, 40, 60), n_strikes=61, strike_step_pct=0.01
    )
    quotes = [replace(q, open_interest=500, volume=200, status="ok", source="cboe") for q in base.quotes]
    return replace(base, quotes=quotes, data_mode="live_chain", source="cboe")


def test_live_chain_allows_proceed_and_orders_by_label(monkeypatch):
    live = _fake_live_chain()
    monkeypatch.setattr(providers, "get_chain", lambda *a, **k: live)
    ideas, mode, _ = service.advise_symbol(
        "ABC", rules=load_rules(), aum=1_000_000, held_qty=100, fetch_realized=False
    )
    assert mode == "live_chain"
    assert any(i.label == "PROCEED" for i in ideas)
    assert all(i.data_status == "chain_validated" for i in ideas)
    order = {"PROCEED": 0, "MONITOR": 1, "REJECT": 2}
    ranks = [order[i.label] for i in ideas]
    assert ranks == sorted(ranks)  # PROCEED first, then MONITOR, then REJECT


def test_regime_gate_suppresses_income_when_risk_on(monkeypatch):
    live = _fake_live_chain()
    monkeypatch.setattr(providers, "get_chain", lambda *a, **k: live)
    ideas, _, _ = service.advise_symbol(
        "ABC", rules=load_rules(), aum=1_000_000, held_qty=100,
        regime_label="Goldilocks", regime_confidence="High", fetch_realized=False,
    )
    # Goldilocks:High is in suppress_income_when → no covered call / CSP
    assert not [i for i in ideas if i.category == "INCOME"]
