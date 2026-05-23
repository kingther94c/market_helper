"""Phase 2 — local refinement around Q9 grid winners.

Phase 1 (macro_neighborhood_stability.py) found:
  - Q9 winner ranks #9 by neighborhood-robust score (Δ +0.6pp to top)
  - Top robust candidates concentrate at it ∈ {0.10, 0.12}, m/m=0.6/0.4
  - Q9 winner is the only top-15 with it=0.15 — it sits at a holdout-
    favorable corner, top robust candidates at a train-favorable corner

Refined grid (only configs NOT in the original 360):
  ivw   ∈ {0.5, 0.6, 0.7, 0.85, 1.0}        (added 0.6, 0.85)
  gvw   ∈ {0.0, 0.15, 0.3}                   (added 0.15)
  gt    ∈ {0.10}                             (fixed — all top configs use this)
  it    ∈ {0.10, 0.11, 0.12, 0.13, 0.14, 0.15}  (added 0.11, 0.13, 0.14)
  blend ∈ {(0.55, 0.45), (0.6, 0.4)}         (added 0.55/0.45 as midpoint)

Total refined-zone configs: 5 × 3 × 1 × 6 × 2 = 180
Already in original grid:                       18
New runs in Phase 2:                           162

Goal: see whether a half-step config (e.g. it=0.13) achieves better
train robust AND holdout than either Q9 winner or current top-1.

Writes augmented grid to macro_calibration_grid_q9_refined.json
(union of original 360 + new 162 = 522 configs).
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
from market_helper.regimes.engine_v2 import (
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.macro_regime import load_macro_regime_config
from market_helper.regimes.methods.market_regime import load_market_regime_config

from scripts.research.anchors import (
    ANCHORS_LEVEL, train_anchors, holdout_anchors,
)
from scripts.research.macro_calibration_grid_q9 import (
    _merge_market_panel, _build_engine_cfg, _override_velocity_weights,
    _evaluate, axis_label, run_lengths,
    MACRO_PANEL, REGIME_CFG, FRED_CFG, MARKET_CFG,
)


ORIGINAL_GRID = REPO_ROOT / "data/research_artifacts/macro_calibration_grid_q9.json"
OUT = REPO_ROOT / "data/research_artifacts/macro_calibration_grid_q9_refined.json"


REFINED_GRID = {
    "inflation_velocity_weight": [0.5, 0.6, 0.7, 0.85, 1.0],
    "growth_velocity_weight":    [0.0, 0.15, 0.3],
    "growth_thresh":             [0.10],
    "inflation_thresh":          [0.10, 0.11, 0.12, 0.13, 0.14, 0.15],
    "layer_blend":               [(0.55, 0.45), (0.60, 0.40)],
}


def _params_key(p: dict) -> tuple:
    return (
        round(float(p["inflation_velocity_weight"]), 4),
        round(float(p["growth_velocity_weight"]), 4),
        round(float(p["growth_thresh"]), 4),
        round(float(p["inflation_thresh"]), 4),
        round(float(p["macro_w"]), 4),
        round(float(p["market_w"]), 4),
    )


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

    # Load existing grid; build seen-set so we skip dups
    original = json.loads(ORIGINAL_GRID.read_text(encoding="utf-8"))
    seen = {_params_key(r["params"]) for r in original}
    print(f"loaded {len(original)} original configs", flush=True)

    refined_combos = list(itertools.product(
        REFINED_GRID["inflation_velocity_weight"],
        REFINED_GRID["growth_velocity_weight"],
        REFINED_GRID["growth_thresh"],
        REFINED_GRID["inflation_thresh"],
        REFINED_GRID["layer_blend"],
    ))

    new_combos = []
    for ivw, gvw, gt, it, (macro_w, market_w) in refined_combos:
        params = {
            "inflation_velocity_weight": ivw,
            "growth_velocity_weight": gvw,
            "growth_thresh": gt,
            "inflation_thresh": it,
            "macro_w": macro_w,
            "market_w": market_w,
        }
        if _params_key(params) in seen:
            continue
        new_combos.append(params)
    print(f"refined zone: {len(refined_combos)} configs total, "
          f"{len(refined_combos) - len(new_combos)} already in original grid, "
          f"{len(new_combos)} new to run", flush=True)

    new_results = []
    for i, params in enumerate(new_combos, 1):
        engine = _build_engine_cfg(
            base_engine,
            growth_thresh=params["growth_thresh"],
            inflation_thresh=params["inflation_thresh"],
            macro_w=params["macro_w"],
            market_w=params["market_w"],
        )
        concepts = _override_velocity_weights(
            base_concepts,
            inflation_velocity_weight=params["inflation_velocity_weight"],
            growth_velocity_weight=params["growth_velocity_weight"],
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

        train_metrics = _evaluate(df, train, params["growth_thresh"], params["inflation_thresh"])
        holdout_metrics = _evaluate(df, holdout, params["growth_thresh"], params["inflation_thresh"])

        g_labels = df["final_g"].apply(lambda s: axis_label(s, params["growth_thresh"], -params["growth_thresh"]))
        i_labels = df["final_i"].apply(lambda s: axis_label(s, params["inflation_thresh"], -params["inflation_thresh"]))
        g_runs = run_lengths(g_labels.tolist())
        i_runs = run_lengths(i_labels.tolist())

        new_results.append({
            "params": params,
            "train": train_metrics,
            "holdout": holdout_metrics,
            "stability": {
                "g_median_run_bdays": int(median(g_runs)),
                "i_median_run_bdays": int(median(i_runs)),
                "g_n_runs": len(g_runs),
                "i_n_runs": len(i_runs),
            },
        })
        if i % 12 == 0 or i == len(new_combos):
            print(f"  {i}/{len(new_combos)} done; "
                  f"latest train_overall={train_metrics['overall']:.1f}% "
                  f"holdout_overall={holdout_metrics['overall']:.1f}% "
                  f"(ivw={params['inflation_velocity_weight']} it={params['inflation_thresh']})",
                  flush=True)

    augmented = original + new_results
    OUT.write_text(json.dumps(augmented, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}: {len(augmented)} configs total ({len(original)} original + {len(new_results)} refined)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
