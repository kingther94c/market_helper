"""Currency lookthrough — country → currency derivation (shared by monitor + advisor)."""

from __future__ import annotations

import pytest

from market_helper.domain.portfolio_monitor.services import currency_lookthrough as cl


def test_bucket_currency_map():
    assert cl.bucket_currency("DM-JP") == "JPY"
    assert cl.bucket_currency("DM-EUME") == "EUR"     # Eurozone-dominant (folds GBP/CHF)
    assert cl.bucket_currency("DM-US") == "USD"
    assert cl.bucket_currency("EM-CN") == "CNY"
    assert cl.bucket_currency("EM-LATAM") == "Other"   # mixed regional bucket
    assert cl.bucket_currency("WAT") == "Other"        # unknown → Other


def test_expand_to_leaves_via_taxonomy():
    taxonomy = {"DM": [("DM-US", 0.7), ("DM-JP", 0.3)]}
    assert dict(cl.expand_to_leaves([("DM", 1.0)], taxonomy)) == {"DM-US": 0.7, "DM-JP": 0.3}
    # A leaf bucket passes through unchanged.
    assert cl.expand_to_leaves([("DM-JP", 0.4)], taxonomy) == [("DM-JP", 0.4)]


def test_symbol_currency_weights_expands_aggregate_then_maps():
    manual = {"VWRA": [("DM", 1.0)]}                    # symbol mapped to an aggregate bucket
    taxonomy = {"DM": [("DM-US", 0.7), ("DM-JP", 0.2), ("DM-EUME", 0.1)]}
    cw = dict(cl.symbol_currency_weights("VWRA", manual=manual, taxonomy=taxonomy))
    assert cw["USD"] == pytest.approx(0.7)
    assert cw["JPY"] == pytest.approx(0.2)
    assert cw["EUR"] == pytest.approx(0.1)


def test_symbol_currency_weights_unknown_symbol_is_empty():
    assert cl.symbol_currency_weights("NOPE", manual={}, taxonomy={}) == []


def test_country_exposure_to_currency_aggregates_by_ccy():
    out = dict(cl.country_exposure_to_currency({"DM-US": 1000.0, "DM-JP": 200.0, "DM-EUME": 100.0, "EM-CN": 50.0}))
    assert out["USD"] == 1000.0 and out["JPY"] == 200.0 and out["EUR"] == 100.0 and out["CNY"] == 50.0
