"""Scout the regime engine over the full FRED-aware history.

Dumps axis-score series, anchor-period consensus matches, and stability
diagnostics so we know where macro calibration needs to focus.

This is measurement-only — no config changes. Output goes to
data/research_artifacts/macro_scout.json for the HTML reporter to read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean, median
from typing import Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from market_helper.data_sources.fred.macro_panel import (
    load_concept_specs,
    load_panel,
    load_series_specs,
)
from market_helper.data_sources.yahoo_finance.market_panel import (
    DEFAULT_MARKET_CACHE_DIR,
    DEFAULT_MARKET_PANEL_FILENAME,
    load_market_panel,
)
from market_helper.regimes.engine_v2 import (
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.macro_regime import load_macro_regime_config
from market_helper.regimes.methods.market_regime import load_market_regime_config

import os

HISTORICAL_MKT = REPO_ROOT / "data/external/regime_detection/historical/market_panel_to_2024.feather"
LIVE_MKT = REPO_ROOT / DEFAULT_MARKET_CACHE_DIR / DEFAULT_MARKET_PANEL_FILENAME
MACRO_PANEL = REPO_ROOT / "data/interim/fred/macro_panel.feather"
REGIME_CFG = REPO_ROOT / "configs/regime_detection/regime_engine.yml"
FRED_CFG = REPO_ROOT / "configs/regime_detection/fred_series.yml"
MARKET_CFG = REPO_ROOT / "configs/regime_detection/market_regime.yml"
# Override-able for the after-calibration rerun.
OUT = REPO_ROOT / os.environ.get(
    "MACRO_SCOUT_OUT", "data/research_artifacts/macro_scout.json"
)


# LEVEL-based consensus labels — match the macro layer's YoY-level scoring.
# See macro_calibration_grid.py and the HTML report's "Methodology" section
# for why we use level (CPI YoY vs 2.5% comfort) rather than direction
# (CPI YoY falling vs prior month). Keep these in lock-step with the grid.
ANCHORS = [
    ("2008 GFC trough",     "2008-10-01", "2009-03-31", "Down",   "Down",    "On",
     "Lehman+ deep recession; oil bust drives YoY CPI to ~-2%"),
    ("2010-12 expansion",   "2010-06-01", "2012-12-31", "Up",     "Neutral", "Off",
     "Slow but steady job growth (PAYEMS YoY +1.5-2%), CPI ~2-3%"),
    ("2015-16 oil bust",    "2015-08-01", "2016-02-29", "Neutral","Down",    "On",
     "Mfg recession, CPI YoY near zero, oil bust deflation"),
    ("2017 Goldilocks",     "2017-04-01", "2017-12-31", "Up",     "Neutral", "Off",
     "PAYEMS +1.5% YoY, CPI ~2.1%"),
    ("2018 Q4 vol shock",   "2018-10-01", "2018-12-31", "Up",     "Neutral", "On",
     "Growth still strong YoY (PAYEMS +1.7%); market stress"),
    ("2019 H2 slowdown",    "2019-07-01", "2019-12-31", "Neutral","Neutral", "Off",
     "Mixed: services strong, mfg recession; CPI ~1.8%"),
    ("2020 COVID recession","2020-02-24", "2020-04-30", "Down",   "Neutral", "On",
     "Catastrophic growth shock; CPI YoY collapse but not deflation"),
    ("2020H2 catch-up",     "2020-07-01", "2020-12-31", "Down",   "Down",    "Off",
     "Recovering but YoY still deep negative; CPI YoY ~1.4%"),
    ("2021 reflation",      "2021-04-01", "2021-12-31", "Up",     "Up",      "Off",
     "Strong recovery, CPI breaks above 5%"),
    ("2022 H1 inflation",   "2022-03-01", "2022-09-30", "Up",     "Up",      "On",
     "PAYEMS +5-6% YoY catch-up, CPI peaks at 9.1% in June"),
    ("2023 high inflation", "2023-06-01", "2023-12-31", "Up",     "Up",      "Off",
     "Soft landing but CPI still 3-4%, payrolls +2.5%"),
    ("2024 disinflation",   "2024-01-01", "2024-12-31", "Up",     "Neutral", "Off",
     "PAYEMS +1.5%, CPI fading to ~2.5-3% range"),
    ("2025 tariff shock",   "2025-04-02", "2025-05-15", "Neutral","Up",      "On",
     "Breakevens spike; equity drawdown; growth signals mixed"),
]


def axis_label(score: float, up: float, down: float) -> str:
    if score is None or pd.isna(score):
        return "Unknown"
    if score > up:
        return "Up"
    if score < down:
        return "Down"
    return "Neutral"


def _merge_market_panel() -> pd.DataFrame:
    hist = load_market_panel(HISTORICAL_MKT) if HISTORICAL_MKT.exists() else pd.DataFrame()
    live = load_market_panel(LIVE_MKT) if LIVE_MKT.exists() else pd.DataFrame()
    if hist.empty:
        return live
    if live.empty:
        return hist
    merged = pd.concat([hist, live], ignore_index=True)
    return (
        merged.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def run_lengths(states: Sequence) -> list[int]:
    runs: list[int] = []
    cur = None
    n = 0
    for s in states:
        if s == cur:
            n += 1
        else:
            if cur is not None:
                runs.append(n)
            cur = s
            n = 1
    runs.append(n)
    return runs


def main() -> int:
    cfg = load_regime_engine_config(REGIME_CFG)
    macro_panel = load_panel(MACRO_PANEL)
    market_panel = _merge_market_panel()
    macro_specs = load_series_specs(FRED_CFG)
    macro_concepts = load_concept_specs(FRED_CFG)
    macro_method = load_macro_regime_config(FRED_CFG)
    market_method = load_market_regime_config(MARKET_CFG)

    results = run_regime_engine_v2(
        config=cfg,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        macro_concepts=macro_concepts,
        macro_method_config=macro_method,
        market_panel=market_panel,
        market_config=market_method,
    )
    print(f"engine produced {len(results)} bdays of regime output")

    # Resolve axis thresholds first so we can derive instantaneous labels
    g_up = cfg.regime_thresholds.growth_up
    g_dn = cfg.regime_thresholds.growth_down
    i_up = cfg.regime_thresholds.inflation_up
    i_dn = cfg.regime_thresholds.inflation_down

    rows = []
    for r in results:
        gs = axis_label(r.final_growth_score, g_up, g_dn)
        ins = axis_label(r.final_inflation_score, i_up, i_dn)
        rows.append({
            "date": str(r.date)[:10],
            "macro_g": r.macro_growth_score,
            "macro_i": r.macro_inflation_score,
            "mkt_g": r.market_growth_score,
            "mkt_i": r.market_inflation_score,
            "final_g": r.final_growth_score,
            "final_i": r.final_inflation_score,
            "risk_score": r.risk_score,
            "risk_on": bool(r.risk_overlay_on),
            # Instantaneous labels (without hysteresis); engine's base_regime
            # has hysteresis baked in
            "growth_state": gs,
            "infl_state": ins,
            "quadrant": r.base_regime,
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    print(f"first/last date: {df['date'].iloc[0].date()} / {df['date'].iloc[-1].date()}")
    print(f"macro_g non-null: {df['macro_g'].notna().sum()}/{len(df)}")
    print(f"macro_i non-null: {df['macro_i'].notna().sum()}/{len(df)}")

    anchor_results = []
    for name, start, end, g_exp, i_exp, risk_exp, brief in ANCHORS:
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        win = df[(df["date"] >= lo) & (df["date"] <= hi)].copy()
        if win.empty:
            print(f"  [{name}] no data — skipped")
            continue
        g_labels = [axis_label(s, g_up, g_dn) for s in win["final_g"]]
        i_labels = [axis_label(s, i_up, i_dn) for s in win["final_i"]]
        g_match = sum(1 for l in g_labels if l == g_exp) / len(g_labels)
        i_match = sum(1 for l in i_labels if l == i_exp) / len(i_labels)
        risk_actual_on = bool(win["risk_on"].any())
        risk_match = (risk_actual_on and risk_exp == "On") or (
            not risk_actual_on and risk_exp == "Off"
        )
        anchor_results.append({
            "name": name,
            "start": start,
            "end": end,
            "brief": brief,
            "g_consensus": g_exp,
            "i_consensus": i_exp,
            "risk_consensus": risk_exp,
            "g_match_pct": round(g_match * 100, 1),
            "i_match_pct": round(i_match * 100, 1),
            "risk_match": risk_match,
            "g_mean_score": round(float(win["final_g"].mean()), 3),
            "g_min_score": round(float(win["final_g"].min()), 3),
            "g_max_score": round(float(win["final_g"].max()), 3),
            "i_mean_score": round(float(win["final_i"].mean()), 3),
            "i_min_score": round(float(win["final_i"].min()), 3),
            "i_max_score": round(float(win["final_i"].max()), 3),
            "macro_g_mean": (
                round(float(win["macro_g"].mean()), 3)
                if win["macro_g"].notna().any() else None
            ),
            "macro_i_mean": (
                round(float(win["macro_i"].mean()), 3)
                if win["macro_i"].notna().any() else None
            ),
            "n_days": len(win),
            "stress_days_pct": round(100.0 * win["risk_on"].mean(), 1),
        })
        flag_g = "OK" if g_match >= 0.6 else "**"
        flag_i = "OK" if i_match >= 0.6 else "**"
        flag_r = "OK" if risk_match else "**"
        print(f"  [{flag_g} G {flag_i} I {flag_r} R] {name:30s}  g={g_match*100:.0f}% ({g_exp})  i={i_match*100:.0f}% ({i_exp})  risk={risk_actual_on}/{risk_exp}")

    g_runs = run_lengths(df["growth_state"].tolist())
    i_runs = run_lengths(df["infl_state"].tolist())
    q_runs = run_lengths(df["quadrant"].tolist())

    print()
    print("=== Stability ===")
    print(f"growth state: median={median(g_runs):.0f} bdays  mean={mean(g_runs):.1f}  n_runs={len(g_runs)}")
    print(f"infl state:   median={median(i_runs):.0f} bdays  mean={mean(i_runs):.1f}  n_runs={len(i_runs)}")
    print(f"quadrant:     median={median(q_runs):.0f} bdays  mean={mean(q_runs):.1f}  n_runs={len(q_runs)}")

    df_m = df.set_index("date").resample("ME").last().reset_index()

    out = {
        "n_bdays": len(df),
        "date_min": str(df["date"].iloc[0].date()),
        "date_max": str(df["date"].iloc[-1].date()),
        "thresholds": {
            "growth_up": g_up, "growth_down": g_dn,
            "inflation_up": i_up, "inflation_down": i_dn,
        },
        "anchor_results": anchor_results,
        "stability": {
            "growth_median_run_bdays": float(median(g_runs)),
            "growth_mean_run_bdays": float(mean(g_runs)),
            "growth_n_runs": len(g_runs),
            "infl_median_run_bdays": float(median(i_runs)),
            "infl_mean_run_bdays": float(mean(i_runs)),
            "infl_n_runs": len(i_runs),
            "quadrant_median_run_bdays": float(median(q_runs)),
            "quadrant_mean_run_bdays": float(mean(q_runs)),
            "quadrant_n_runs": len(q_runs),
        },
        "monthly_series": [
            {
                "date": str(r.date.date()),
                "final_g": (float(r.final_g) if pd.notna(r.final_g) else None),
                "final_i": (float(r.final_i) if pd.notna(r.final_i) else None),
                "macro_g": (float(r.macro_g) if pd.notna(r.macro_g) else None),
                "macro_i": (float(r.macro_i) if pd.notna(r.macro_i) else None),
                "mkt_g": (float(r.mkt_g) if pd.notna(r.mkt_g) else None),
                "mkt_i": (float(r.mkt_i) if pd.notna(r.mkt_i) else None),
                "risk_score": (float(r.risk_score) if pd.notna(r.risk_score) else None),
                "risk_on": bool(r.risk_on),
            }
            for r in df_m.itertuples(index=False)
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
