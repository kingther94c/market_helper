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
    assert headers == ["Type", "Subject", "Instrument", "Urgency", "To roll", "Roll date", "Schedule"]
    assert len(trows) == len(rows) and all(len(r) == len(headers) for r in trows)
    date_col = headers.index("Roll date")
    spy = next(r for r in trows if r[1] == "SPY")
    assert spy[date_col] == "2026-06-08"            # option roll date = its expiry
    ng = next(r for r in trows if r[1] == "NG")
    assert ng[date_col] == "2026-07-07"             # GSCI-like prior-month target (Jul 7)


def test_roll_yield_table_formats_ok_and_skipped():
    rows = [
        {"root": "NG", "held_contract": "NGQ26", "next_contract": "NGU26",
         "held_px": 3.23, "next_px": 3.40, "roll_yield_ann": -0.602, "curve": "contango", "status": "ok"},
        {"root": "ZN", "held_contract": "10Y US", "status": "skipped",
         "note": "no month code on the position — cannot identify the curve point"},
    ]
    headers, trows = roll_mod.roll_yield_table(rows)
    assert headers[-2] == "Roll yield (ann)"
    assert trows[0][5] == "-60.2%" and trows[0][6] == "contango"
    assert "no month code" in trows[1][6]           # skips carry their reason, never vanish


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


def _decision_inputs():
    panel = {
        "available": True,
        "legs_raw": [
            {"currency": "AUD", "target_contracts": 4, "target_notional_usd": 400_000.0},
            {"currency": "CNH", "target_contracts": 1, "target_notional_usd": 100_000.0},
        ],
    }
    exposure = {
        "available": True,
        "by_currency": [("USD", 700_000.0, 0.7), ("AUD", 200_000.0, 0.2), ("CNY", 100_000.0, 0.1)],
        "fx_overlay_by_currency": {"AUD": {"usd": 200_000.0, "qty": 3.0}},
    }
    return panel, exposure


def test_build_fx_decision_joins_target_vs_held():
    panel, exposure = _decision_inputs()
    d = fx_mod.build_fx_decision(panel, exposure)
    assert d["available"] is True
    by = {r["ccy"]: r for r in d["rows"]}
    aud = by["AUD"]
    assert aud["cur_qty"] == 3.0 and aud["cur_usd"] == 200_000.0
    assert aud["tgt_ct"] == 4 and aud["tgt_usd"] == 400_000.0
    assert aud["gap_ct"] == 1.0 and aud["gap_usd"] == 200_000.0        # the actionable distance
    # CNH target leg joins the book's CNY bucket (offshore proxy, documented).
    cny = by["CNY"]
    assert cny["tgt_usd"] == 100_000.0 and cny["cur_usd"] == 0.0 and cny["book_usd"] == 100_000.0
    assert d["rows"][0]["ccy"] == "AUD"                                # sorted by |target| desc


def test_build_fx_decision_at_target_mix_renormalizes():
    panel, exposure = _decision_inputs()
    d = fx_mod.build_fx_decision(panel, exposure)
    at = {c: (usd, w) for c, usd, w in d["at_target"]}
    # AUD: 200k book − 200k held + 400k target = 400k; CNY: 100k + 100k = 200k; USD unchanged.
    assert at["AUD"][0] == 400_000.0 and at["CNY"][0] == 200_000.0 and at["USD"][0] == 700_000.0
    total = 400_000.0 + 200_000.0 + 700_000.0
    assert abs(at["USD"][1] - 700_000.0 / total) < 1e-9
    assert d["at_target"][0][0] == "USD"                               # sorted by size desc
    assert "USD" in fx_mod.at_target_line(d)


def test_build_fx_decision_unavailable_inputs_stay_empty():
    d = fx_mod.build_fx_decision({"available": False}, {"available": True, "by_currency": []})
    assert d["available"] is False and d["rows"] == []                 # never fabricated
    headers, rows = fx_mod.fx_decision_table(d)
    assert rows == [] and headers[0] == "Ccy"


def test_fx_decision_table_formats_signed():
    panel, exposure = _decision_inputs()
    headers, rows = fx_mod.fx_decision_table(fx_mod.build_fx_decision(panel, exposure))
    assert headers == ["Ccy", "Book $", "Book %", "Now ct", "Now $", "Target ct", "Target $", "Δ ct", "Δ $"]
    aud = next(r for r in rows if r[0] == "AUD")
    assert aud[5] == "+4" and aud[7] == "+1" and aud[8] == "+200,000"


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


def test_option_summary_rows_ranked_and_aligned():
    a = Suggestion(advisor="option", suggestion_id="a", as_of="2026-06-10",
                   title="COVERED_CALL · SPY", subject="SPY", category="INCOME",
                   label="WATCHLIST", score=0.6,
                   headline_metrics={"yield": "38%/yr", "IV/RV": "1.31x", "net": "credit 412", "liq": "ok"})
    b = Suggestion(advisor="option", suggestion_id="b", as_of="2026-06-10",
                   title="ZERO_COST_COLLAR · NVDA", subject="NVDA", category="HEDGE",
                   label="RESEARCH_READY", score=0.8, headline_metrics={"net": "credit 0", "@-10%": "-1,200"})
    headers, rows = opt_mod.option_summary_rows([a, b])
    assert len(headers) == len(rows[0]) == len(rows[1])
    assert rows[0][:4] == ["Hedge", "NVDA", "ZERO_COST_COLLAR", "RESEARCH_READY"]  # label rank first
    assert rows[1][0] == "Income" and rows[1][4] == "38%/yr" and rows[1][5] == "1.31x"
    assert rows[0][4] == "—"                                       # missing metric → em dash, not blank
