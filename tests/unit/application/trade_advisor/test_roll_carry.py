"""Roll-yield fetch + artifact cache — network only behind the explicit action."""

from __future__ import annotations

from market_helper.application.trade_advisor.roll_carry import fetch_roll_yields, load_roll_yields

_HEADER = (
    "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,"
    "avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight,option_delta,"
    "option_underlying_price,option_delta_exposure_usd,option_implied_vol,option_greeks_source,"
    "option_greeks_status,option_underlying_symbol,option_underlying_internal_id"
)


def _write_positions(path):
    rows = [
        _HEADER,
        "2026-06-09T00:00:00+00:00,U1,FUT:NGQ26:NYMEX,1,NG,NGQ26,NYMEX,USD,ibkr,-1,30000,3.23,-32300,-30000,-2300,0.0,,,,,,,,",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_fetch_writes_cache_and_load_round_trips(tmp_path):
    csv_path = tmp_path / "positions.csv"
    artifact = tmp_path / "roll_yield.json"
    _write_positions(csv_path)
    quotes = {"NGQ26.NYM": 3.23, "NGU26.NYM": 3.10}

    payload = fetch_roll_yields(
        positions_path=csv_path, artifact_path=artifact,
        fetcher=lambda s: quotes.get(s), now="2026-06-10T08:00:00",
    )
    assert payload["fetched_at"] == "2026-06-10T08:00:00"
    assert payload["rows"][0]["status"] == "ok"
    assert payload["rows"][0]["curve"] == "backwardation"      # 3.23 > 3.10

    out = load_roll_yields(artifact, now="2026-06-10T20:00:00")
    assert out is not None
    assert out["rows"][0]["next_contract"] == "NGU26"
    assert abs(out["age_hours"] - 12.0) < 1e-9                  # honest age stamp


def test_load_missing_or_corrupt_is_none(tmp_path):
    assert load_roll_yields(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{oops", encoding="utf-8")
    assert load_roll_yields(bad) is None
