"""Futures roll & carry calendar: month parsing + GSCI/expiry roll targets (no network)."""

from __future__ import annotations

import datetime as dt

from market_helper.domain.portfolio_monitor.services.futures_roll_calendar import (
    compute_futures_roll,
    parse_contract_month,
)


def _fut(root, contract, exchange="X", qty=1.0):
    return {"root": root, "contract": contract, "exchange": exchange, "qty": qty}


def test_parse_contract_month():
    assert parse_contract_month("NG", "NGQ26") == (2026, 8)
    assert parse_contract_month("NG", "Q26") == (2026, 8)
    assert parse_contract_month("ZN", "ZNH26") == (2026, 3)
    assert parse_contract_month("ZN", "10Y US") is None   # financial, no month code
    assert parse_contract_month("NG", "NG") is None        # root only, no contract month


def test_gsci_rolls_in_prior_month():
    [it] = compute_futures_roll([_fut("NG", "NGQ26", "NYMEX")], today=dt.date(2026, 7, 1))
    assert it.schedule == "gsci"
    assert it.delivery_label == "Aug 2026"
    assert it.roll_target == "2026-07-07"   # prior month (Jul) of an Aug delivery, ~day 7
    assert it.label == "MONITOR"            # 6 days out → within the window, not yet urgent


def test_gsci_urgent_when_target_imminent():
    [it] = compute_futures_roll([_fut("NG", "NGQ26")], today=dt.date(2026, 7, 6))
    assert it.label == "PROCEED"            # 1 day to the roll target


def test_expiry_schedule_uses_lead_days():
    [it] = compute_futures_roll([_fut("ZN", "ZNH26", "CBOT")], today=dt.date(2026, 2, 1))
    assert it.schedule == "expiry"
    assert it.roll_target == "2026-02-15"   # Mar-1 delivery anchor minus 14 lead days
    assert it.label == "MONITOR"


def test_unparseable_contract_is_info():
    [it] = compute_futures_roll([_fut("ZN", "10Y US", "CBOT")], today=dt.date(2026, 1, 1))
    assert it.label == "INFO"
    assert it.days_to_roll is None
    assert "forward curve" in it.note  # honest about the missing F1/F7 carry feed
