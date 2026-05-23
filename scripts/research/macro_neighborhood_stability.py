"""Phase 1 — neighborhood-stability analysis on the Q9 macro grid.

Rationale (user-driven critique of the original argmax selection):

  The grid winner is the maximum of a sample of a noisy response
  surface. A point that wins by a 0.5pp margin against its neighbors
  may sit on a noise spike — when we revisit or perturb, it collapses.
  A robust optimum is one whose *neighborhood median* is in the top
  tier AND whose worst neighbor is not catastrophically bad.

Neighborhood definition (L1, deliberate):
  Two configs are neighbors iff they share the same `layer_blend`
  (categorical — not a continuous dim) AND differ on exactly ONE of
  the four continuous dims (ivw, gvw, gt, it) by exactly ONE grid
  step. Max 8 neighbors (4 dims × ±1), fewer at grid corners.

  Why same-blend: layer_blend is a discrete choice (macro/market =
  50/50 or 60/40), not a marginal perturbation. Crossing it would
  compare apples to oranges in the neighborhood stat.

Top-of-neighborhood metric: median(neighbor train_overall).
  Median (vs mean) is robust to a single outlier neighbor pulling the
  stat up or down — we want central tendency, not best-or-worst case.

"No particularly bad point" rule (conjunction):
  - min(neighbor train_overall) >= baseline_train  (no regress-baseline
    neighbor)
  - min(neighbor train_overall) >= self_train - 5.0  (worst neighbor
    within 5pp of the candidate itself)

Train/holdout discipline: all neighborhood stats computed separately on
train and holdout. Selection still uses only train signal (holdout is
hard non-regression constraint, never optimization objective). Holdout
neighborhood stats are reported post-hoc.

Output:
  data/research_artifacts/macro_neighborhood_q9.json — raw analysis
  Console: top-K by neighborhood-median, side-by-side vs argmax winner.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, median
from typing import Sequence

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"
GRID = ART / "macro_calibration_grid_q9.json"
OUT = ART / "macro_neighborhood_q9.json"

# Grid axes (must match macro_calibration_grid_q9.py)
IVW_STEPS = [0.0, 0.3, 0.5, 0.7, 1.0]
GVW_STEPS = [0.0, 0.3, 0.5, 0.7]
GT_STEPS = [0.10, 0.12, 0.15]
IT_STEPS = [0.10, 0.12, 0.15]
BLEND_KEY = lambda p: (round(float(p["macro_w"]), 3), round(float(p["market_w"]), 3))

Q8_BASELINE_KEY = dict(
    inflation_velocity_weight=0.0,
    growth_velocity_weight=0.0,
    growth_thresh=0.10,
    inflation_thresh=0.12,
    macro_w=0.5,
    market_w=0.5,
)

# User-confirmed thresholds
MAX_WORST_DROP_PP = 5.0  # worst neighbor must be within 5pp of self


def _idx_in(steps: Sequence[float], v: float) -> int:
    for i, s in enumerate(steps):
        if abs(float(s) - float(v)) < 1e-6:
            return i
    raise ValueError(f"value {v} not in steps {steps}")


def _coord(p: dict) -> tuple:
    """Grid-index coordinate (ivw_idx, gvw_idx, gt_idx, it_idx, blend_key)."""
    return (
        _idx_in(IVW_STEPS, p["inflation_velocity_weight"]),
        _idx_in(GVW_STEPS, p["growth_velocity_weight"]),
        _idx_in(GT_STEPS, p["growth_thresh"]),
        _idx_in(IT_STEPS, p["inflation_thresh"]),
        BLEND_KEY(p),
    )


def _is_q8_baseline(p: dict) -> bool:
    return all(
        abs(float(p[k]) - float(v)) < 1e-6 for k, v in Q8_BASELINE_KEY.items()
    )


def _l1_neighbors(coord: tuple, all_coords: set) -> list[tuple]:
    """Same blend, ±1 step in exactly one of the 4 continuous dims."""
    ivw, gvw, gt, it, blend = coord
    out = []
    for d, (val, steps) in enumerate(
        [(ivw, IVW_STEPS), (gvw, GVW_STEPS), (gt, GT_STEPS), (it, IT_STEPS)]
    ):
        for delta in (-1, +1):
            new_val = val + delta
            if not (0 <= new_val < len(steps)):
                continue
            nbr = list(coord)
            nbr[d] = new_val
            nbr_t = tuple(nbr)
            if nbr_t in all_coords:
                out.append(nbr_t)
    return out


def main() -> int:
    runs = json.loads(GRID.read_text(encoding="utf-8"))
    print(f"loaded {len(runs)} configs", flush=True)

    by_coord = {_coord(r["params"]): r for r in runs}
    all_coords = set(by_coord.keys())

    baseline = next((r for r in runs if _is_q8_baseline(r["params"])), None)
    if baseline is None:
        raise SystemExit("Q8-equivalent baseline not in grid")
    bt = baseline["train"]["overall"]
    bh = baseline["holdout"]["overall"]
    print(f"baseline (Q8-equivalent): train={bt:.1f}% holdout={bh:.1f}%", flush=True)
    print()

    annotated = []
    for r in runs:
        c = _coord(r["params"])
        nbrs = _l1_neighbors(c, all_coords)
        nbr_runs = [by_coord[n] for n in nbrs]

        nbr_train = [n["train"]["overall"] for n in nbr_runs]
        nbr_holdout = [n["holdout"]["overall"] for n in nbr_runs]

        self_train = r["train"]["overall"]
        self_holdout = r["holdout"]["overall"]

        # Stability stats
        nbr_train_median = median(nbr_train) if nbr_train else self_train
        nbr_train_mean = mean(nbr_train) if nbr_train else self_train
        nbr_train_min = min(nbr_train) if nbr_train else self_train
        nbr_train_max = max(nbr_train) if nbr_train else self_train
        nbr_holdout_median = median(nbr_holdout) if nbr_holdout else self_holdout
        nbr_holdout_min = min(nbr_holdout) if nbr_holdout else self_holdout

        # Decision metrics:
        #   - "neighborhood top score" = median of neighbors on train
        #   - "no bad neighbor" = min(neighbor train) >= max(baseline, self - 5pp)
        bad_floor = max(bt, self_train - MAX_WORST_DROP_PP)
        no_bad_neighbor = bool(nbrs) and (nbr_train_min >= bad_floor)

        # Robust score = average of (self, neighbor median) — emphasizes
        # that both self AND neighborhood center are high. Single number
        # for ranking.
        robust_train = (self_train + nbr_train_median) / 2.0

        annotated.append({
            "params": r["params"],
            "coord": list(c[:4]) + [list(c[4])],
            "self_train": self_train,
            "self_holdout": self_holdout,
            "stability_g_run": r["stability"]["g_median_run_bdays"],
            "stability_i_run": r["stability"]["i_median_run_bdays"],
            "n_neighbors": len(nbrs),
            "nbr_train_median": round(nbr_train_median, 2),
            "nbr_train_mean": round(nbr_train_mean, 2),
            "nbr_train_min": round(nbr_train_min, 2),
            "nbr_train_max": round(nbr_train_max, 2),
            "nbr_train_spread": round(nbr_train_max - nbr_train_min, 2),
            "nbr_holdout_median": round(nbr_holdout_median, 2),
            "nbr_holdout_min": round(nbr_holdout_min, 2),
            "no_bad_neighbor": no_bad_neighbor,
            "robust_train": round(robust_train, 2),
            "holdout_non_regress": self_holdout >= bh,
            "is_q8_baseline": _is_q8_baseline(r["params"]),
        })

    # ---------- Rankings ----------
    # 1. Current Q9 selection (argmax-style): max train, gated by
    #    (holdout >= baseline). Find current Q9 winner for comparison.
    Q9_KEY = dict(
        inflation_velocity_weight=1.0,
        growth_velocity_weight=0.0,
        growth_thresh=0.10,
        inflation_thresh=0.15,
        macro_w=0.6,
        market_w=0.4,
    )

    def _is_q9_winner(p):
        return all(
            abs(float(p[k]) - float(v)) < 1e-6 for k, v in Q9_KEY.items()
        )

    q9_winner_annot = next((a for a in annotated if _is_q9_winner(a["params"])), None)

    # 2. Neighborhood-robust selection:
    #    Filter to:
    #      - n_neighbors >= 4 (corners discarded — too few neighbors for the
    #        median to be informative; protects against edge effects)
    #      - holdout_non_regress (Q9 hard constraint)
    #      - self_train > bt (must still beat baseline on train)
    #      - no_bad_neighbor (no neighbor regresses baseline or drops > 5pp)
    #    Sort by:
    #      - robust_train (self + neighbor-median average) descending
    #      - secondary: self_train descending (break ties)
    eligible = [
        a for a in annotated
        if a["n_neighbors"] >= 4
        and a["holdout_non_regress"]
        and a["self_train"] > bt
        and a["no_bad_neighbor"]
    ]
    eligible.sort(key=lambda a: (-a["robust_train"], -a["self_train"]))

    # Diagnostic: how many candidates pass each filter individually?
    by_filter = {
        "n_neighbors_ge_4": sum(1 for a in annotated if a["n_neighbors"] >= 4),
        "holdout_non_regress": sum(1 for a in annotated if a["holdout_non_regress"]),
        "self_train_gt_baseline": sum(1 for a in annotated if a["self_train"] > bt),
        "no_bad_neighbor": sum(1 for a in annotated if a["no_bad_neighbor"]),
        "all_combined": len(eligible),
    }

    # ---------- Console output ----------
    print(f"Filter cascade:")
    for f, n in by_filter.items():
        print(f"  {f:28s}: {n}/{len(annotated)}")
    print()

    if q9_winner_annot:
        q = q9_winner_annot
        rank_in_eligible = next(
            (i for i, a in enumerate(eligible, 1) if a["params"] == q["params"]),
            None,
        )
        print(f"Current Q9 winner (argmax train + holdout non-regress):")
        print(f"  params: {q['params']}")
        print(f"  self_train={q['self_train']:.1f}% self_holdout={q['self_holdout']:.1f}%")
        print(f"  nbr_train (median/min/max): {q['nbr_train_median']:.1f} / {q['nbr_train_min']:.1f} / {q['nbr_train_max']:.1f}  (n={q['n_neighbors']})")
        print(f"  nbr_holdout (median/min): {q['nbr_holdout_median']:.1f} / {q['nbr_holdout_min']:.1f}")
        print(f"  no_bad_neighbor: {q['no_bad_neighbor']}, holdout_non_regress: {q['holdout_non_regress']}")
        print(f"  robust_train: {q['robust_train']:.1f}")
        print(f"  rank by robust_train among eligible: {rank_in_eligible if rank_in_eligible else 'NOT eligible'}")
        print()

    print("Top 15 by robust_train (neighborhood-stable selection):")
    print(f"{'#':3s} {'ivw':4s} {'gvw':4s} {'gt':5s} {'it':5s} {'m/m':8s} | {'self_T':6s} {'nbr_med_T':9s} {'nbr_min_T':9s} {'self_H':6s} {'nbr_min_H':9s} | {'robust':6s} {'mark':6s}")
    print("-" * 115)
    for i, a in enumerate(eligible[:15], 1):
        p = a["params"]
        mark = ""
        if a["is_q8_baseline"]:
            mark = "Q8"
        if q9_winner_annot and a["params"] == q9_winner_annot["params"]:
            mark = "Q9*"
        print(f"{i:3d} {p['inflation_velocity_weight']:4.1f} {p['growth_velocity_weight']:4.1f} "
              f"{p['growth_thresh']:5.2f} {p['inflation_thresh']:5.2f} "
              f"{p['macro_w']:.1f}/{p['market_w']:.1f}  | "
              f"{a['self_train']:6.1f} {a['nbr_train_median']:9.1f} {a['nbr_train_min']:9.1f} "
              f"{a['self_holdout']:6.1f} {a['nbr_holdout_min']:9.1f} | "
              f"{a['robust_train']:6.1f} {mark:6s}")

    # Compare top-3 robust candidates side by side
    top3 = eligible[:3]

    out = {
        "n_configs": len(runs),
        "baseline_train": bt,
        "baseline_holdout": bh,
        "rules": {
            "neighborhood": "L1 grid-index, same layer_blend, ±1 step in one of 4 continuous dims",
            "top_metric": "median(neighbor train_overall)",
            "no_bad_neighbor": f"min(neighbor train) >= max(baseline_train, self - {MAX_WORST_DROP_PP}pp)",
            "filters": "n_neighbors >= 4 AND holdout_non_regress AND self_train > baseline_train AND no_bad_neighbor",
            "ranking": "robust_train = mean(self_train, neighbor_median_train); secondary self_train",
        },
        "filter_cascade": by_filter,
        "q9_winner_annot": q9_winner_annot,
        "q9_winner_rank_among_eligible": (
            next((i for i, a in enumerate(eligible, 1)
                  if a["params"] == q9_winner_annot["params"]), None)
            if q9_winner_annot else None
        ),
        "top10_robust": eligible[:10],
        "annotated_all": annotated,
    }
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")

    # Verdict
    print()
    if not eligible:
        print("VERDICT: no candidate passes all filters. Phase 1 inconclusive.")
        print("→ Recommend: keep current Q9 winner, document neighborhood-instability as caveat.")
    elif q9_winner_annot and eligible[0]["params"] == q9_winner_annot["params"]:
        print("VERDICT: current Q9 winner is also the neighborhood-robust top.")
        print(f"→ Recommend: ship Q9 unchanged. {by_filter['all_combined']} eligible candidates;")
        print(f"   Q9 winner dominates on robust_train ({eligible[0]['robust_train']:.1f}).")
    else:
        nbr_winner = eligible[0]
        print(f"VERDICT: a different config dominates on neighborhood-robust score.")
        print(f"→ Phase-2 trigger if delta is meaningful.")
        if q9_winner_annot:
            delta = nbr_winner["robust_train"] - q9_winner_annot["robust_train"]
            print(f"   Q9 winner robust_train: {q9_winner_annot['robust_train']:.1f}")
            print(f"   New top  robust_train: {nbr_winner['robust_train']:.1f}")
            print(f"   Δ = {delta:+.1f}pp")
            if abs(delta) > 1.0:
                print(f"   → Material gap. Recommend Phase 2 (local refinement).")
            else:
                print(f"   → Marginal gap (<1pp). Within grid noise; consider keeping Q9.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
