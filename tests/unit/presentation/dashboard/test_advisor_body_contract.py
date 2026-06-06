"""Adapter → page body contract.

Each advisor's real ``Suggestion.detail`` must drive its dedicated body
renderer's pure builder. This pins the coupling between an adapter's detail keys
and the page builders — rename ``fx_legs``/``ranking``/a roll key and a test here
fails loudly instead of the body silently rendering empty.
"""

from __future__ import annotations

from types import SimpleNamespace

from market_helper.presentation.dashboard.pages.trade_advisor import cards as ta_cards
from market_helper.trade_advisor.adapters.fx_hedge import FxHedgeAdvisorPlugin
from market_helper.trade_advisor.adapters.option import OptionAdvisorPlugin
from market_helper.trade_advisor.adapters.roll import RollReminderPlugin
from market_helper.trade_advisor.contracts import AdvisorContext


def _leg(ccy, beta, contracts, notional, carry, on_rate):
    return SimpleNamespace(
        currency=ccy, instrument="6" + ccy[0], beta=beta, target_contracts=contracts,
        target_notional_usd=notional, expected_annual_carry_usd=carry, on_rate=on_rate, expiry="2026-09-16",
    )


def _fx_suggestions():
    alloc = SimpleNamespace(
        run_date="2026-06-03", hedge_target_pair="USD/SGD", hedge_notional_usd=1_000_000.0,
        hedge_notional_source="config", totals={"expected_annual_carry_bps": 35.0},
        regression={"r_squared": 0.88},
        legs=[_leg("EUR", 0.40, 3, 400_000, 6000, 0.025), _leg("JPY", 0.10, 1, 100_000, -200, 0.001)],
    )
    state = SimpleNamespace(
        allocation=alloc, computed_fresh=False, age_days=5, source_label="cache", error_message=None,
    )
    return FxHedgeAdvisorPlugin().produce(AdvisorContext(as_of="2026-06-03"), provider=lambda **k: state).suggestions


def test_fx_alloc_detail_drives_alloc_table():
    s = next(x for x in _fx_suggestions() if x.body_kind == "fx_alloc")
    headers, rows = ta_cards.fx_alloc_table(s.detail)
    assert len(rows) == 2          # one row per hedge leg
    assert rows[0][0] == "EUR"     # currency first column
    assert headers[3] == "Contracts"


def test_fx_carry_detail_drives_carry_table():
    s = next(x for x in _fx_suggestions() if x.body_kind == "fx_carry")
    headers, rows = ta_cards.fx_carry_table(s.detail)
    assert rows and rows[0][0] == "EUR"   # ranked top-carry first


def test_roll_detail_drives_roll_facts():
    held = [{"underlying": "SPY", "right": "C", "strike": 740, "expiry": "2026-06-08",
             "qty": -1, "underlying_price": 759.0}]
    s = RollReminderPlugin().produce(
        AdvisorContext(as_of="2026-06-03", held_options=held), today="2026-06-03"
    ).suggestions[0]
    facts = dict(ta_cards.roll_facts(s.detail))
    assert facts["Underlying"] == "SPY" and facts["Moneyness"] == "ITM"
    assert facts["Contract"].startswith("short C740")


def test_option_detail_drives_option_body_helpers():
    res = OptionAdvisorPlugin().produce(
        AdvisorContext(as_of="2026-06-03", holdings={"NVDA": 100.0}, aum=500_000.0),
        overrides={"NVDA": {"spot": 120.0, "iv": 0.45}}, fetch_realized=False,
    )
    s = res.suggestions[0]
    assert ta_cards.option_legs_lines(s.detail)                 # ≥1 readable leg line
    assert "spot" in s.detail and "iv_skew" in s.detail   # what-if inputs are present
