"""Seed AdvisorContext from a positions CSV: holdings / held options / AUM (hermetic)."""

from __future__ import annotations

from market_helper.application.trade_advisor import context_from_positions_csv

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
