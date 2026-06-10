"""Crystallize editor — bounded premium-screen edits that keep the YAML's comments."""

from __future__ import annotations

from market_helper.application.trade_advisor.option_rules import (
    clamp_premium_screen,
    load_premium_screen,
    save_premium_screen,
)

_YAML = """# Option Advisor rules — comments are the research rationale; they must survive.
version: "1"

filters:
  min_premium_over_costs: 1.5    # net credit must clear costs x this

premium_screen:
  # The edge is the VARIANCE RISK PREMIUM (see option_advisor.md §5b).
  target_yield_annualized: 0.40  # annualized credit/capital-at-risk → score 1.0
  vrp_ratio_span: 0.5            # IV/RV − 1 of 0.5 → richness 1.0
  min_vrp_ratio: 1.0            # ≤1 = implied cheaper than realized
  manage_dte: 21
"""


def test_clamp_bounds_and_types():
    out = clamp_premium_screen({
        "target_yield_annualized": 5.0,    # above band → clamped to 2.0
        "vrp_ratio_span": 0.5,             # in band → kept
        "min_vrp_ratio": 0.1,              # below band → clamped to 0.5
        "manage_dte": 21.6,                # int knob → rounded
        "not_a_knob": 99,                  # unknown → dropped
        "bad": "x",
    })
    assert out == {"target_yield_annualized": 2.0, "vrp_ratio_span": 0.5,
                   "min_vrp_ratio": 0.5, "manage_dte": 22}


def test_save_edits_values_in_place_and_keeps_comments(tmp_path):
    p = tmp_path / "advisor_rules.yaml"
    p.write_text(_YAML, encoding="utf-8")

    written = save_premium_screen({"min_vrp_ratio": 1.15, "manage_dte": 18}, path=p)
    assert written == {"min_vrp_ratio": 1.15, "manage_dte": 18}

    text = p.read_text(encoding="utf-8")
    assert "min_vrp_ratio: 1.15" in text
    assert "manage_dte: 18" in text
    # The research comments and untouched keys survive byte-for-byte.
    assert "# The edge is the VARIANCE RISK PREMIUM" in text
    assert "# ≤1 = implied cheaper than realized" in text          # trailing comment kept
    assert "target_yield_annualized: 0.40" in text                  # untouched knob unchanged
    assert "min_premium_over_costs: 1.5    # net credit" in text    # other blocks untouched

    # And the effective rules reflect the edit.
    ps = load_premium_screen(p)
    assert ps["min_vrp_ratio"] == 1.15 and ps["manage_dte"] == 18


def test_save_appends_missing_block(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text("version: '1'\n", encoding="utf-8")
    save_premium_screen({"min_vrp_ratio": 1.2}, path=p)
    ps = load_premium_screen(p)
    assert ps["min_vrp_ratio"] == 1.2
    assert ps["manage_dte"] == 21                                   # defaults still merge underneath


def test_save_nothing_valid_is_a_noop(tmp_path):
    p = tmp_path / "rules.yaml"
    p.write_text(_YAML, encoding="utf-8")
    assert save_premium_screen({"junk": 1}, path=p) == {}
    assert p.read_text(encoding="utf-8") == _YAML                   # file untouched
