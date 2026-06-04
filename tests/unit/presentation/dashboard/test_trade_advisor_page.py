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


def test_register_is_idempotent_and_registers_route():
    from nicegui import app as nicegui_app

    ta.register_trade_advisor_page()
    ta.register_trade_advisor_page()  # idempotent — must not raise
    paths = {getattr(r, "path", None) for r in nicegui_app.routes}
    assert "/advisor" in paths
