"""Q9 calibration grid - train/holdout discipline + velocity layer sweep.

Sweeps:
  - inflation_velocity concept weight ∈ [0.0, 0.3, 0.5, 0.7, 1.0]
  - growth_velocity concept weight   ∈ [0.0, 0.3, 0.5, 0.7]
  - inflation_thresh                  ∈ [0.10, 0.12, 0.15]
  - growth_thresh                     ∈ [0.10, 0.12, 0.15]
  - layer blend (macro_w, market_w)   ∈ [(0.5,0.5), (0.6,0.4)]

Evaluates each config on the 9 TRAIN anchors only. Holdout (4 anchors:
2008 GFC, 2017 Goldilocks, 2024 disinflation, 2025 tariff) is recorded
in the output but NOT used for selection. After the train winner is
picked, holdout is the validation signal.

Per-config metrics:
  - train: g_avg_match_pct, i_avg_match_pct, risk_avg_match_pct, overall
  - holdout: same (validation only)
  - stability (g/i median run, on full history)
"""
from __future__ import annotations

import itertools
import json
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from statistics import mean, median
from typing import Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from market_helper.data_sources.fred.macro_panel import (
    ConceptSpec,
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
    LayerConfig,
    RegimeEngineConfig,
    RegimeThresholds,
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.macro_regime import (
    MacroRegimeConfig,
    load_macro_regime_config,
)
from market_helper.regimes.methods.market_regime import load_market_regime_config

from scripts.research.anchors import (
    ANCHORS_LEVEL,
    train_anchors,
    holdout_anchors,
)


HISTORICAL_MKT = REPO_ROOT / "data/external/regime_detection/historical/market_panel_to_2024.feather"
LIVE_MKT = REPO_ROOT / DEFAULT_MARKET_CACHE_DIR / DEFAULT_MARKET_PANEL_FILENAME
MACRO_PANEL = REPO_ROOT / "data/interim/fred/macro_panel.feather"
REGIME_CFG = REPO_ROOT / "configs/regime_detection/regime_engine.yml"
FRED_CFG = REPO_ROOT / "configs/regime_detection/fred_series.yml"
MARKET_CFG = REPO_ROOT / "configs/regime_detection/market_regime.yml"
OUT = REPO_ROOT / "data/research_artifacts/macro_calibration_grid_q9.json"


# Q9 grid dimensions. Smaller than Q8 since several Q8 dims were resolved.
GRID = {
    "inflation_velocity_weight": [0.0, 0.3, 0.5, 0.7, 1.0],
    "growth_velocity_weight":    [0.0, 0.3, 0.5, 0.7],
    "growth_thresh":             [0.10, 0.12, 0.15],
    "inflation_thresh":          [0.10, 0.12, 0.15],
    "layer_blend":               [(0.50, 0.50), (0.60, 0.40)],
}


def axis_label(score: float, up: float, down: float) -> str:
    if score is None or pd.isna(score):
        return "Unknown"
    if score > up:
        return "Up"
    if score < down:
        return "Down"
    return "Neutral"


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
        .sort_values("date").reset_index(drop=True)
    )


def _build_engine_cfg(
    base: RegimeEngineConfig, *, growth_thresh: float, inflation_thresh: float,
    macro_w: float, market_w: float,
) -> RegimeEngineConfig:
    layers = dict(base.layers)
    layers["macro_nowcast"] = replace(
        layers["macro_nowcast"], weight_growth=macro_w, weight_inflation=macro_w
    )
    layers["market_implied"] = replace(
        layers["market_implied"], weight_growth=market_w, weight_inflation=market_w
    )
    new_thresh = replace(
        base.regime_thresholds,
        growth_up=growth_thresh,
        growth_down=-growth_thresh,
        inflation_up=inflation_thresh,
        inflation_down=-inflation_thresh,
    )
    return replace(base, layers=layers, regime_thresholds=new_thresh)


def _override_velocity_weights(
    concepts: Sequence[ConceptSpec],
    *, inflation_velocity_weight: float, growth_velocity_weight: float,
) -> list[ConceptSpec]:
    out = []
    for c in concepts:
        if c.name == "inflation_velocity":
            out.append(replace(c, weight=inflation_velocity_weight))
        elif c.name == "growth_velocity":
            out.append(replace(c, weight=growth_velocity_weight))
        else:
            out.append(c)
    return out


