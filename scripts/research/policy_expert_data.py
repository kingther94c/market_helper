"""Policy-expert research — monthly sleeve panel + futures-excess accounting.

Clean-room rebuild (the task + lessons are kept; the prior session's concrete code
is NOT reused). This module is the data/accounting LIBRARY imported by
``policy_expert_study.py``.

Sleeves / proxies (longest clean total-return history we can assemble, monthly):
  EQ    = S&P 500 Total Return      (Yahoo ^SP500TR, 1988+)
  CM    = S&P GSCI commodity index  (Yahoo ^SPGSCI, 1985+; spot/excess index)
  FI    = synthetic constant-maturity 10Y UST total return (FRED GS10)
          r ~= y/12 - ModDur*dy + 0.5*Conv*dy^2   (par-bond duration/convexity)
  CASH  = 3M T-bill                 (FRED TB3MS, real cash yield)
  MACRO = TSMOM trend proxy: sign(trailing-12m excess) on EQ/CM/FI, equal-weight,
          vol-scaled ~10% ann (managed-futures stand-in; an EXCESS-return series)

Accounting (FI & MACRO are futures excess-return overlays, off the cash budget):
  R = cash*100% + SUM_sleeve exposure * (sleeve_total_return - cash)
with MACRO's "excess" being the proxy series itself.

Reuses the PROJECT's own committed utilities (keyless data access):
  market_helper.data_library.loader.download_fred_series_csv
  market_helper.data_sources.yahoo_finance.client.YahooFinanceClient

No trade execution, no config changes, no broker calls. ASCII-only console output.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from market_helper.data_library.loader import download_fred_series_csv  # noqa: E402
from market_helper.data_sources.yahoo_finance.client import YahooFinanceClient  # noqa: E402

CACHE_DIR = REPO_ROOT / "data/research_artifacts/_policy_expert_cache"
SAMPLE_START = "1988-01"  # first month with EQ total return (^SP500TR)


# ---------------------------------------------------------------------------
# Raw series (cached to feather for offline-reproducible re-runs)
# ---------------------------------------------------------------------------
def _fred_monthly(series_id: str) -> pd.Series:
    """Monthly FRED series as a float Series indexed by month-start date."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"fred_{series_id}.feather"
    if cache.exists():
        d = pd.read_feather(cache)
    else:
        es = download_fred_series_csv(
            series_id, observation_start="1950-01-01", timeout=60
        )
        d = pd.DataFrame(
            [(o.date, o.value) for o in es.observations], columns=["date", "val"]
        )
        d["date"] = pd.to_datetime(d["date"])
        d = d.dropna().reset_index(drop=True)
        d.to_feather(cache)
    return d.set_index("date")["val"].astype(float).sort_index()


