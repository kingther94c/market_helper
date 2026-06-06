"""Goal-v2 Section D -- daily expert-return series for the Policy-Expert Trending panel.

Daily EQ/CM/FI/CASH via the SAME futures-excess accounting as the monthly panel, but the
FI leg uses IEF (daily, 2002+) instead of the synthetic monthly 10Y, and CASH uses DTB3
(daily 3M T-bill). Expert EXPOSURES (EQ/CM/FI; MACRO already removed) are unchanged -- this
is a daily return series for the descriptive Trending panel only; the ML predictor stays
monthly.

Output: data/research_artifacts/policy_expert_daily_returns.csv  (date x 4 experts).
Reuses the project Yahoo client + keyless FRED loader. No execution. ASCII console.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from market_helper.data_sources.yahoo_finance.client import YahooFinanceClient  # noqa: E402
from scripts.research.policy_expert_data import CACHE_DIR, _fred_monthly  # noqa: E402

EXPERTS_JSON = REPO_ROOT / "data/research_artifacts/policy_experts.json"
OUT_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_daily_returns.csv"
EXPERTS = ["Goldilocks", "Reflation", "Stagflation", "Recession"]


def _yahoo_daily_return(symbol: str) -> pd.Series:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = symbol.replace("^", "_").replace("=", "_")
    cache = CACHE_DIR / f"daily_{safe}.feather"
    if cache.exists():
        d = pd.read_feather(cache)
    else:
        pl = YahooFinanceClient().fetch_price_history(symbol, period="max", interval="1d")
        d = pd.DataFrame(pl["prices"])
        d["date"] = pd.to_datetime(d["timestamp"], unit="s").dt.normalize()
        d = d[["date", "adjclose"]].dropna().sort_values("date").reset_index(drop=True)
        d.to_feather(cache)
    px = d.set_index("date")["adjclose"].astype(float)
    return px.pct_change()


def build_daily_panel() -> pd.DataFrame:
    eq = _yahoo_daily_return("^SP500TR")
    cm = _yahoo_daily_return("^SPGSCI")
    fi = _yahoo_daily_return("IEF")                       # daily 7-10Y UST total return
    # CASH from monthly TB3MS (daily DTB3 times out); forward-filled to daily. The cash
    # leg is ~0.01%/day, so monthly-resolution funding is plenty for the daily series.
    tb3ms = _fred_monthly("TB3MS")
    tb3ms.index = pd.to_datetime(tb3ms.index)
    daily_cash = (tb3ms / 100.0 / 252.0).sort_index()
    df = pd.DataFrame({"EQ": eq, "CM": cm, "FI": fi})
    df["CASH"] = daily_cash.reindex(df.index, method="ffill")
    return df.dropna()


def expert_daily_returns(panel: pd.DataFrame, experts: dict) -> pd.DataFrame:
    cash = panel["CASH"]
    out = {}
    for k in EXPERTS:
        e = experts[k]
        out[k] = cash + (e["EQ"] * (panel["EQ"] - cash) + e["CM"] * (panel["CM"] - cash)
                         + e["FI"] * (panel["FI"] - cash)) / 100.0
    return pd.DataFrame(out)


def main() -> int:
    experts = json.loads(EXPERTS_JSON.read_text(encoding="utf-8"))["experts"]
    panel = build_daily_panel()
    rets = expert_daily_returns(panel, experts).dropna()
    rets.index.name = "date"
    out = rets.copy()
    out.index = out.index.strftime("%Y-%m-%d")
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_CSV)
    print(f"wrote {OUT_CSV}  ({rets.shape[0]} days x {rets.shape[1]} experts)")
    print(f"span {rets.index.min().date()} .. {rets.index.max().date()}")
    ann = {k: round(((1 + rets[k]).prod() ** (252 / len(rets)) - 1) * 100, 1) for k in EXPERTS}
    print("daily-series ann return %:", ann)
    for win, label in ((63, "3M"), (21, "1M"), (5, "1W")):
        perf = {k: round(((1 + rets[k]).tail(win).prod() - 1) * 100, 1) for k in EXPERTS}
        print(f"  trailing {label}: {perf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
