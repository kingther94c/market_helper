"""v2 cockpit module builders — the pure logic behind each module surface.

Roll & Carry (no-run calendar), FX Hedge (decision panel), and the option
universe loader are exercised here so the thin ``ui.*`` wrappers can stay untested.
"""

from __future__ import annotations

from types import SimpleNamespace

from market_helper.presentation.dashboard.pages.trade_advisor.inputs import load_option_universe
from market_helper.presentation.dashboard.pages.trade_advisor.modules import fx_hedge as fx_mod
from market_helper.presentation.dashboard.pages.trade_advisor.modules import option as opt_mod
from market_helper.presentation.dashboard.pages.trade_advisor.modules import roll as roll_mod
from market_helper.trade_advisor.contracts import AdvisorContext, LABEL_RESEARCH_READY, Suggestion


# --------------------------------------------------------------------------- #
# Roll & Carry Calendar
# --------------------------------------------------------------------------- #


def _roll_context() -> AdvisorContext:
    return AdvisorContext(
        as_of="2026-06-03",
        held_options=[
            {"underlying": "SPY", "right": "C", "strike": 740, "expiry": "2026-06-08",
             "qty": -1, "underlying_price": 759.0},  # short ITM, 5 DTE → "Roll now"
        ],
        held_futures=[
            {"root": "NG", "contract": "NGQ26", "exchange": "NYMEX", "asset_class": "CM",
             "qty": -1, "latest_price": 3.5, "market_value": -3500.0},
        ],
    )


def test_build_roll_rows_sorts_urgent_first():
    rows = roll_mod.build_roll_rows(_roll_context(), today="2026-06-03")
    kinds = {r["kind"] for r in rows}
    assert kinds == {"Option", "Future"}          # both held legs surfaced
    assert rows[0]["kind"] == "Option"            # the urgent short-ITM option ranks first
    assert rows[0]["urgency"] == "Roll now"
    spy = next(r for r in rows if r["subject"] == "SPY")
    assert spy["label"] == LABEL_RESEARCH_READY and spy["to_roll"] == "5d"
    ng = next(r for r in rows if r["subject"] == "NG")
    assert ng["schedule"] == "GSCI-like"


def test_build_roll_rows_empty_book():
    assert roll_mod.build_roll_rows(AdvisorContext(as_of="2026-06-03")) == []


def test_roll_calendar_table_shape():
    rows = roll_mod.build_roll_rows(_roll_context(), today="2026-06-03")
    headers, trows = roll_mod.roll_calendar_table(rows)
    assert headers == ["Type", "Subject", "Instrument", "Urgency", "To roll", "Schedule"]
    assert len(trows) == len(rows) and all(len(r) == len(headers) for r in trows)


def test_commodity_carry_placeholder_is_honest():
    ph = roll_mod.commodity_carry_placeholder()
    assert "GSCI" in ph["body"] and "F1/F7" in ph["body"]
    assert "forward curve" in ph["blocked_on"]      # names the data gap, doesn't fabricate basis


# --------------------------------------------------------------------------- #
# FX Hedge decision panel
# --------------------------------------------------------------------------- #


def _leg(ccy, beta, contracts, notional, carry, on_rate):
    return SimpleNamespace(
        currency=ccy, instrument="6" + ccy[0], beta=beta, target_contracts=contracts,
        target_notional_usd=notional, expected_annual_carry_usd=carry, on_rate=on_rate, expiry="2026-09-16",
    )


def _fx_state():
    alloc = SimpleNamespace(
        run_date="2026-06-03", hedge_target_pair="USD/SGD", hedge_notional_usd=1_000_000.0,
        hedge_notional_source="config", totals={"expected_annual_carry_bps": 35.0},
        regression={"r_squared": 0.88},
        legs=[_leg("AUD", 0.30, 4, 400_000, 14000, 0.035), _leg("JPY", 0.10, 1, 100_000, -200, 0.001)],
    )
    return SimpleNamespace(allocation=alloc, computed_fresh=False, age_days=5,
                           source_label="cache", error_message=None)


def test_build_fx_panel_from_allocation():
    panel = fx_mod.build_fx_panel(provider=lambda **k: _fx_state())
    assert panel["available"] is True
    mix_headers, mix_rows = panel["mix"]
    assert mix_headers[0] == "Ccy" and len(mix_rows) == 2
    assert mix_rows[0][0] == "AUD"                       # leg currency in column 0
    # The carry → tilt section has a before/after read.
    assert fx_mod.fx_tilt_summary(panel)


def test_build_fx_panel_missing_allocation():
    state = SimpleNamespace(allocation=None, error_message="no artifact")
    panel = fx_mod.build_fx_panel(provider=lambda **k: state)
    assert panel["available"] is False


def test_fx_exposure_placeholder_is_honest():
    ph = fx_mod.fx_exposure_placeholder()
    assert "lookthrough" in ph["body"] and "fabricated" in ph["body"]   # no fake exposure number


# --------------------------------------------------------------------------- #
# Option universe loader (security_universe.csv wiring)
# --------------------------------------------------------------------------- #


def test_load_option_universe_filters(tmp_path):
    csv = tmp_path / "u.csv"
    csv.write_text(
        "asset_class,sec_type,ibkr_symbol,yahoo_symbol\n"
        "EQ,STK,SPY,SPY\n"
        "EQ,STK,SPYL,SPYL.L\n"      # London listing → dropped (no US option chain)
        "FI,STK,TLT,TLT\n"          # not EQ → dropped
        "EQ,FUT,ES,ES\n",           # not STK → dropped
        encoding="utf-8",
    )
    out = load_option_universe(path=csv)
    assert out == ["SPY"]


def test_load_option_universe_falls_back(tmp_path):
    bad = tmp_path / "missing.csv"
    out = load_option_universe(path=bad)
    assert "SPY" in out and "QQQ" in out      # falls back to LIQUID_UNIVERSE


def _opt_sug(category: str, sid: str) -> Suggestion:
    return Suggestion(advisor="option", suggestion_id=sid, as_of="2026-06-09",
                      title=sid, subject="X", category=category)


def test_partition_option_ideas_splits_into_two_screens():
    sugs = [_opt_sug("HEDGE", "h1"), _opt_sug("INCOME", "i1"),
            _opt_sug("INCOME", "i2"), _opt_sug("DIRECTIONAL", "d1")]
    groups = opt_mod.partition_option_ideas(sugs)
    assert "Hedge" in groups[0][0] and "Income" in groups[1][0] and "Other" in groups[2][0]
    assert [s.suggestion_id for s in groups[0][1]] == ["h1"]        # collar/hedge screen
    assert [s.suggestion_id for s in groups[1][1]] == ["i1", "i2"]  # premium/income screen
    assert [s.suggestion_id for s in groups[2][1]] == ["d1"]        # other structures
    assert groups[2][2] == ""                                       # 'Other' hidden when empty (no note)
