"""Phase 1+2 unified neighborhood-stability analysis.

Same logic as macro_neighborhood_stability.py but derives the grid-step
lists from the loaded data rather than hardcoding them. Works on:
  - the original 360-config Q9 grid (macro_calibration_grid_q9.json)
  - the augmented 522-config refined grid (macro_calibration_grid_q9_refined.json)

Selects winner by the user-confirmed rule:
  - L1 neighbors (same layer_blend, ±1 step on exactly one of 4 cont. dims)
  - Top metric: median(neighbor train_overall)
  - No bad neighbor: min(neighbor train) >= max(baseline_train, self - 5pp)
  - Filters: n_neighbors >= 4, holdout_non_regress, self_train > baseline
  - Rank: robust_train = mean(self_train, neighbor_median_train)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean, median

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"

# CLI: --grid <path> --out <path>
import argparse
ap = argparse.ArgumentParser()
ap.add_argument("--grid", default=str(ART / "macro_calibration_grid_q9.json"))
ap.add_argument("--out", default=str(ART / "macro_neighborhood_q9_v2.json"))
ap.add_argument("--max-worst-drop-pp", type=float, default=5.0)
args = ap.parse_args()

GRID = Path(args.grid)
OUT = Path(args.out)
MAX_WORST_DROP_PP = float(args.max_worst_drop_pp)


Q8_BASELINE_KEY = dict(
    inflation_velocity_weight=0.0,
    growth_velocity_weight=0.0,
    growth_thresh=0.10,
    inflation_thresh=0.12,
    macro_w=0.5,
    market_w=0.5,
)
Q9_WINNER_KEY = dict(
    inflation_velocity_weight=1.0,
    growth_velocity_weight=0.0,
    growth_thresh=0.10,
    inflation_thresh=0.15,
    macro_w=0.6,
    market_w=0.4,
)


def _is_baseline(p):
    return all(abs(float(p[k]) - float(v)) < 1e-6 for k, v in Q8_BASELINE_KEY.items())


def _is_q9_winner(p):
    return all(abs(float(p[k]) - float(v)) < 1e-6 for k, v in Q9_WINNER_KEY.items())


def _blend_key(p):
    return (round(float(p["macro_w"]), 4), round(float(p["market_w"]), 4))


def _derive_steps(runs, key):
    """Sorted unique values for a continuous param across all configs."""
    return sorted({round(float(r["params"][key]), 6) for r in runs})


def _idx(steps, v):
    target = round(float(v), 6)
    for i, s in enumerate(steps):
        if abs(s - target) < 1e-6:
            return i
    raise ValueError(f"{v} not in {steps}")


def main() -> int:
    runs = json.loads(GRID.read_text(encoding="utf-8"))
    print(f"loaded {len(runs)} configs from {GRID.name}", flush=True)

    # Derive step lists from data
    ivw_steps = _derive_steps(runs, "inflation_velocity_weight")
    gvw_steps = _derive_steps(runs, "growth_velocity_weight")
    gt_steps = _derive_steps(runs, "growth_thresh")
    it_steps = _derive_steps(runs, "inflation_thresh")
    print(f"step lists:")
    print(f"  ivw: {ivw_steps}")
    print(f"  gvw: {gvw_steps}")
    print(f"  gt:  {gt_steps}")
    print(f"  it:  {it_steps}")
    print(f"  blends: {sorted({_blend_key(r['params']) for r in runs})}")
    print()

    # Build coord lookup. Coord = (ivw_idx, gvw_idx, gt_idx, it_idx, blend_key).
    by_coord = {}
    for r in runs:
        p = r["params"]
        c = (
            _idx(ivw_steps, p["inflation_velocity_weight"]),
            _idx(gvw_steps, p["growth_velocity_weight"]),
            _idx(gt_steps, p["growth_thresh"]),
            _idx(it_steps, p["inflation_thresh"]),
            _blend_key(p),
        )
        by_coord[c] = r
    all_coords = set(by_coord.keys())

    baseline = next((r for r in runs if _is_baseline(r["params"])), None)
    if not baseline:
        raise SystemExit("Q8-equivalent baseline not in grid")
    bt = baseline["train"]["overall"]
    bh = baseline["holdout"]["overall"]
    print(f"baseline: train={bt:.1f}% holdout={bh:.1f}%", flush=True)
    print()

    def _l1_neighbors(c):
        out = []
        dims = [
            (c[0], ivw_steps), (c[1], gvw_steps),
            (c[2], gt_steps), (c[3], it_steps),
        ]
        for d, (val, steps) in enumerate(dims):
            for delta in (-1, +1):
                nv = val + delta
                if not (0 <= nv < len(steps)):
                    continue
                nbr = list(c)
                nbr[d] = nv
                nt = tuple(nbr)
                if nt in all_coords:
                    out.append(nt)
        return out

    annotated = []
    for r in runs:
        p = r["params"]
        c = (
            _idx(ivw_steps, p["inflation_velocity_weight"]),
            _idx(gvw_steps, p["growth_velocity_weight"]),
            _idx(gt_steps, p["growth_thresh"]),
            _idx(it_steps, p["inflation_thresh"]),
            _blend_key(p),
        )
        nbrs = _l1_neighbors(c)
        nbr_runs = [by_coord[n] for n in nbrs]

        nbr_train = [n["train"]["overall"] for n in nbr_runs]
        nbr_holdout = [n["holdout"]["overall"] for n in nbr_runs]

        self_train = r["train"]["overall"]
        self_holdout = r["holdout"]["overall"]
        if nbr_train:
            ntm = median(nbr_train); ntmean = mean(nbr_train)
            ntmin = min(nbr_train); ntmax = max(nbr_train)
        else:
            ntm = ntmean = ntmin = ntmax = self_train
        if nbr_holdout:
            nhm = median(nbr_holdout); nhmin = min(nbr_holdout)
        else:
            nhm = nhmin = self_holdout
        bad_floor = max(bt, self_train - MAX_WORST_DROP_PP)
        no_bad = bool(nbrs) and (ntmin >= bad_floor)
        robust = (self_train + ntm) / 2.0

        annotated.append({
            "params": p,
            "self_train": self_train,
            "self_holdout": self_holdout,
            "stability_g_run": r["stability"]["g_median_run_bdays"],
            "stability_i_run": r["stability"]["i_median_run_bdays"],
            "n_neighbors": len(nbrs),
            "nbr_train_median": round(ntm, 2),
            "nbr_train_mean": round(ntmean, 2),
            "nbr_train_min": round(ntmin, 2),
            "nbr_train_max": round(ntmax, 2),
            "nbr_train_spread": round(ntmax - ntmin, 2),
            "nbr_holdout_median": round(nhm, 2),
            "nbr_holdout_min": round(nhmin, 2),
            "no_bad_neighbor": no_bad,
            "robust_train": round(robust, 2),
            "holdout_non_regress": self_holdout >= bh,
            "is_q8_baseline": _is_baseline(p),
            "is_q9_winner": _is_q9_winner(p),
        })

    eligible = [
        a for a in annotated
        if a["n_neighbors"] >= 4
        and a["holdout_non_regress"]
        and a["self_train"] > bt
        and a["no_bad_neighbor"]
    ]
    eligible.sort(key=lambda a: (-a["robust_train"], -a["self_train"]))

    by_filter = {
        "total": len(annotated),
        "n_neighbors_ge_4": sum(1 for a in annotated if a["n_neighbors"] >= 4),
        "holdout_non_regress": sum(1 for a in annotated if a["holdout_non_regress"]),
        "self_train_gt_baseline": sum(1 for a in annotated if a["self_train"] > bt),
        "no_bad_neighbor": sum(1 for a in annotated if a["no_bad_neighbor"]),
        "all_combined": len(eligible),
    }
    print("Filter cascade:")
    for f, n in by_filter.items():
        print(f"  {f:28s}: {n}/{len(annotated)}")
    print()

    q9 = next((a for a in annotated if a["is_q9_winner"]), None)
    if q9:
        rank = next((i for i, a in enumerate(eligible, 1) if a["is_q9_winner"]), None)
        print(f"Q9 winner annotation:")
        print(f"  self_train={q9['self_train']:.1f}% self_holdout={q9['self_holdout']:.1f}%")
        print(f"  nbr_train (median/min/max): {q9['nbr_train_median']:.1f} / {q9['nbr_train_min']:.1f} / {q9['nbr_train_max']:.1f}  (n={q9['n_neighbors']})")
        print(f"  nbr_holdout (median/min): {q9['nbr_holdout_median']:.1f} / {q9['nbr_holdout_min']:.1f}")
        print(f"  no_bad_neighbor: {q9['no_bad_neighbor']}, holdout_non_regress: {q9['holdout_non_regress']}")
        print(f"  robust_train: {q9['robust_train']:.1f}")
        print(f"  rank among eligible: {rank if rank else 'NOT eligible'}")
        print()

    print("Top 15 by robust_train (neighborhood-stable selection):")
    print(f"{'#':3s} {'ivw':5s} {'gvw':5s} {'gt':5s} {'it':5s} {'m/m':10s} | {'self_T':6s} {'nbr_med_T':9s} {'nbr_min_T':9s} {'self_H':6s} {'nbr_min_H':9s} | {'robust':6s} {'mark':6s}")
    print("-" * 122)
    for i, a in enumerate(eligible[:15], 1):
        p = a["params"]
        mark = ""
        if a["is_q8_baseline"]: mark = "Q8"
        if a["is_q9_winner"]:   mark = "Q9*"
        print(f"{i:3d} {p['inflation_velocity_weight']:5.2f} {p['growth_velocity_weight']:5.2f} "
              f"{p['growth_thresh']:5.2f} {p['inflation_thresh']:5.2f} "
              f"{p['macro_w']:.2f}/{p['market_w']:.2f}  | "
              f"{a['self_train']:6.1f} {a['nbr_train_median']:9.1f} {a['nbr_train_min']:9.1f} "
              f"{a['self_holdout']:6.1f} {a['nbr_holdout_min']:9.1f} | "
              f"{a['robust_train']:6.1f} {mark:6s}")

    out = {
        "n_configs": len(runs),
        "grid_file": str(GRID),
        "step_lists": {
            "ivw": ivw_steps, "gvw": gvw_steps,
            "gt": gt_steps, "it": it_steps,
        },
        "baseline_train": bt,
        "baseline_holdout": bh,
        "rules": {
            "neighborhood": "L1 grid-index, same layer_blend, ±1 step in one of 4 continuous dims",
            "top_metric": "median(neighbor train_overall)",
            "no_bad_neighbor": f"min(neighbor train) >= max(baseline_train, self - {MAX_WORST_DROP_PP}pp)",
            "filters": "n_neighbors >= 4 AND holdout_non_regress AND self_train > baseline AND no_bad_neighbor",
            "ranking": "robust_train = mean(self_train, neighbor_median_train)",
        },
        "filter_cascade": by_filter,
        "q9_winner_annot": q9,
        "q9_winner_rank_among_eligible": (
            next((i for i, a in enumerate(eligible, 1) if a["is_q9_winner"]), None) if q9 else None
        ),
        "top10_robust": eligible[:10],
        "annotated_all": annotated,
    }
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")

    # Verdict
    print()
    if not eligible:
        print("VERDICT: no candidate passes all filters. Phase analysis inconclusive.")
    elif q9 and eligible[0]["is_q9_winner"]:
        print("VERDICT: current Q9 winner is also the neighborhood-robust top — confirmed.")
    else:
        nbr = eligible[0]
        delta = nbr["robust_train"] - (q9["robust_train"] if q9 else nbr["robust_train"])
        print(f"VERDICT: top robust differs from Q9 winner. Δ robust_train = {delta:+.1f}pp")
        if q9:
            h_delta = nbr["self_holdout"] - q9["self_holdout"]
            print(f"  Q9 winner:  self_train={q9['self_train']:.1f}% self_holdout={q9['self_holdout']:.1f}%")
            print(f"  Top robust: self_train={nbr['self_train']:.1f}% self_holdout={nbr['self_holdout']:.1f}%")
            print(f"  Δ holdout (top - Q9) = {h_delta:+.1f}pp")
            print(f"  Decision: if top robust ALSO has holdout ≥ Q9 winner's holdout, switch.")
            print(f"            Else: Q9 winner trades train-robustness for holdout — keep Q9.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
