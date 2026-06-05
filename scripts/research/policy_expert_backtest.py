"""Phases 5-6 -- soft mixture-of-experts allocation + walk-forward backtest.

Phase 5 (allocation): from the walk-forward predictions (soft alloc_k over the 4
experts), blend the experts' exposure vectors into a time-varying sleeve allocation
W_sleeve_t = sum_k alloc_k,t * expert_k, then apply:
  - turnover smoothing (EWMA span 3 on exposures),
  - vol targeting to TARGET_VOL with a hard <= VOL_CAP ceiling (scale by trailing
    realized vol; vol is a CAP not a floor),
  - cash-on-low-confidence (scale toward cash when expert dispersion is low).

Phase 6 (backtest): apply the month-t allocation to month t+1 returns (no look-ahead)
and compare against investable baselines: equal-weight experts, best single static
expert (Goldilocks), static SAA, risk-parity, all-weather, no-MACRO, no-leverage,
simple trend, and cash-in-stagflation. Metrics: ann ret/vol, Sharpe, maxDD, Calmar,
turnover; per-stress-episode attribution.

In-sample caveat: the EXPERTS are full-sample oracle templates (the teacher step) --
static vectors, but their dating is in-sample; only the PREDICTOR is walk-forward.
Reported honestly. Outputs: data/research_artifacts/policy_expert_backtest.json.
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
    ann_return, ann_vol, build_full_panel, max_drawdown,
)

PRED_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_predictions.csv"
EXPERTS_JSON = REPO_ROOT / "data/research_artifacts/policy_experts.json"
FEAT_CSV = REPO_ROOT / "data/research_artifacts/policy_expert_features.csv"
OUT_JSON = REPO_ROOT / "data/research_artifacts/policy_expert_backtest.json"

EXPERTS = ["Goldilocks", "Reflation", "Stagflation", "Recession"]
SLEEVES = ["EQ", "CM", "MACRO", "FI"]
TARGET_VOL = 0.15
VOL_CAP = 0.30
EWMA_SPAN = 3
STRESS = {"2008 GFC": ("2008-07", "2009-03"), "2020 COVID": ("2020-02", "2020-04"),
          "2022 Stagflation": ("2022-01", "2022-10")}


def load_inputs():
    panel = build_full_panel()
    pred = pd.read_csv(PRED_CSV)
    pred["month"] = pd.PeriodIndex(pred["month"], freq="M")
    pred = pred.set_index("month")
    experts = json.loads(EXPERTS_JSON.read_text(encoding="utf-8"))["experts"]
    return panel, pred, experts


def strategy_return(panel: pd.DataFrame, expo: pd.DataFrame) -> pd.Series:
    """Apply month-t exposures (percent) to month t+1 returns. No look-ahead."""
    e = expo.reindex(panel.index).shift(1)            # decided at t, held over t+1
    cash = panel["CASH"]
    contrib = (e["EQ"] * (panel["EQ"] - cash) + e["CM"] * (panel["CM"] - cash)
               + e["FI"] * (panel["FI"] - cash) + e["MACRO"] * panel["MACRO"]) / 100.0
    return (cash + contrib).dropna()


def metrics(r: pd.Series, cash: pd.Series, expo: pd.DataFrame | None = None) -> dict:
    r = r.dropna()
    cash_ann = ann_return(cash.reindex(r.index))
    a, v, dd = ann_return(r), ann_vol(r), max_drawdown(r)
    sharpe = (a - cash_ann) / v if v > 0 else None
    turnover = None
    if expo is not None:
        e = expo.reindex(r.index).dropna()
        turnover = round(float(e.diff().abs().sum(axis=1).mean()), 1)
    return {
        "ann_return_pct": round(a * 100, 2), "ann_vol_pct": round(v * 100, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "max_dd_pct": round(dd * 100, 2),
        "calmar": round(a / abs(dd), 2) if dd < 0 else None,
        "avg_monthly_turnover_pct": turnover,
    }


def build_moe_exposures(pred: pd.DataFrame, experts: dict) -> pd.DataFrame:
    alloc = pred[[f"alloc_{k}" for k in EXPERTS]].to_numpy()
    W = np.zeros((len(pred), len(SLEEVES)))
    for j, k in enumerate(EXPERTS):
        vec = np.array([experts[k][s] for s in SLEEVES])
        W += alloc[:, j][:, None] * vec[None, :]
    expo = pd.DataFrame(W, index=pred.index, columns=SLEEVES)
    # cash-on-low-confidence: scale toward cash when expert dispersion (max-0.25) is low
    conf = (alloc.max(1) - 0.25) / 0.75
    conf = np.clip(0.5 + 0.5 * conf, 0.5, 1.0)        # 0.5..1.0 engagement
    expo = expo.mul(conf, axis=0)
    return expo.ewm(span=EWMA_SPAN).mean()             # turnover smoothing


def vol_target(expo: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Scale exposures by trailing realized vol toward TARGET_VOL, capped at VOL_CAP."""
    raw = strategy_return(panel, expo)
    rv = raw.rolling(12).std() * np.sqrt(12)
    scale = (TARGET_VOL / rv).clip(0.4, 1.3).reindex(expo.index).shift(1).fillna(1.0)
    capped = (VOL_CAP / rv).clip(upper=1.5).reindex(expo.index).shift(1).fillna(1.0)
    scale = np.minimum(scale, capped)
    return expo.mul(scale, axis=0)


