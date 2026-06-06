"""Provider parsing + synthetic vol-surface fallback (no network)."""

from __future__ import annotations

import pytest

from market_helper.domain.option_advisor.contracts import VolSurfaceParams
from market_helper.domain.option_advisor.providers import (
    build_synthetic_chain,
    get_chain,
    parse_occ_symbol,
    surface_iv,
)


def test_parse_occ_symbol():
    assert parse_occ_symbol("AAPL260619C00200000") == ("AAPL", "2026-06-19", "C", 200.0)
    assert parse_occ_symbol("SPY260101P00450500") == ("SPY", "2026-01-01", "P", 450.5)


def test_surface_put_skew_positive():
    s = VolSurfaceParams(atm_iv=0.20)
    iv_atm = surface_iv(s, 100, 100, 30 / 365)
    iv_otm_put = surface_iv(s, 90, 100, 30 / 365)
    assert iv_otm_put > iv_atm  # equity put skew


def test_surface_skew_flattens_with_maturity():
    s = VolSurfaceParams(atm_iv=0.20)
    near = surface_iv(s, 95, 100, 30 / 365) - surface_iv(s, 100, 100, 30 / 365)
    far = surface_iv(s, 95, 100, 365 / 365) - surface_iv(s, 100, 100, 365 / 365)
    assert abs(near) > abs(far)  # ~1/sqrt(T) decay


def test_build_synthetic_chain_shape_and_greeks():
    ch = build_synthetic_chain("XYZ", 100.0, 0.20, expiries_dte=(30, 60), n_strikes=11)
    assert ch.data_mode == "synthetic" and ch.spot == 100.0
    assert len(ch.expiries()) == 2
    for q in ch.quotes:
        assert q.iv > 0 and q.delta is not None
        assert q.bid <= q.last <= q.ask  # bracketed model price
    call = ch.nearest_by_delta(ch.nearest_expiry(30), "C", 0.30)
    assert call is not None and 0 < call.delta < 1


def test_get_chain_user_override_is_offline():
    ch = get_chain("ZZZ", spot_override=50.0, iv_override=0.35)
    assert ch.data_mode == "user_override"
    assert ch.spot == 50.0 and ch.atm_iv == 0.35 and ch.quotes


def test_get_chain_synthetic_needs_spot():
    with pytest.raises(Exception):
        get_chain("ZZZ", prefer=(), allow_synthetic=True)  # no live, no spot override
