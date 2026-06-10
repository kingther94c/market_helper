"""Two-contract roll yield — next-liquid resolution, Yahoo symbols, carry math."""

from __future__ import annotations

import math

import pytest

from market_helper.domain.portfolio_monitor.services.futures_roll_calendar import (
    FuturesRollConfig,
)
from market_helper.domain.portfolio_monitor.services.futures_roll_yield import (
    annualized_roll_yield,
    compute_roll_yields,
    liquid_months_for,
    next_liquid_contract,
    yahoo_contract_symbol,
)

_CFG = FuturesRollConfig(roots={"NG": {"schedule": "gsci"}, "ZN": {"schedule": "expiry"}})


def test_liquid_months_by_schedule_and_override():
    assert liquid_months_for("NG", _CFG) == "FGHJKMNQUVXZ"     # GSCI commodity → monthly
    assert liquid_months_for("ZN", _CFG) == "HMUZ"             # financial → quarterly
    cfg = FuturesRollConfig(roots={"CL": {"liquid_months": "GJMQVZ"}})
    assert liquid_months_for("CL", cfg) == "GJMQVZ"            # explicit cycle wins


def test_next_liquid_contract_monthly_and_quarterly():
    assert next_liquid_contract("NG", "NGQ26", "FGHJKMNQUVXZ") == ("NGU26", 2026, 9)
    assert next_liquid_contract("ZN", "ZNZ26", "HMUZ") == ("ZNH27", 2027, 3)   # year wrap
    assert next_liquid_contract("NG", "10Y US", "FGHJKMNQUVXZ") is None        # no month code → never guessed


def test_yahoo_contract_symbol_mapping():
    assert yahoo_contract_symbol("NG", "NGU26", "NYMEX") == "NGU26.NYM"
    assert yahoo_contract_symbol("ZN", "ZNH27", "CBOT") == "ZNH27.CBT"
    assert yahoo_contract_symbol("X", "XF26", "EUREX") is None                 # unmapped exchange → skip


def test_annualized_roll_yield_sign_convention():
    # Backwardation: held (front) above next → positive (the roll pays a long).
    up = annualized_roll_yield(4.0, 3.8, (2026, 8), (2026, 9))
    assert up == pytest.approx(math.log(4.0 / 3.8) * 365 / 31)
    assert up > 0
    # Contango: held below next → negative.
    assert annualized_roll_yield(3.2, 3.4, (2026, 8), (2026, 9)) < 0
    assert annualized_roll_yield(0.0, 3.4, (2026, 8), (2026, 9)) is None       # bad quote → None


def test_compute_roll_yields_quotes_and_skips():
    quotes = {"NGQ26.NYM": 3.23, "NGU26.NYM": 3.40}
    held = [
        {"root": "NG", "contract": "NGQ26", "exchange": "NYMEX", "qty": -1},
        {"root": "NG", "contract": "NGQ26", "exchange": "NYMEX", "qty": 2},    # dup → quoted once
        {"root": "ZN", "contract": "10Y US", "exchange": "CBOT", "qty": 1},    # no month code → skipped
        {"root": "NG", "contract": "NGG27", "exchange": "NYMEX", "qty": 1},    # no quote for next
    ]
    calls: list[str] = []

    def fetcher(sym: str):
        calls.append(sym)
        return quotes.get(sym)

    rows = compute_roll_yields(held, config=_CFG, fetcher=fetcher)
    by = {(r["root"], r["held_contract"]): r for r in rows}

    ok = by[("NG", "NGQ26")]
    assert ok["status"] == "ok" and ok["next_contract"] == "NGU26"
    assert ok["curve"] == "contango" and ok["roll_yield_ann"] < 0              # 3.23 < 3.40
    assert calls.count("NGQ26.NYM") == 1                                       # de-duplicated quote

    assert by[("ZN", "10Y US")]["status"] == "skipped"                         # honest skip + reason
    assert "month code" in by[("ZN", "10Y US")]["note"]
    assert by[("NG", "NGG27")]["status"] == "no_quote"


def test_compute_roll_yields_fetcher_error_degrades_row():
    def boom(_sym: str):
        raise RuntimeError("rate limited")

    rows = compute_roll_yields(
        [{"root": "NG", "contract": "NGQ26", "exchange": "NYMEX", "qty": 1}],
        config=_CFG, fetcher=boom,
    )
    assert rows[0]["status"] == "no_quote"                                     # degraded, not raised
