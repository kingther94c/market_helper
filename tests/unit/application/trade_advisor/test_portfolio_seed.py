"""Seed AdvisorContext from a positions CSV: holdings / held options / AUM (hermetic)."""

from __future__ import annotations

from market_helper.application.trade_advisor import (
    context_from_positions_csv,
    currency_exposure_from_positions_csv,
)

_HEADER = (
    "as_of,account,internal_id,con_id,symbol,local_symbol,exchange,currency,source,quantity,"
    "avg_cost,latest_price,market_value,cost_basis,unrealized_pnl,weight,option_delta,"
    "option_underlying_price,option_delta_exposure_usd,option_implied_vol,option_greeks_source,"
    "option_greeks_status,option_underlying_symbol,option_underlying_internal_id"
)


def _write_csv(path):
    rows = [
        _HEADER,
        # stock holding → 200 sh AAPL, mv 60000 (counts to AUM)
        "2026-06-03T00:00:00+00:00,U1,STK:AAPL:SMART,1,AAPL,AAPL,SMART,USD,ibkr,200,250,300,60000,50000,10000,0.4,,,,,,,,",
        # held option → short 1 SPY 2026-06-19 C400, mv 500 (held_option, NOT AUM)
        '2026-06-03T00:00:00+00:00,U1,OPT:SPY:SMART,2,SPY,SPY   260619C00400000,SMART,USD,ibkr,-1,5,5,500,500,0,0.0,0.30,759.0,,0.13,modelGreeks,available,SPY,STK:SPY:SMART',
        # future → excluded from AUM/holdings/options
        "2026-06-03T00:00:00+00:00,U1,FUT:ZN:CBOT,3,ZN,10Y US,CBOT,USD,ibkr,1,110000,110,110000,110000,0,0.5,,,,,,,,",
        # cash → counts to AUM
        "2026-06-03T00:00:00+00:00,U1,CASH:USD:IDEALPRO,4,USD,USD,IDEALPRO,USD,ibkr,20000,1,1,20000,20000,0,0.1,,,,,,,,",
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_seed_classifies_holdings_options_and_aum(tmp_path):
    csv_path = tmp_path / "positions.csv"
    _write_csv(csv_path)
    ctx = context_from_positions_csv(csv_path, watchlist=["QQQ"], regime_label="Reflation")

    assert ctx.holdings == {"AAPL": 200.0}          # only the STK row
    assert ctx.aum == 80000.0                        # STK 60000 + CASH 20000 (FUT/OPT excluded)
    assert ctx.watchlist == ["QQQ"]
    assert ctx.regime_label == "Reflation"

    assert len(ctx.held_options) == 1
    opt = ctx.held_options[0]
    assert opt["underlying"] == "SPY" and opt["right"] == "C"
    assert opt["strike"] == 400.0 and opt["expiry"] == "2026-06-19"
    assert opt["qty"] == -1.0 and opt["underlying_price"] == 759.0


def test_missing_csv_returns_empty_context(tmp_path):
    ctx = context_from_positions_csv(tmp_path / "nope.csv", watchlist=["SPY"])
    assert ctx.holdings == {} and ctx.held_options == [] and ctx.aum is None
    assert ctx.watchlist == ["SPY"]  # graceful: watchlist-only scan


def _write_fx_csv(path):
    rows = [
        _HEADER,
        # US equity → USD exposure (quote ccy)
        "2026-06-03T00:00:00+00:00,U1,STK:ACWD:LSEETF,1,ACWD,ACWD,LSEETF,USD,ibkr,100,900,955,95501,90000,5501,0.2,,,,,,,,",
        # CME AUD future → AUD exposure even though USD-quoted (FX-future override)
        "2026-06-03T00:00:00+00:00,U1,FUT:AUD:CME,2,AUD,AUD,CME,USD,ibkr,5,98000,98,493206,490000,3206,0.0,,,,,,,,",
        # Italian bond future → EUR exposure (quote ccy; not an FX future)
        "2026-06-03T00:00:00+00:00,U1,FUT:BTP:EUREX,3,BTP,BTP,EUREX,EUR,ibkr,1,117000,117,117150,117000,150,0.0,,,,,,,,",
        # US Treasury future → USD (quote ccy)
        "2026-06-03T00:00:00+00:00,U1,FUT:ZN:CBOT,4,ZN,10Y US,CBOT,USD,ibkr,1,110000,110,110000,110000,0,0.0,,,,,,,,",
        # cash → USD
        "2026-06-03T00:00:00+00:00,U1,CASH:USD:IDEALPRO,5,USD,USD,IDEALPRO,USD,ibkr,20000,1,1,20000,20000,0,0.0,,,,,,,,",
        # option → excluded from exposure (overlay)
        '2026-06-03T00:00:00+00:00,U1,OUTSIDE_SCOPE:OPT:FLKR:AMEX,6,FLKR,FLKR  260618C00069000,AMEX,USD,ibkr,-1,2,2,-240,-200,-40,0.0,0.3,69,,0.4,modelGreeks,available,FLKR,STK:FLKR:SMART',
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_currency_exposure_maps_fx_futures_and_excludes_options(tmp_path):
    csv_path = tmp_path / "positions.csv"
    _write_fx_csv(csv_path)
    exp = currency_exposure_from_positions_csv(csv_path, lookthrough=False)  # coarse listing-ccy path

    by = dict((c, usd) for c, usd, _w in exp["by_currency"])
    assert by["AUD"] == 493206.0                       # FX future → foreign ccy, not USD
    assert by["EUR"] == 117150.0                        # BTP bond future → quote ccy
    assert by["USD"] == 95501.0 + 110000.0 + 20000.0   # ACWD + ZN + cash
    assert "FLKR" not in by and exp["n_positions"] == 5  # option excluded
    assert exp["by_currency"][0][0] == "AUD"            # ranked by exposure desc
    assert abs(exp["total_usd"] - 835857.0) < 1e-6
    # weights sum to 1
    assert abs(sum(w for _c, _u, w in exp["by_currency"]) - 1.0) < 1e-9


def test_currency_exposure_missing_csv_is_empty(tmp_path):
    exp = currency_exposure_from_positions_csv(tmp_path / "nope.csv", lookthrough=False)
    assert exp["by_currency"] == [] and exp["total_usd"] == 0.0 and exp["n_positions"] == 0


def test_currency_exposure_deeper_lookthrough_splits_equity(tmp_path):
    csv_path = tmp_path / "positions.csv"
    rows = [
        _HEADER,
        # USD-listed ex-US ETF (USD quote) holding Japan + Europe → splits via lookthrough
        "2026-06-03T00:00:00+00:00,U1,STK:VEA:SMART,1,VEA,VEA,SMART,USD,ibkr,1000,40,100,100000,90000,10000,0.5,,,,,,,,",
        # FX future is unchanged by the equity lookthrough
        "2026-06-03T00:00:00+00:00,U1,FUT:AUD:CME,2,AUD,AUD,CME,USD,ibkr,2,98000,98,200000,196000,4000,0.0,,,,,,,,",
    ]
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    # Inject a lookthrough: VEA = 40% Japan + 50% Europe (10% uncovered → listing USD).
    manual = {"VEA": [("DM-JP", 0.40), ("DM-EUME", 0.50)]}
    exp = currency_exposure_from_positions_csv(csv_path, manual=manual, taxonomy={})
    by = dict((c, usd) for c, usd, _w in exp["by_currency"])
    assert exp["lookthrough"] is True
    assert by["JPY"] == 40000.0                 # 0.40 × 100k → JPY (not USD!)
    assert by["EUR"] == 50000.0                 # 0.50 × 100k → EUR
    assert by["USD"] == 10000.0                 # 0.10 uncovered remainder → listing currency
    assert by["AUD"] == 200000.0                # FX future economic ccy, unchanged
    assert "VEA" not in by                       # looked through, not held as a 'VEA currency'
