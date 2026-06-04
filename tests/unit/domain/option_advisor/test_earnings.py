"""Earnings feed → EventRisk: pure core, coercion, wiring, filter activation.

All hermetic — the only yfinance touch point (``_yf_earnings_dates``) is
monkeypatched so nothing hits the network.
"""

from __future__ import annotations

import datetime as _dt

from dataclasses import replace

from market_helper.domain.option_advisor import earnings, filters, ranking, signals, structures
from market_helper.domain.option_advisor.contracts import EventRisk
from market_helper.domain.option_advisor.providers import build_synthetic_chain
from market_helper.domain.option_advisor.service import run_advisor


def _chain(dte=40):
    return build_synthetic_chain("ABC", 100.0, 0.25, expiries_dte=(dte,), n_strikes=41, strike_step_pct=0.02)


# --------------------------------------------------------------------------- #
# Pure core: event_risk_from_dates
# --------------------------------------------------------------------------- #


def test_event_risk_from_dates_picks_nearest_future():
    today = _dt.date(2026, 6, 4)
    dates = [_dt.date(2026, 5, 1), _dt.date(2026, 7, 15), _dt.date(2026, 10, 2)]
    er = earnings.event_risk_from_dates("ABC", dates, today=today)
    assert er.event_status == "known"
    assert er.next_earnings_date == "2026-07-15"
    assert er.days_to_earnings == (_dt.date(2026, 7, 15) - today).days


def test_event_risk_from_dates_all_past_is_none_status():
    today = _dt.date(2026, 6, 4)
    er = earnings.event_risk_from_dates("ABC", [_dt.date(2026, 1, 1)], today=today)
    assert er.event_status == "none"
    assert er.next_earnings_date is None and er.days_to_earnings is None


def test_event_risk_from_dates_empty_is_none_status():
    er = earnings.event_risk_from_dates("ABC", [], today=_dt.date(2026, 6, 4))
    assert er.event_status == "none"


# --------------------------------------------------------------------------- #
# _to_date coercion
# --------------------------------------------------------------------------- #


class _FakeTimestamp:
    def __init__(self, d):
        self._d = d

    def date(self):
        return self._d


def test_to_date_handles_each_shape():
    d = _dt.date(2026, 7, 15)
    assert earnings._to_date(_dt.datetime(2026, 7, 15, 9, 30)) == d
    assert earnings._to_date(d) == d
    assert earnings._to_date(_FakeTimestamp(d)) == d
    assert earnings._to_date("2026-07-15T00:00:00") == d
    assert earnings._to_date(None) is None
    assert earnings._to_date("not-a-date") is None


# --------------------------------------------------------------------------- #
# fetch_earnings wrapper (yfinance source monkeypatched)
# --------------------------------------------------------------------------- #


def test_fetch_earnings_returns_event_risk(monkeypatch):
    monkeypatch.setattr(earnings, "_yf_earnings_dates", lambda s: [_dt.date(2099, 3, 1)])
    er = earnings.fetch_earnings("ABC")
    assert er is not None and er.event_status == "known" and er.next_earnings_date == "2099-03-01"


def test_fetch_earnings_none_when_empty(monkeypatch):
    monkeypatch.setattr(earnings, "_yf_earnings_dates", lambda s: [])
    assert earnings.fetch_earnings("ABC") is None


def test_fetch_earnings_none_on_error(monkeypatch):
    def boom(_s):
        raise RuntimeError("network down")

    monkeypatch.setattr(earnings, "_yf_earnings_dates", boom)
    assert earnings.fetch_earnings("ABC") is None


# --------------------------------------------------------------------------- #
# signals.build_context wiring
# --------------------------------------------------------------------------- #


def test_build_context_uses_injected_event_risk():
    injected = EventRisk("ABC", next_earnings_date="2026-07-15", days_to_earnings=41, event_status="known")
    ctx = signals.build_context("ABC", _chain(), fetch_realized=False, event_risk=injected)
    assert ctx.event_risk is injected


