"""Trade Advisor page: pure-helper correctness + route registration."""

from __future__ import annotations

from market_helper.presentation.dashboard.pages import trade_advisor as ta


def test_build_context_maps_held_and_watchlist():
    inp = ta.AdvisorInputs(symbols=["SPY", "QQQ", "NVDA"], held=["SPY", "TSLA"], aum=300_000)
    ctx = ta.build_context(inp)
    # held ∩ universe → 100 sh each; TSLA not in symbols so dropped
    assert ctx.holdings == {"SPY": 100.0}
    assert ctx.watchlist == ["QQQ", "NVDA"]
    assert ctx.aum == 300_000
    assert ctx.symbols() == ["SPY", "QQQ", "NVDA"]


def test_option_run_params_passthrough():
    params = ta.option_run_params(ta.AdvisorInputs(fetch_realized=True, check_earnings=True))
    assert params == {"option": {"fetch_realized": True, "fetch_events": True}}


def test_payoff_figure_from_curve():
    detail = {"est_payoff_curve": [[90.0, -500.0], [100.0, 0.0], [110.0, 500.0]], "est_breakevens": [100.0]}
    fig = ta.payoff_figure(detail)
    assert len(fig.data) >= 1
    assert list(fig.data[0].x) == [90.0, 100.0, 110.0]
    assert list(fig.data[0].y) == [-500.0, 0.0, 500.0]


def test_num_and_pct_helpers():
    assert ta._num(None) == "—"
    assert ta._num("") == "—"
    assert ta._num(3, "+d") == "+3"            # int spec on a float-able value
    assert ta._num(3.0, "+d") == "+3"
    assert ta._num(375000.0, ",.0f") == "375,000"
    assert ta._num(0.45, "+.3f") == "+0.450"
    assert ta._num("n/a") == "n/a"             # non-numeric passes through
    assert ta._pct(0.039) == "3.90"
    assert ta._pct(None) == "—"


def test_fx_alloc_table_formats_legs():
    detail = {
        "fx_legs": [
            {"currency": "EUR", "instrument": "6E", "beta": 0.45, "target_contracts": 3,
             "target_notional_usd": 375000.0, "carry_bps": -12.0, "on_rate": 0.039, "expiry": "2026-09-15"},
        ],
        "totals": {"expected_annual_carry_bps": -8},
    }
    headers, rows = ta.fx_alloc_table(detail)
    assert headers[0] == "Ccy" and "Contracts" in headers
    assert rows == [["EUR", "6E", "+0.450", "+3", "375,000", "-12", "3.90", "2026-09-15"]]


def test_fx_alloc_table_empty_when_no_legs():
    headers, rows = ta.fx_alloc_table({})
    assert headers and rows == []


def test_fx_carry_table_formats_ranking():
    detail = {"ranking": [{"currency": "EUR", "carry_bps": -12.3, "on_rate": 0.039},
                          {"currency": "JPY", "carry_bps": -40.0, "on_rate": 0.001}]}
    headers, rows = ta.fx_carry_table(detail)
    assert headers == ["Ccy", "Carry bps", "ON %"]
    assert rows == [["EUR", "-12", "3.90"], ["JPY", "-40", "0.10"]]


def test_roll_facts_short_itm():
    detail = {"underlying": "AAPL", "right": "C", "strike": 190.0, "expiry": "2026-07-17",
              "qty": -1.0, "dte": 12, "itm": True, "underlying_price": 195.2}
    facts = dict(ta.roll_facts(detail))
    assert facts["Underlying"] == "AAPL"
    assert facts["Contract"] == "short C190 2026-07-17"
    assert facts["Quantity"] == "-1"
    assert facts["DTE"] == "12d"
    assert facts["Moneyness"] == "ITM"
    assert facts["Underlying px"] == "195.2"


def test_roll_facts_handles_missing_expiry_and_itm():
    facts = dict(ta.roll_facts({"underlying": "MSFT", "right": "P", "strike": 400.0, "qty": 1.0}))
    assert facts["DTE"] == "—" and facts["Moneyness"] == "—"
    assert facts["Contract"].startswith("long P400")


def test_option_legs_lines():
    detail = {"legs": [{"action": "sell", "right": "C", "resolved_strike": 110.0,
                        "est_price": 2.5, "resolved_dte": 35}]}
    lines = ta.option_legs_lines(detail)
    assert lines == ["SELL C110.0 @ 2.5 (35DTE)"]


def test_register_is_idempotent_and_registers_route():
    from nicegui import app as nicegui_app

    ta.register_trade_advisor_page()
    ta.register_trade_advisor_page()  # idempotent — must not raise
    paths = {getattr(r, "path", None) for r in nicegui_app.routes}
    assert "/advisor" in paths
