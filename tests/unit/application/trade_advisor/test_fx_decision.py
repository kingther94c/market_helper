"""fx_decision_from_book — assemble the join from artifact + book (graceful)."""

from __future__ import annotations

from types import SimpleNamespace

from market_helper.application.trade_advisor.fx_decision import fx_decision_from_book

_HEADER = (
    "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,"
    "avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight,option_delta,"
    "option_underlying_price,option_delta_exposure_usd,option_implied_vol,option_greeks_source,"
    "option_greeks_status,option_underlying_symbol,option_underlying_internal_id"
)


def _leg(ccy, contracts, notional):
    return SimpleNamespace(
        currency=ccy, instrument="6" + ccy[0], beta=0.2, target_contracts=contracts,
        target_notional_usd=notional, expected_annual_carry_usd=0.0, on_rate=0.03, expiry="2026-09-16",
    )


def _state():
    alloc = SimpleNamespace(
        run_date="2026-06-10", hedge_target_pair="USD/SGD", hedge_notional_usd=1_000_000.0,
        hedge_notional_source="config", totals={}, regression={},
        legs=[_leg("AUD", 2, 171_842.0)],
    )
    return SimpleNamespace(allocation=alloc, computed_fresh=False, age_days=5,
                           source_label="cache", error_message=None)


def test_fx_decision_from_book_joins(tmp_path):
    csv_path = tmp_path / "positions.csv"
    csv_path.write_text("\n".join([
        _HEADER,
        "2026-06-10T00:00:00+00:00,U1,FUT:AUD:CME,1,AUD,AUD,CME,USD,ibkr,7,70000,0.70458,493206,500000,-6794,0.1,,,,,,,,",
    ]) + "\n", encoding="utf-8")

    out = fx_decision_from_book(provider=lambda **k: _state(), positions_path=csv_path)
    assert out["available"] is True and out["data_mode"].startswith("cached")
    aud = out["rows"][0]
    assert aud["ccy"] == "AUD" and aud["cur_qty"] == 7.0 and aud["tgt_ct"] == 2
    assert aud["gap_ct"] == -5.0                                  # held 7 vs target 2


def test_fx_decision_from_book_graceful_when_missing(tmp_path):
    missing_state = SimpleNamespace(allocation=None, error_message="no artifact")
    out = fx_decision_from_book(provider=lambda **k: missing_state,
                                positions_path=tmp_path / "nope.csv")
    assert out["available"] is False and out["rows"] == []
    assert "no cached FX hedge target" in out["note"]

    def boom(**_k):
        raise RuntimeError("provider exploded")

    # The fx_hedge adapter absorbs provider errors into its missing-state result,
    # so even a raising provider degrades to the same honest no-target answer.
    out2 = fx_decision_from_book(provider=boom, positions_path=tmp_path / "nope.csv")
    assert out2["available"] is False and out2["rows"] == []             # never raises