def test_build_context_event_override_date():
    ctx = signals.build_context("ABC", _chain(), fetch_realized=False, event_override_date="2099-01-15")
    assert ctx.event_risk is not None
    assert ctx.event_risk.event_status == "known"
    assert ctx.event_risk.next_earnings_date == "2099-01-15"


def test_build_context_no_event_when_flags_off():
    ctx = signals.build_context("ABC", _chain(), fetch_realized=False)
    assert ctx.event_risk is None


def test_build_context_injected_event_risk_beats_override():
    injected = EventRisk("ABC", next_earnings_date="2030-01-01", event_status="known")
    ctx = signals.build_context(
        "ABC", _chain(), fetch_realized=False, event_risk=injected, event_override_date="2099-01-15",
    )
    assert ctx.event_risk is injected  # injected wins over the override date


def test_build_context_bad_override_date_is_ignored():
    ctx = signals.build_context("ABC", _chain(), fetch_realized=False, event_override_date="not-a-date")
    assert ctx.event_risk is None


# --------------------------------------------------------------------------- #
# Filter activation: a known earnings inside the trade fails the soft event check
# --------------------------------------------------------------------------- #


def test_event_filter_flags_earnings_within_trade():
    chain = _chain(40)
    ctx = signals.build_context(
        "ABC", chain, fetch_realized=False,
        event_risk=EventRisk("ABC", "2026-07-01", days_to_earnings=5, event_status="known"),
    )
    idea = structures.build_call_spread(chain, ctx, long_delta=0.45, short_delta=0.25, dte=40)
    fos, _ = filters.evaluate(idea, ctx, {"filters": {}})
    ev = next(f for f in fos if f.filter_name == "event_risk")
    assert ev.passed is False  # earnings in 5d is within the ~40DTE trade → flagged


def test_event_filter_passes_earnings_beyond_trade():
    chain = _chain(40)
    ctx = signals.build_context(
        "ABC", chain, fetch_realized=False,
        event_risk=EventRisk("ABC", "2027-01-01", days_to_earnings=200, event_status="known"),
    )
    idea = structures.build_call_spread(chain, ctx, long_delta=0.45, short_delta=0.25, dte=40)
    fos, _ = filters.evaluate(idea, ctx, {"filters": {}})
    ev = next(f for f in fos if f.filter_name == "event_risk")
    assert ev.passed is True  # earnings 200d out is beyond the trade


# --------------------------------------------------------------------------- #
# Service: per-symbol earnings override flows onto every idea (no network)
# --------------------------------------------------------------------------- #


def test_run_advisor_earnings_override_flows_to_ideas():
    result = run_advisor(
        ["ABC"],
        overrides={"ABC": {"spot": 100.0, "iv": 0.25, "earnings": "2099-03-15"}},
        fetch_realized=False,
    )
    assert result.ideas
    for idea in result.ideas:
        assert idea.event_risk is not None
        assert idea.event_risk.event_status == "known"
        assert idea.event_risk.next_earnings_date == "2099-03-15"


# --------------------------------------------------------------------------- #
# Ranking event-safety: a known earnings inside the trade penalizes the score
# --------------------------------------------------------------------------- #


def _idea():
    chain = _chain(40)
    ctx = signals.build_context("ABC", chain, fetch_realized=False)
    return structures.build_call_spread(chain, ctx, long_delta=0.45, short_delta=0.25, dte=40)


def test_event_safety_penalizes_near_earnings():
    idea = _idea()
    near = replace(idea, event_risk=EventRisk("ABC", "x", days_to_earnings=5, event_status="known"))
    far = replace(idea, event_risk=EventRisk("ABC", "x", days_to_earnings=30, event_status="known"))
    none = replace(idea, event_risk=EventRisk("ABC", event_status="none"))
    assert ranking.score_components(near)[0]["event_penalty"] == 0.5
    assert ranking.score_components(far)[0]["event_penalty"] == 0.9
    assert ranking.score_components(none)[0]["event_penalty"] == 1.0