def _evaluate(df: pd.DataFrame, anchors, gt: float, it: float) -> dict:
    per = []
    for a in anchors:
        lo, hi = pd.Timestamp(a.start), pd.Timestamp(a.end)
        win = df[(df["date"] >= lo) & (df["date"] <= hi)]
        if win.empty:
            continue
        g = win["final_g"].apply(lambda s: axis_label(s, gt, -gt))
        i = win["final_i"].apply(lambda s: axis_label(s, it, -it))
        risk_actual_on = bool(win["risk_on"].any())
        risk_match = (risk_actual_on and a.risk_consensus == "On") or (
            not risk_actual_on and a.risk_consensus == "Off"
        )
        per.append({
            "name": a.name,
            "g_match_pct": round(100.0 * (g == a.g_consensus).mean(), 1),
            "i_match_pct": round(100.0 * (i == a.i_consensus).mean(), 1),
            "risk_match": risk_match,
        })
    if not per:
        return {"overall": 0.0, "g_avg": 0.0, "i_avg": 0.0, "risk_avg": 0.0, "per_anchor": []}
    g_avg = mean(p["g_match_pct"] for p in per)
    i_avg = mean(p["i_match_pct"] for p in per)
    risk_avg = 100.0 * mean(1.0 if p["risk_match"] else 0.0 for p in per)
    overall = (g_avg + i_avg + risk_avg) / 3.0
    return {
        "overall": round(overall, 1),
        "g_avg": round(g_avg, 1),
        "i_avg": round(i_avg, 1),
        "risk_avg": round(risk_avg, 1),
        "per_anchor": per,
    }


def main() -> int:
    base_engine = load_regime_engine_config(REGIME_CFG)
    base_macro = load_macro_regime_config(FRED_CFG)
    macro_specs = load_series_specs(FRED_CFG)
    base_concepts = load_concept_specs(FRED_CFG)
    market_method = load_market_regime_config(MARKET_CFG)
    macro_panel = load_panel(MACRO_PANEL)
    market_panel = _merge_market_panel()
    train = train_anchors()
    holdout = holdout_anchors()
    print(f"train anchors: {len(train)}, holdout: {len(holdout)}", flush=True)
    print(f"macro_panel {macro_panel.shape}, market_panel {market_panel.shape}", flush=True)

    grid = list(itertools.product(
        GRID["inflation_velocity_weight"],
        GRID["growth_velocity_weight"],
        GRID["growth_thresh"],
        GRID["inflation_thresh"],
        GRID["layer_blend"],
    ))
    print(f"running {len(grid)} configs (train-only evaluation)...", flush=True)

    all_results = []
    for i, (ivw, gvw, gt, it, (macro_w, market_w)) in enumerate(grid, 1):
        engine = _build_engine_cfg(
            base_engine, growth_thresh=gt, inflation_thresh=it,
            macro_w=macro_w, market_w=market_w,
        )
        concepts = _override_velocity_weights(
            base_concepts,
            inflation_velocity_weight=ivw,
            growth_velocity_weight=gvw,
        )
        results = run_regime_engine_v2(
            config=engine,
            macro_panel=macro_panel, macro_specs=macro_specs,
            macro_concepts=concepts, macro_method_config=base_macro,
            market_panel=market_panel, market_config=market_method,
        )
        rows = [{"date": pd.Timestamp(str(r.date)[:10]),
                 "final_g": r.final_growth_score,
                 "final_i": r.final_inflation_score,
                 "risk_on": bool(r.risk_overlay_on)} for r in results]
        df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

        train_metrics = _evaluate(df, train, gt, it)
        holdout_metrics = _evaluate(df, holdout, gt, it)

        # Stability — instantaneous labels on full history
        g_labels = df["final_g"].apply(lambda s: axis_label(s, gt, -gt))
        i_labels = df["final_i"].apply(lambda s: axis_label(s, it, -it))
        g_runs = run_lengths(g_labels.tolist())
        i_runs = run_lengths(i_labels.tolist())

        all_results.append({
            "params": {
                "inflation_velocity_weight": ivw,
                "growth_velocity_weight": gvw,
                "growth_thresh": gt,
                "inflation_thresh": it,
                "macro_w": macro_w,
                "market_w": market_w,
            },
            "train": train_metrics,
            "holdout": holdout_metrics,
            "stability": {
                "g_median_run_bdays": int(median(g_runs)),
                "i_median_run_bdays": int(median(i_runs)),
                "g_n_runs": len(g_runs),
                "i_n_runs": len(i_runs),
            },
        })
        if i % 12 == 0 or i == len(grid):
            print(f"  {i}/{len(grid)} done; latest train_overall={train_metrics['overall']:.1f}% "
                  f"holdout_overall={holdout_metrics['overall']:.1f}%", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
