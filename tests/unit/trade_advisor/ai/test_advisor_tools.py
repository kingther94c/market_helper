"""Cross-module AI tools — the AI sees what the modules see (read-only, cached)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from market_helper.trade_advisor.ai.advisor_tools import (
    build_advisor_tool_registry,
    register_advisor_tools,
)
from market_helper.trade_advisor.ai.tools import AiToolRegistry

_NEW_TOOLS = {"get_portfolio_book", "get_fx_decision", "get_roll_yields", "get_option_scan"}


def test_register_adds_the_four_cross_module_tools():
    reg = register_advisor_tools(AiToolRegistry())
    assert set(reg.keys()) == _NEW_TOOLS
    assert all(t.read_only for t in reg.all())          # the registry invariant holds


def test_full_registry_merges_tactical_and_cross_module():
    reg = build_advisor_tool_registry()
    keys = set(reg.keys())
    assert _NEW_TOOLS <= keys
    # The tactical research tools ride along (shared set for every pane).
    assert {"get_regime_snapshot", "get_price_trend", "get_tactical_edge"} <= keys


def test_get_portfolio_book_dispatch(monkeypatch):
    from market_helper import application

    ctx = SimpleNamespace(
        as_of="2026-06-10", aum=500_000.0, holdings={"SPY": 100.0},
        held_options=[{"underlying": "SPY", "right": "C", "strike": 620.0,
                       "expiry": "2026-06-18", "qty": -1.0, "iv": 0.2}],
        held_futures=[{"root": "NG", "contract": "NGQ26", "exchange": "NYMEX",
                       "qty": -1.0, "market_value": -32300.0, "latest_price": 3.23}],
    )
    monkeypatch.setattr(application.trade_advisor, "context_from_positions_csv", lambda: ctx)
    reg = register_advisor_tools(AiToolRegistry())
    out = json.loads(reg.dispatch("get_portfolio_book", {}))
    assert out["funded_aum_usd"] == 500_000.0
    assert out["holdings_shares"] == {"SPY": 100.0}
    assert out["held_options"][0]["strike"] == 620.0 and "iv" not in out["held_options"][0]
    assert out["held_futures"][0]["market_value"] == -32300.0   # signed notional rides along
    assert "excludes options/futures" in out["note"]            # the sizing gotcha is stated


def test_get_fx_decision_dispatch(monkeypatch):
    from market_helper.application.trade_advisor import fx_decision as fxmod

    decision = {
        "available": True, "data_mode": "cached_5d",
        "rows": [{"ccy": "AUD", "book_usd": 499547.0, "book_w": 0.12, "cur_qty": 7.0,
                  "cur_usd": 493206.0, "tgt_ct": 2, "tgt_usd": 171842.0,
                  "gap_ct": -5.0, "gap_usd": -321364.0}],
        "at_target": [("USD", 2_800_000.0, 0.68)],
        "note": "read-only",
    }
    monkeypatch.setattr(fxmod, "fx_decision_from_book", lambda: decision)
    reg = register_advisor_tools(AiToolRegistry())
    out = json.loads(reg.dispatch("get_fx_decision", {}))
    assert out["available"] is True
    assert out["rows"][0]["gap_ct"] == -5.0                     # the actionable distance survives
    assert "book_w" not in out["rows"][0]                       # trimmed to the model-facing fields
    assert out["at_target_mix"] == [{"ccy": "USD", "weight": 0.68}]


def test_get_roll_yields_absent_is_honest(monkeypatch):
    from market_helper.application.trade_advisor import roll_carry

    monkeypatch.setattr(roll_carry, "load_roll_yields", lambda: None)
    reg = register_advisor_tools(AiToolRegistry())
    out = json.loads(reg.dispatch("get_roll_yields", {}))
    assert out["available"] is False and "Fetch quotes" in out["note"]   # never fetches itself


def test_get_roll_yields_splits_ok_and_skipped(monkeypatch):
    from market_helper.application.trade_advisor import roll_carry

    payload = {"fetched_at": "2026-06-10T20:27:15", "age_hours": 1.25, "rows": [
        {"root": "NG", "held_contract": "NGQ26", "next_contract": "NGU26",
         "roll_yield_ann": 0.1015, "curve": "backwardation", "status": "ok"},
        {"root": "ZN", "held_contract": "10Y US", "status": "skipped", "note": "no month code"},
    ]}
    monkeypatch.setattr(roll_carry, "load_roll_yields", lambda: payload)
    reg = register_advisor_tools(AiToolRegistry())
    out = json.loads(reg.dispatch("get_roll_yields", {}))
    assert out["available"] is True and out["age_hours"] == 1.2
    assert out["rows"][0]["curve"] == "backwardation"
    assert out["skipped"] == [{"root": "ZN", "held": "10Y US", "why": "no month code"}]


def test_get_option_scan_summarizes(monkeypatch):
    from market_helper import application
    from market_helper.trade_advisor.contracts import Suggestion

    saved = {
        "saved_at": "2026-06-10T09:30:00", "as_of": "2026-06-10", "data_mode": "live_chain",
        "inputs": {"use_portfolio": True}, "warnings": [],
        "suggestions": [Suggestion(
            advisor="option", suggestion_id="x", as_of="2026-06-10",
            title="COVERED_CALL · SPY", subject="SPY", category="INCOME",
            label="WATCHLIST", score=0.71, thesis="Sell the 35d call." * 20,
            headline_metrics={"yield": "38%/yr", "IV/RV": "1.31x", "net": "credit 412"},
        )],
    }
    monkeypatch.setattr(application.trade_advisor, "load_option_scan", lambda: saved)
    reg = register_advisor_tools(AiToolRegistry())
    out = json.loads(reg.dispatch("get_option_scan", {}))
    assert out["available"] is True and out["n_ideas"] == 1
    idea = out["ideas"][0]
    assert idea["structure"] == "COVERED_CALL" and idea["iv_rv"] == "1.31x"
    assert len(idea["thesis"]) <= 160                            # summarized, not dumped

    monkeypatch.setattr(application.trade_advisor, "load_option_scan", lambda: None)
    out = json.loads(register_advisor_tools(AiToolRegistry()).dispatch("get_option_scan", {}))
    assert out["available"] is False and "run the Option Strategy scan" in out["note"]