def const_expo(index, eq, cm, ma, fi) -> pd.DataFrame:
    return pd.DataFrame({"EQ": eq, "CM": cm, "MACRO": ma, "FI": fi}, index=index)


def risk_parity_expo(panel: pd.DataFrame, index) -> pd.DataFrame:
    rv = {s: (panel[s] if s != "MACRO" else panel["MACRO"]).rolling(36).std() * np.sqrt(12)
          for s in SLEEVES}
    rvdf = pd.DataFrame(rv).reindex(index)
    inv = 1.0 / rvdf
    w = inv.div(inv.sum(axis=1), axis=0) * 100.0      # gross 100, inverse-vol
    return w.bfill()[SLEEVES]


def main() -> int:
    panel, pred, experts = load_inputs()
    idx = pred.index
    cash = panel["CASH"]

    moe_raw = build_moe_exposures(pred, experts)
    moe = vol_target(moe_raw, panel)

    feat = pd.read_csv(FEAT_CSV).rename(columns={"Unnamed: 0": "month"})
    feat["month"] = pd.PeriodIndex(feat["month"], freq="M")
    feat = feat.set_index("month")

    strategies: dict[str, pd.DataFrame] = {
        "MoE (this model)": moe,
        "MoE no-MACRO": moe.assign(MACRO=0.0),
        "MoE no-leverage": moe.div((moe.abs().sum(axis=1) / 100).clip(lower=1.0), axis=0),
        "Equal-weight experts": const_expo(
            idx, *[float(np.mean([experts[k][s] for k in EXPERTS])) for s in SLEEVES]),
        "Best static (Goldilocks)": const_expo(idx, **{"eq": experts["Goldilocks"]["EQ"],
            "cm": experts["Goldilocks"]["CM"], "ma": experts["Goldilocks"]["MACRO"],
            "fi": experts["Goldilocks"]["FI"]}),
        "Static SAA (80/5/15)": const_expo(idx, 80, 5, 0, 15),
        "All-weather": const_expo(idx, 30, 15, 0, 55),
        "Risk parity": risk_parity_expo(panel, idx),
        "Simple trend (MACRO)": const_expo(idx, 0, 0, 100, 0),
    }
    # cash-in-stagflation: Goldilocks, but flat to cash when lagged inflation > 4%
    cis = const_expo(idx, experts["Goldilocks"]["EQ"], experts["Goldilocks"]["CM"],
                     experts["Goldilocks"]["MACRO"], experts["Goldilocks"]["FI"])
    hot = feat["infl_yoy"].reindex(idx) > 4.0
    cis = cis.mul((~hot).astype(float), axis=0)
    strategies["Cash-in-stagflation"] = cis

    results = {}
    for name, expo in strategies.items():
        r = strategy_return(panel, expo)
        results[name] = metrics(r, cash, expo)

    # per-stress-episode attribution: MoE vs always-Goldilocks
    gold = strategies["Best static (Goldilocks)"]
    episode = {}
    for label, (s, e) in STRESS.items():
        lo, hi = pd.Period(s, "M"), pd.Period(e, "M")
        mask = (idx >= lo) & (idx <= hi)
        sub = idx[mask]
        if len(sub) == 0:
            continue
        moe_r = strategy_return(panel, moe.loc[sub])
        gold_r = strategy_return(panel, gold.loc[sub])
        episode[label] = {
            "MoE_total_ret_pct": round(float((1 + moe_r).prod() - 1) * 100, 1),
            "Goldilocks_total_ret_pct": round(float((1 + gold_r).prod() - 1) * 100, 1),
        }

    out = {
        "config": {"target_vol": TARGET_VOL, "vol_cap": VOL_CAP, "ewma_span": EWMA_SPAN,
                   "oos_span": [str(idx.min()), str(idx.max())], "n_months": int(len(idx))},
        "strategies": results,
        "stress_episode_attribution": episode,
        "caveat": "Experts are full-sample oracle templates (teacher step); only the "
                  "predictor is walk-forward. Raw return ~ always-Goldilocks; the edge "
                  "is risk-adjusted (drawdown/Sharpe).",
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    print(f"\nbacktest {out['config']['oos_span']}  ({out['config']['n_months']} months)")
    print(f"{'strategy':28s} {'ret%':>6} {'vol%':>6} {'Sharpe':>7} {'maxDD%':>7} {'Calmar':>7} {'turn%':>6}")
    for name, m in sorted(results.items(), key=lambda kv: -(kv[1]["sharpe"] or -9)):
        print(f"{name:28s} {m['ann_return_pct']:>6} {m['ann_vol_pct']:>6} "
              f"{str(m['sharpe']):>7} {m['max_dd_pct']:>7} {str(m['calmar']):>7} "
              f"{str(m['avg_monthly_turnover_pct']):>6}")
    print("\nstress episodes (MoE vs Goldilocks, total %):")
    for label, d in episode.items():
        print(f"  {label:18s}: MoE {d['MoE_total_ret_pct']:+.1f}  vs  Gold {d['Goldilocks_total_ret_pct']:+.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
