"""Premium value screen — the variance-risk-premium (IV/RV) ranking for INCOME.

Research basis: docs/architecture/devplans/option_advisor.md "Premium value screen".
The edge in selling premium is the VRP (implied vol > realized vol); equal yield with
richer VRP should rank higher, and a premium that is cheap vs realized is poor value.
"""

from __future__ import annotations

import pytest

from market_helper.domain.option_advisor.config import load_rules
from market_helper.domain.option_advisor.contracts import (
    CATEGORY_INCOME,
    OptionIdea,
    OptionLeg,
)
from market_helper.domain.option_advisor.ranking import _efficiency, rank_and_label

_PREMIUM_CFG = load_rules(None)["premium_screen"]


def _income_idea(idea_id: str, under_iv, under_rv, *, credit=200.0, max_loss=9800.0, dte=35) -> OptionIdea:
    leg = OptionLeg(
        right="P", action="sell", strike_rule="delta:0.27", expiry_rule="dte:35",
        resolved_strike=100.0, resolved_dte=dte, quote_status="live",
    )
    return OptionIdea(
        idea_id=idea_id, as_of="2026-06-09", underlying_id=idea_id, underlying_symbol="SPY",
        category=CATEGORY_INCOME, structure_type="CASH_SECURED_PUT", legs=[leg],
        est_net_debit_credit=credit, est_max_loss=-max_loss, data_status="chain_validated",
        under_iv=under_iv, under_rv=under_rv,
    )


def test_vrp_ratio_property():
    assert _income_idea("a", 0.30, 0.20).vrp_ratio == pytest.approx(1.5)   # implied 50% over realized
    assert _income_idea("b", 0.20, None).vrp_ratio is None     # no realized vol → undefined
    assert _income_idea("c", 0.20, 0.0).vrp_ratio is None      # guard /0


def test_rich_vrp_outranks_cheap_vrp_at_equal_yield():
    rich = _income_idea("rich", under_iv=0.30, under_rv=0.20)   # VRP 1.5x
    cheap = _income_idea("cheap", under_iv=0.20, under_rv=0.25)  # VRP 0.8x (implied < realized)
    eff_rich, ann_rich = _efficiency(rich, _PREMIUM_CFG)
    eff_cheap, ann_cheap = _efficiency(cheap, _PREMIUM_CFG)
    assert ann_rich == ann_cheap          # identical yield (same credit/loss/dte)
    assert eff_rich > eff_cheap           # but the rich-VRP one screens as better value
    assert eff_cheap == 0.0               # implied ≤ realized → no seller edge

    ranked = rank_and_label([cheap, rich], load_rules(None))
    by_id = {i.idea_id: i for i in ranked}
    assert by_id["rich"].score > by_id["cheap"].score
    assert ranked[0].idea_id == "rich"    # sorted best-value first
    # The VRP read + the researched management note ride in the rationale + drivers.
    assert "VRP IV/RV 1.50x (rich" in by_id["rich"].rationale
    assert "CHEAP vs realized" in by_id["cheap"].rationale
    assert "manage ~21 DTE" in by_id["rich"].rationale
    assert ("vrp_ratio", 1.5) in by_id["rich"].drivers


def test_no_realized_vol_falls_back_to_pure_yield():
    no_rv = _income_idea("x", under_iv=0.30, under_rv=None)
    eff, ann = _efficiency(no_rv, _PREMIUM_CFG)
    # Pure yield: ann / target_yield, clipped — unchanged from the pre-VRP behavior.
    assert eff == min(1.0, ann / _PREMIUM_CFG["target_yield_annualized"])
