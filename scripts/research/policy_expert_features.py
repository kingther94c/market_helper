"""Phase 4a -- ex-ante point-in-time feature panel for the policy-expert predictor.

Every feature row at month t uses ONLY information available at the END of month t:
  - MACRO features (FRED) are lagged +1 month (a monthly print for month m is
    released during m+1), so feature[t] references data through ~month t-1 -- safely
    ex-ante. Lag is recorded per feature in the schema.
  - MARKET features (prices / returns) through month t are known at end of t; their
    trailing windows end at t (no extra lag).

Sources are keyless: FRED via download_fred_series_csv (reused from policy_expert_data),
market sleeves from build_full_panel.

Outputs (data/research_artifacts/):
  policy_expert_features.csv    -- month x feature columns (ex-ante)
  policy_expert_feature_schema.json -- name -> {source, transform, lag_months, group}
No execution, no config changes. ASCII-only console.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.research.policy_expert_data import (  # noqa: E402
    _fred_monthly, _to_period, _yahoo_monthly_total_return, build_full_panel,
    yahoo_monthly_level,
)

OUT_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_features.csv"
OUT_SCHEMA = REPO_ROOT / "data/research_artifacts/policy_expert_feature_schema.json"

MACRO_LAG = 1  # months; publication-lag guard applied to every FRED-derived feature


def _yoy_pct(level: pd.Series) -> pd.Series:
    return (level / level.shift(12) - 1.0) * 100.0


def _fred_period(series_id: str) -> pd.Series:
    """Monthly FRED series on a Period('M') index. Daily series are month-averaged."""
    s = _fred_monthly(series_id)
    s.index = pd.to_datetime(s.index)
    if s.index.to_series().diff().median() < pd.Timedelta(days=20):
        s = s.resample("ME").mean()           # daily -> monthly average
    s.index = s.index.to_period("M")
    return s.sort_index()


def build_features() -> tuple[pd.DataFrame, dict]:
    panel = build_full_panel()                # EQ/CM/FI/CASH/MACRO, Period('M')
    idx = panel.index
    schema: dict = {}
    feat = pd.DataFrame(index=idx)

    def add_macro(name, series, transform, group):
        feat[name] = series.reindex(idx)
        schema[name] = {"source": "FRED", "transform": transform,
                        "lag_months": MACRO_LAG, "group": group}

    def add_market(name, series, transform, group):
        feat[name] = series.reindex(idx)
        schema[name] = {"source": "market", "transform": transform,
                        "lag_months": 0, "group": group}

    # ---- MACRO (FRED) ----
    cpi = _fred_period("CPIAUCSL")
    cpi_yoy = _yoy_pct(cpi)
    add_macro("infl_yoy", cpi_yoy, "CPIAUCSL YoY %", "inflation")
    add_macro("infl_accel", cpi_yoy - cpi_yoy.shift(6), "CPI YoY 6m change", "inflation")
    add_macro("core_infl_yoy", _yoy_pct(_fred_period("PCEPILFE")), "core PCE YoY %", "inflation")

    unrate = _fred_period("UNRATE")
    add_macro("unrate", unrate, "UNRATE level", "growth")
    add_macro("unrate_chg6", unrate - unrate.shift(6), "UNRATE 6m change", "growth")
    add_macro("payems_yoy", _yoy_pct(_fred_period("PAYEMS")), "payrolls YoY %", "growth")
    add_macro("indpro_yoy", _yoy_pct(_fred_period("INDPRO")), "industrial prod YoY %", "growth")

    ff = _fred_period("FEDFUNDS")
    add_macro("policy_rate", ff, "fed funds level", "policy")
    add_macro("policy_rate_chg6", ff - ff.shift(6), "fed funds 6m change", "policy")

    gs10 = _fred_period("GS10")
    add_macro("real_yield", gs10 - cpi_yoy, "GS10 - CPI YoY", "rates")
    add_macro("curve_slope", gs10 - _fred_period("GS2"), "GS10 - GS2", "rates")
    add_macro("credit_spread", _fred_period("BAA") - _fred_period("AAA"), "BAA - AAA", "credit")

    try:
        vix_level = _to_period(yahoo_monthly_level("^VIX"))   # real-time, no lag
        add_market("vix", vix_level, "VIX monthly close level", "risk")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] VIX unavailable ({exc}); skipping")

    # ---- MARKET (from sleeves; known at t) ----
    for s in ("EQ", "CM", "FI"):
        mom = (1 + panel[s]).rolling(12).apply(lambda v: v.prod() - 1, raw=True) * 100
        add_market(f"{s.lower()}_mom12", mom, f"{s} trailing 12m return %", "momentum")
    # USD momentum (best-effort; Yahoo ICE dollar index)
    try:
        dxy = _to_period(_yahoo_monthly_total_return("DX-Y.NYB"))
        usd_mom = (1 + dxy).rolling(12).apply(lambda v: v.prod() - 1, raw=True) * 100
        add_market("usd_mom12", usd_mom, "USD (DXY) trailing 12m %", "momentum")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] USD momentum unavailable ({exc}); skipping")

    eq_level = (1 + panel["EQ"]).cumprod()
    add_market("eq_drawdown", (eq_level / eq_level.cummax() - 1) * 100, "EQ drawdown %", "stress")
    fi_level = (1 + panel["FI"]).cumprod()
    add_market("fi_drawdown", (fi_level / fi_level.cummax() - 1) * 100, "FI drawdown %", "stress")
    add_market("move_proxy",
               panel["FI"].rolling(3).std() * np.sqrt(12) * 100,
               "FI 3m realized vol %% (MOVE proxy)", "stress")
    add_market("eqfi_corr12",
               panel["EQ"].rolling(12).corr(panel["FI"]),
               "rolling 12m corr(EQ,FI)", "cross")
    ex = pd.DataFrame({s: panel[s] - panel["CASH"] for s in ("EQ", "CM", "FI")})
    trend_sign = np.sign((1 + ex).rolling(12).apply(lambda v: v.prod() - 1, raw=True))
    add_market("trend_breadth", trend_sign.sum(axis=1), "n positive 12m trends (-3..3)", "trend")

    # publication-lag guard on macro features
    macro_cols = [c for c, m in schema.items() if m["lag_months"] == MACRO_LAG]
    feat[macro_cols] = feat[macro_cols].shift(MACRO_LAG)

    return feat, schema


def main() -> int:
    feat, schema = build_features()
    n_full = int(feat.dropna().shape[0])
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    out = feat.copy()
    out.index = out.index.astype(str)
    out.index.name = "month"
    out.to_csv(OUT_CSV)
    OUT_SCHEMA.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    print(f"wrote {OUT_CSV}  ({feat.shape[0]} months x {feat.shape[1]} features)")
    print(f"wrote {OUT_SCHEMA}")
    print(f"complete-case rows: {n_full}  (span {feat.dropna().index.min()} .. {feat.dropna().index.max()})")
    print("\nfeatures by group:")
    groups: dict = {}
    for c, m in schema.items():
        groups.setdefault(m["group"], []).append(c)
    for g, cols in groups.items():
        print(f"  {g:10s}: {', '.join(cols)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
