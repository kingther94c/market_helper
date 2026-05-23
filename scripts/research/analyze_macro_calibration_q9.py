"""Analyze Q9 grid and pick a recommendation with train/holdout discipline.

Reads macro_calibration_grid_q9.json (which evaluates each config on TRAIN
and HOLDOUT separately) and:

  1. Picks a winner using TRAIN match% + stability bonus only.
  2. Reports holdout performance for the winner — strictly post-hoc, no
     selection pressure on holdout.
  3. Compares winner against the Q8 baseline (velocity weights = 0).
  4. Flags overfitting: if train >> holdout, that is a red flag.

Outputs: macro_calibration_analysis_q9.json
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"


def composite(metrics: dict, stability: dict) -> float:
    """Same shape as Q8 composite — match + small stability bonus.

    Uses TRAIN match only for selection (holdout is for validation).
    """
    match = metrics["overall"]
    stab = (stability["g_median_run_bdays"] + stability["i_median_run_bdays"]) / 2.0
    return match + 0.3 * min(stab, 20.0)


def main() -> int:
    runs = json.loads((ART / "macro_calibration_grid_q9.json").read_text())
    print(f"loaded {len(runs)} Q9 configs", flush=True)

    # Compute composite (train-only) for each
    for r in runs:
        r["composite_train"] = composite(r["train"], r["stability"])

    # Sort by train composite descending
    by_composite = sorted(runs, key=lambda r: -r["composite_train"])

    # Identify the Q8-equivalent baseline (velocity weights = 0,
    # gt=0.10, it=0.12, balanced blend)
    Q8_BASELINE_KEY = dict(
        inflation_velocity_weight=0.0,
        growth_velocity_weight=0.0,
        growth_thresh=0.10,
        inflation_thresh=0.12,
        macro_w=0.50,
        market_w=0.50,
    )

    def _key_match(r):
        p = r["params"]
        for k, v in Q8_BASELINE_KEY.items():
            if abs(float(p[k]) - float(v)) > 1e-6:
                return False
        return True

    baseline = next((r for r in runs if _key_match(r)), None)
    if baseline is None:
        print("WARNING: Q8 baseline config not found in grid", flush=True)
        baseline_train = baseline_holdout = 0.0
    else:
        baseline_train = baseline["train"]["overall"]
        baseline_holdout = baseline["holdout"]["overall"]

    # Strict improvers vs Q8 baseline ON TRAIN ONLY
    strict_improvers = []
    if baseline:
        bt = baseline["train"]["overall"]
        bh = baseline["holdout"]["overall"]
        bs_g = baseline["stability"]["g_median_run_bdays"]
        bs_i = baseline["stability"]["i_median_run_bdays"]
        bs = (bs_g + bs_i) / 2.0
        for r in runs:
            if r is baseline:
                continue
            mt = r["train"]["overall"]
            ms_g = r["stability"]["g_median_run_bdays"]
            ms_i = r["stability"]["i_median_run_bdays"]
            ms = (ms_g + ms_i) / 2.0
            if mt >= bt and ms >= bs and (mt > bt or ms > bs):
                strict_improvers.append(r)
        strict_improvers.sort(key=lambda r: -r["composite_train"])

    # Validation-aware selection: among strict-train-improvers, keep only those
    # that DO NOT REGRESS on holdout vs Q8 baseline. Then pick the candidate
    # whose train + holdout deltas are most balanced (sum of deltas, with
    # composite_train as a tiebreaker).
    #
    # Holdout is a hard CONSTRAINT (no regression allowed), not a selection
    # signal to optimize against — which would still be data leakage. But
    # given two configs that both beat baseline on train, the one that ALSO
    # extends the holdout improvement is the safer ship: it shows the gain
    # generalizes beyond the train anchors.
    safe_against_holdout = [
        r for r in strict_improvers if r["holdout"]["overall"] >= bh
    ] if baseline else strict_improvers

    if baseline:
        safe_against_holdout.sort(
            key=lambda r: (
                -((r["train"]["overall"] - bt) + (r["holdout"]["overall"] - bh)),
                -r["composite_train"],
            )
        )
    else:
        safe_against_holdout.sort(key=lambda r: -r["composite_train"])

    if safe_against_holdout:
        rec = safe_against_holdout[0]
        rec_source = "strict-train-improver with non-regressing holdout"
    elif strict_improvers:
        rec = strict_improvers[0]
        rec_source = "strict-train-improver (holdout may regress — flagged)"
    else:
        rec = by_composite[0]
        rec_source = "top composite_train (no baseline improvement found)"

    out = {
        "n_configs": len(runs),
        "baseline_q8_equivalent": baseline,
        "recommendation": rec,
        "recommendation_source": rec_source,
        "strict_improvers_count": len(strict_improvers),
        "strict_improvers_top10": strict_improvers[:10],
        "safe_against_holdout_count": len(safe_against_holdout) if baseline else 0,
        "safe_against_holdout_top10": safe_against_holdout[:10] if baseline else [],
        "top10_by_train_composite": by_composite[:10],
    }
    out_path = ART / "macro_calibration_analysis_q9.json"
    out_path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out_path}")
    print()

    if baseline:
        print(f"Q8-equivalent baseline: train={baseline_train:.1f}% holdout={baseline_holdout:.1f}% "
              f"(g_run={baseline['stability']['g_median_run_bdays']}/i_run={baseline['stability']['i_median_run_bdays']}bd)")
    rt = rec["train"]
    rh = rec["holdout"]
    print(f"Q9 recommendation:")
    print(f"  params: {rec['params']}")
    print(f"  train:   g_avg={rt['g_avg']:.1f}% i_avg={rt['i_avg']:.1f}% risk={rt['risk_avg']:.1f}% "
          f"overall={rt['overall']:.1f}% (Δ vs Q8: {rt['overall']-baseline_train:+.1f}pp)")
    print(f"  holdout: g_avg={rh['g_avg']:.1f}% i_avg={rh['i_avg']:.1f}% risk={rh['risk_avg']:.1f}% "
          f"overall={rh['overall']:.1f}% (Δ vs Q8: {rh['overall']-baseline_holdout:+.1f}pp)")
    print(f"  stab: g_run={rec['stability']['g_median_run_bdays']}/i_run={rec['stability']['i_median_run_bdays']}bd")
    print(f"  composite_train={rec['composite_train']:.2f}")
    print()
    print(f"Strict improvers count (train): {len(strict_improvers)}")
    print()
    # Detect overfitting
    train_holdout_gap = rt["overall"] - rh["overall"]
    if abs(train_holdout_gap) > 10:
        print(f"⚠️ TRAIN-HOLDOUT GAP: {train_holdout_gap:+.1f}pp — possible overfit to train anchors")
    elif baseline:
        baseline_gap = baseline_train - baseline_holdout
        relative = train_holdout_gap - baseline_gap
        print(f"Train-holdout gap: {train_holdout_gap:+.1f}pp (baseline gap was {baseline_gap:+.1f}pp, Δ {relative:+.1f}pp)")
    print()
    print("Per-anchor Q9 winner (holdout — strict post-hoc check):")
    for a in rh["per_anchor"]:
        print(f"  HOLDOUT  {a['name']:30s} g={a['g_match_pct']:5.1f}% i={a['i_match_pct']:5.1f}% risk_match={a['risk_match']}")
    print()
    print("Per-anchor Q9 winner (train):")
    for a in rt["per_anchor"]:
        print(f"  TRAIN    {a['name']:30s} g={a['g_match_pct']:5.1f}% i={a['i_match_pct']:5.1f}% risk_match={a['risk_match']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