def yahoo_monthly_level(symbol: str) -> pd.Series:
    """Monthly adjusted-close LEVEL series (month-end), cached to feather."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = symbol.replace("^", "_").replace("=", "_")
    cache = CACHE_DIR / f"yahoo_{safe}.feather"
    if cache.exists():
        d = pd.read_feather(cache)
    else:
        payload = YahooFinanceClient().fetch_price_history(
            symbol, period="max", interval="1mo"
        )
        d = pd.DataFrame(payload["prices"])
        d["date"] = pd.to_datetime(d["timestamp"], unit="s").dt.normalize()
        d = d[["date", "adjclose"]].dropna().sort_values("date").reset_index(drop=True)
        d.to_feather(cache)
    return d.set_index("date")["adjclose"].astype(float).resample("ME").last()


def _yahoo_monthly_total_return(symbol: str) -> pd.Series:
    """Monthly simple total return from Yahoo monthly adjusted-close bars."""
    return yahoo_monthly_level(symbol).pct_change()


# ---------------------------------------------------------------------------
# Synthetic constant-maturity 10Y total return from GS10 yields
# ---------------------------------------------------------------------------
def _par_dur_conv(y: float, n_years: int = 10, m: int = 2) -> tuple[float, float]:
    """Modified duration + convexity of a par bond (coupon == ytm == y)."""
    per = n_years * m
    r = y / m
    coupon = y / m * 100.0
    t = np.arange(1, per + 1)
    cf = np.full(per, coupon, dtype=float)
    cf[-1] += 100.0
    disc = (1.0 + r) ** (-t)
    pv = cf * disc
    price = pv.sum()
    years = t / m
    mac_dur = (years * pv).sum() / price
    mod_dur = mac_dur / (1.0 + r)
    conv = ((cf * t * (t + 1) * (1.0 + r) ** (-(t + 2))).sum() / price) / (m ** 2)
    return mod_dur, conv


def synth_10y_total_return(gs10_pct: pd.Series) -> pd.Series:
    """Monthly TR of a constant-maturity 10Y UST: r = y/12 - D*dy + 0.5*C*dy^2."""
    y = (gs10_pct / 100.0).sort_index()
    out = pd.Series(index=y.index, dtype=float)
    yv = y.to_numpy()
    for i in range(1, len(yv)):
        y0, y1 = yv[i - 1], yv[i]
        dmod, conv = _par_dur_conv(y0)
        out.iloc[i] = y0 / 12.0 - dmod * (y1 - y0) + 0.5 * conv * (y1 - y0) ** 2
    return out


# ---------------------------------------------------------------------------
# Panel assembly + MACRO trend sleeve + accounting
# ---------------------------------------------------------------------------
def _to_period(s: pd.Series) -> pd.Series:
    s = s.copy()
    s.index = pd.to_datetime(s.index).to_period("M")
    return s


def build_panel() -> pd.DataFrame:
    """Monthly total-return panel EQ/CM/FI/CASH (PeriodIndex), 1988+."""
    eq = _to_period(_yahoo_monthly_total_return("^SP500TR"))
    cm = _to_period(_yahoo_monthly_total_return("^SPGSCI"))
    fi = _to_period(synth_10y_total_return(_fred_monthly("GS10")))
    cash = _to_period(_fred_monthly("TB3MS") / 100.0 / 12.0)
    df = pd.DataFrame({"EQ": eq, "CM": cm, "FI": fi, "CASH": cash}).dropna()
    return df[df.index >= pd.Period(SAMPLE_START, "M")]


def build_macro(df: pd.DataFrame, target_vol: float = 0.10) -> pd.Series:
    """TSMOM trend proxy (MACRO sleeve), returned as an EXCESS-return series.

    sign(trailing-12m excess) on EQ/CM/FI, equal-weight, vol-scaled to ~target_vol.
    The 12m look-back is lagged by 1 month (no contemporaneous leakage in the
    signal); the resulting series starts ~13 months into the sample.
    """
    ex = pd.DataFrame({s: df[s] - df["CASH"] for s in ("EQ", "CM", "FI")})
    legs = {}
    for s in ("EQ", "CM", "FI"):
        trail = (1.0 + ex[s]).rolling(12).apply(lambda v: v.prod() - 1.0, raw=True).shift(1)
        legs[s] = np.sign(trail) * ex[s]
    macro = pd.concat(legs, axis=1).mean(axis=1)
    scale = target_vol / (macro.std() * np.sqrt(12))
    return (macro * scale).rename("MACRO")


def build_full_panel() -> pd.DataFrame:
    """Panel with the MACRO excess column attached; rows before MACRO dropped."""
    df = build_panel()
    df = df.assign(MACRO=build_macro(df))
    return df.dropna(subset=["MACRO"])


def portfolio_return(
    df: pd.DataFrame, eq: float, cm: float, fi: float, ma: float
) -> pd.Series:
    """Monthly portfolio return. Exposures in PERCENT (e.g. EQ=100, FI=-75, MACRO=10).

    R = cash + (eq*(EQ-cash) + cm*(CM-cash) + fi*(FI-cash) + ma*MACRO_excess) / 100
    """
    cash = df["CASH"]
    contrib = (
        eq * (df["EQ"] - cash)
        + cm * (df["CM"] - cash)
        + fi * (df["FI"] - cash)
        + ma * df["MACRO"]
    )
    return cash + contrib / 100.0


# ---------------------------------------------------------------------------
# Stats helpers (shared by the study)
# ---------------------------------------------------------------------------
def ann_return(r: pd.Series) -> float:
    r = r.dropna()
    return float((1.0 + r).prod() ** (12.0 / len(r)) - 1.0) if len(r) else float("nan")


def ann_vol(r: pd.Series) -> float:
    r = r.dropna()
    return float(r.std(ddof=1) * np.sqrt(12)) if len(r) > 1 else float("nan")


def max_drawdown(r: pd.Series) -> float:
    r = r.dropna()
    if not len(r):
        return float("nan")
    curve = (1.0 + r).cumprod()
    return float((curve / curve.cummax() - 1.0).min())


def fi_validation() -> dict:
    """Cross-check the synthetic 10Y vs IEF (vol / beta / corr). Sanity only."""
    df = build_panel()
    ief = _to_period(_yahoo_monthly_total_return("IEF"))
    j = pd.concat([df["FI"].rename("synth"), ief.rename("ief")], axis=1).dropna()
    beta = float(np.polyfit(j["synth"], j["ief"], 1)[0]) if len(j) > 2 else float("nan")
    return {
        "synth_vol_pct": round(ann_vol(df["FI"]) * 100, 1),
        "ief_vol_pct": round(ann_vol(ief) * 100, 1),
        "beta": round(beta, 2),
        "corr": round(float(j["synth"].corr(j["ief"])), 2),
        "n_overlap_months": int(len(j)),
    }


def _console() -> None:
    df = build_full_panel()
    print(f"panel: {df.index.min()} .. {df.index.max()}  ({df.shape[0]} months)")
    print("cols:", list(df.columns))
    print("\nfull-sample sleeve stats (total return; MACRO is excess):")
    for s in ("EQ", "CM", "FI", "CASH", "MACRO"):
        r = df[s]
        print(f"  {s:5s} ann={ann_return(r)*100:6.1f}%  vol={ann_vol(r)*100:5.1f}%")
    print("\nFI validation vs IEF:", fi_validation())


if __name__ == "__main__":
    _console()
