"""Q1 — Robustness sweep for the Q8 macro calibration recommendation.

Re-runs the engine for a handful of contender configs (baseline + Q8
winner + top-N from grid), gets per-day score frames, then in-memory
re-evaluates each config against perturbed anchor sets:
  - Boundary shifts ±5, ±10, ±20 bdays (one anchor set per shift)
  - Leave-one-out (13 anchor sets)
  - Alternative consensus labels (one anchor set)

For each (perturbation, config), compute overall match%, growth match%,
inflation match%, risk match%. Then report:
  - Does Q8 still beat baseline under every perturbation?
  - How does its rank shift in the top-K?
  - Which anchors are most rank-sensitive (likely overfit signals)?

Output: data/research_artifacts/macro_robustness.json
"""
from __future__ import annotations

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
from market_helper.regimes.methods.macro_regime import (
    MacroRegimeConfig,
    load_macro_regime_config,
)
from market_helper.regimes.methods.market_regime import load_market_regime_config

from scripts.research.anchors import (
    ANCHORS_LEVEL,
    Anchor,
    perturb_boundary_shifts,
    perturb_alt_consensus,
    perturb_leave_one_out,
)
from scripts.research.macro_calibration_grid import (
    _merge_market_panel,
    _build_engine_cfg,
    _build_macro_cfg,
    MACRO_PANEL,
    REGIME_CFG,
    FRED_CFG,
    MARKET_CFG,
)


OUT = REPO_ROOT / "data/research_artifacts/macro_robustness.json"


# Contender configs to test for robustness. Names map to the params dict
# layout used everywhere else in the workflow.
BASELINE = dict(
    name="Q7 baseline (Q6 + Q7 risk overlay)",
    min_weight=0.65, growth_thresh=0.15, inflation_thresh=0.12,
    axis_min_consecutive=5, macro_g_w=0.35, macro_i_w=0.30,
    market_g_w=0.65, market_i_w=0.70,
)
Q8_WINNER = dict(
    name="Q8 winner (balanced + gt=0.10)",
    min_weight=0.65, growth_thresh=0.10, inflation_thresh=0.12,
    axis_min_consecutive=5, macro_g_w=0.50, macro_i_w=0.50,
    market_g_w=0.50, market_i_w=0.50,
)
# Two close runner-ups from the top-10 — useful to see if Q8 is uniquely
# good or just one of a cluster.
RUNNERUP_BALANCED_IT008 = dict(
    name="Runner-up: balanced + gt=0.10 + it=0.08",
    min_weight=0.65, growth_thresh=0.10, inflation_thresh=0.08,
    axis_min_consecutive=5, macro_g_w=0.50, macro_i_w=0.50,
    market_g_w=0.50, market_i_w=0.50,
)
RUNNERUP_INFLATION_HEAVY = dict(
    name="Runner-up: inflation_macro_heavy + gt=0.10",
    min_weight=0.65, growth_thresh=0.10, inflation_thresh=0.12,
    axis_min_consecutive=5, macro_g_w=0.30, macro_i_w=0.60,
    market_g_w=0.70, market_i_w=0.40,
)
RUNNERUP_LOW_DECAY = dict(
    name="Runner-up: balanced + gt=0.10 + decay engaged (mw=0.10)",
    min_weight=0.10, growth_thresh=0.10, inflation_thresh=0.12,
    axis_min_consecutive=5, macro_g_w=0.50, macro_i_w=0.50,
    market_g_w=0.50, market_i_w=0.50,
)

CONTENDERS = [BASELINE, Q8_WINNER, RUNNERUP_BALANCED_IT008,
              RUNNERUP_INFLATION_HEAVY, RUNNERUP_LOW_DECAY]


def axis_label(score: float, up: float, down: float) -> str:
    if score is None or pd.isna(score):
        return "Unknown"
    if score > up:
        return "Up"
    if score < down:
        return "Down"
    return "Neutral"


def _run_one_config(params: dict, *, base_engine, base_macro,
                    macro_panel, market_panel, macro_specs,
                    macro_concepts, market_method) -> pd.DataFrame:
    """Run the engine for one config and return the full per-day score frame."""
    engine = _build_engine_cfg(
        base_engine,
        growth_thresh=params["growth_thresh"],
        inflation_thresh=params["inflation_thresh"],
        axis_min_consecutive=params["axis_min_consecutive"],
        macro_g_w=params["macro_g_w"],
        macro_i_w=params["macro_i_w"],
        market_g_w=params["market_g_w"],
        market_i_w=params["market_i_w"],
    )
    macro = _build_macro_cfg(base_macro, min_weight=params["min_weight"])
    results = run_regime_engine_v2(
        config=engine,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        macro_concepts=macro_concepts,
        macro_method_config=macro,
        market_panel=market_panel,
        market_config=market_method,
    )
    rows = []
    for r in results:
        rows.append({
            "date": pd.Timestamp(str(r.date)[:10]),
            "final_g": r.final_growth_score,
            "final_i": r.final_inflation_score,
            "risk_on": bool(r.risk_overlay_on),
        })
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def evaluate_against_anchors(
    df: pd.DataFrame,
    anchors: Sequence[Anchor],
    *,
    growth_thresh: float,
    inflation_thresh: float,
) -> dict:
    """Compute per-anchor match% and aggregate metrics for one (config, anchor-set) pair."""
    per = []
    for a in anchors:
        lo, hi = pd.Timestamp(a.start), pd.Timestamp(a.end)
        win = df[(df["date"] >= lo) & (df["date"] <= hi)]
        if win.empty:
            continue
        g_labels = win["final_g"].apply(
            lambda s: axis_label(s, growth_thresh, -growth_thresh)
        )
        i_labels = win["final_i"].apply(
            lambda s: axis_label(s, inflation_thresh, -inflation_thresh)
        )
        risk_actual_on = bool(win["risk_on"].any())
        risk_match = (risk_actual_on and a.risk_consensus == "On") or (
            not risk_actual_on and a.risk_consensus == "Off"
        )
        per.append({
            "name": a.name,
            "g_match_pct": round(100.0 * (g_labels == a.g_consensus).mean(), 1),
            "i_match_pct": round(100.0 * (i_labels == a.i_consensus).mean(), 1),
            "risk_match": risk_match,
        })
    if not per:
        return {"overall": 0.0, "g_avg": 0.0, "i_avg": 0.0, "risk_avg": 0.0,
                "per_anchor": []}
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
    print("loading panels and configs...", flush=True)
    base_engine = load_regime_engine_config(REGIME_CFG)
    base_macro = load_macro_regime_config(FRED_CFG)
    macro_specs = load_series_specs(FRED_CFG)
    macro_concepts = load_concept_specs(FRED_CFG)
    market_method = load_market_regime_config(MARKET_CFG)
    macro_panel = load_panel(MACRO_PANEL)
    market_panel = _merge_market_panel()

    # Stash per-config full frames in memory
    print(f"running {len(CONTENDERS)} contender configs...", flush=True)
    frames = {}
    for params in CONTENDERS:
        print(f"  {params['name']}", flush=True)
        frames[params["name"]] = _run_one_config(
            params,
            base_engine=base_engine, base_macro=base_macro,
            macro_panel=macro_panel, market_panel=market_panel,
            macro_specs=macro_specs, macro_concepts=macro_concepts,
            market_method=market_method,
        )

    # Build perturbation sets
    print("evaluating against perturbations...", flush=True)
    perturbations = []
    perturbations.append(("original anchors", list(ANCHORS_LEVEL)))
    for s in (-20, -10, -5, +5, +10, +20):
        perturbations.append((f"boundary shift {s:+d}bd", perturb_boundary_shifts(s)))
    perturbations.append(("alternative consensus labels", perturb_alt_consensus()))
    for name, anchors in perturb_leave_one_out():
        perturbations.append((f"LOO: {name}", anchors))

    # Per-perturbation, per-contender evaluation
    results = []
    for pert_name, anchors in perturbations:
        per_contender = {}
        for params in CONTENDERS:
            df = frames[params["name"]]
            metrics = evaluate_against_anchors(
                df, anchors,
                growth_thresh=params["growth_thresh"],
                inflation_thresh=params["inflation_thresh"],
            )
            per_contender[params["name"]] = metrics
        # Rank contenders by overall match
        ranked = sorted(per_contender.items(), key=lambda kv: -kv[1]["overall"])
        # Find baseline & Q8 ranks
        baseline_rank = next((i for i, (n, _) in enumerate(ranked) if n == BASELINE["name"]), -1)
        q8_rank = next((i for i, (n, _) in enumerate(ranked) if n == Q8_WINNER["name"]), -1)
        q8_overall = per_contender[Q8_WINNER["name"]]["overall"]
        baseline_overall = per_contender[BASELINE["name"]]["overall"]
        results.append({
            "perturbation": pert_name,
            "baseline_overall": baseline_overall,
            "q8_overall": q8_overall,
            "q8_beats_baseline": q8_overall > baseline_overall,
            "q8_minus_baseline": round(q8_overall - baseline_overall, 1),
            "baseline_rank": baseline_rank + 1,
            "q8_rank": q8_rank + 1,
            "winner_name": ranked[0][0],
            "winner_overall": ranked[0][1]["overall"],
            "per_contender": per_contender,
        })

    # Aggregate stats
    q8_wins = sum(1 for r in results if r["q8_beats_baseline"])
    q8_loses = sum(1 for r in results if r["q8_overall"] < r["baseline_overall"])
    q8_ties = sum(1 for r in results if r["q8_overall"] == r["baseline_overall"])
    q8_top1 = sum(1 for r in results if r["q8_rank"] == 1)
    q8_top2 = sum(1 for r in results if r["q8_rank"] <= 2)
    q8_min_delta = min(r["q8_minus_baseline"] for r in results)
    q8_max_delta = max(r["q8_minus_baseline"] for r in results)
    q8_median_delta = median(r["q8_minus_baseline"] for r in results)

    # Find perturbations that hurt Q8 most
    worst_for_q8 = sorted(results, key=lambda r: r["q8_minus_baseline"])[:5]
    best_for_q8 = sorted(results, key=lambda r: -r["q8_minus_baseline"])[:5]

    out = {
        "n_perturbations": len(results),
        "n_contenders": len(CONTENDERS),
        "contenders": [{"name": c["name"], "params": {k: v for k, v in c.items() if k != "name"}} for c in CONTENDERS],
        "summary": {
            "q8_beats_baseline_count": q8_wins,
            "q8_loses_count": q8_loses,
            "q8_ties_count": q8_ties,
            "q8_top1_count": q8_top1,
            "q8_top2_count": q8_top2,
            "q8_min_delta_pp": q8_min_delta,
            "q8_max_delta_pp": q8_max_delta,
            "q8_median_delta_pp": q8_median_delta,
        },
        "worst_perturbations_for_q8": [
            {"perturbation": r["perturbation"],
             "delta": r["q8_minus_baseline"],
             "q8": r["q8_overall"],
             "baseline": r["baseline_overall"]}
            for r in worst_for_q8
        ],
        "best_perturbations_for_q8": [
            {"perturbation": r["perturbation"],
             "delta": r["q8_minus_baseline"],
             "q8": r["q8_overall"],
             "baseline": r["baseline_overall"]}
            for r in best_for_q8
        ],
        "all_results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print()
    print(f"Q8 vs baseline across {len(results)} perturbations:")
    print(f"  Q8 beats baseline:  {q8_wins:3d} / {len(results)}")
    print(f"  Q8 ties baseline:   {q8_ties:3d} / {len(results)}")
    print(f"  Q8 loses baseline:  {q8_loses:3d} / {len(results)}")
    print(f"  Q8 ranks #1:        {q8_top1:3d} / {len(results)} contenders")
    print(f"  Q8 ranks top-2:     {q8_top2:3d} / {len(results)} contenders")
    print(f"  delta range (Q8-baseline pp): min={q8_min_delta:+.1f}, median={q8_median_delta:+.1f}, max={q8_max_delta:+.1f}")
    print()
    print("Worst 5 perturbations for Q8:")
    for r in worst_for_q8:
        print(f"  {r['q8_minus_baseline']:+5.1f}pp  Q8={r['q8_overall']:.1f}%  base={r['baseline_overall']:.1f}%  {r['perturbation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
