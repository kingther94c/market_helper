"""Dig into top Q9 configs to understand train/holdout trade-off."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"

runs = json.loads((ART / "macro_calibration_grid_q9.json").read_text())
print(f"loaded {len(runs)} runs")
print()

Q8_KEY = dict(inflation_velocity_weight=0.0, growth_velocity_weight=0.0,
              growth_thresh=0.10, inflation_thresh=0.12, macro_w=0.5, market_w=0.5)

def _is_q8(r):
    p = r["params"]
    return all(abs(float(p[k]) - float(v)) < 1e-6 for k, v in Q8_KEY.items())

q8 = next((r for r in runs if _is_q8(r)), None)
print(f"Q8 baseline: train={q8['train']['overall']:.1f}% holdout={q8['holdout']['overall']:.1f}% gap={q8['train']['overall']-q8['holdout']['overall']:+.1f}pp")
print()

# Top 15 by train
print("Top 15 by TRAIN overall:")
top_train = sorted(runs, key=lambda r: -r["train"]["overall"])[:15]
for i, r in enumerate(top_train, 1):
    p = r["params"]
    gap = r["train"]["overall"] - r["holdout"]["overall"]
    mark = "Q8" if _is_q8(r) else "  "
    print(f"  #{i:2d} {mark}: train={r['train']['overall']:.1f}% holdout={r['holdout']['overall']:.1f}% gap={gap:+.1f}pp  ivw={p['inflation_velocity_weight']} gvw={p['growth_velocity_weight']} gt={p['growth_thresh']} it={p['inflation_thresh']} m/m={p['macro_w']}/{p['market_w']}")
print()

# Top 15 by HOLDOUT (post-hoc curiosity, not selection signal)
print("Top 15 by HOLDOUT overall (NOT a selection signal; post-hoc only):")
top_h = sorted(runs, key=lambda r: -r["holdout"]["overall"])[:15]
for i, r in enumerate(top_h, 1):
    p = r["params"]
    gap = r["train"]["overall"] - r["holdout"]["overall"]
    mark = "Q8" if _is_q8(r) else "  "
    print(f"  #{i:2d} {mark}: holdout={r['holdout']['overall']:.1f}% train={r['train']['overall']:.1f}% gap={gap:+.1f}pp  ivw={p['inflation_velocity_weight']} gvw={p['growth_velocity_weight']} gt={p['growth_thresh']} it={p['inflation_thresh']} m/m={p['macro_w']}/{p['market_w']}")
print()

# Top 15 by joint (min of train and holdout) — proxy for "best both"
print("Top 15 by MIN(train, holdout):")
top_min = sorted(runs, key=lambda r: -min(r["train"]["overall"], r["holdout"]["overall"]))[:15]
for i, r in enumerate(top_min, 1):
    p = r["params"]
    gap = r["train"]["overall"] - r["holdout"]["overall"]
    mark = "Q8" if _is_q8(r) else "  "
    print(f"  #{i:2d} {mark}: min={min(r['train']['overall'],r['holdout']['overall']):.1f}% train={r['train']['overall']:.1f}% holdout={r['holdout']['overall']:.1f}% gap={gap:+.1f}pp  ivw={p['inflation_velocity_weight']} gvw={p['growth_velocity_weight']} gt={p['growth_thresh']} it={p['inflation_thresh']} m/m={p['macro_w']}/{p['market_w']}")
print()

# Configs that strictly improve BOTH train and holdout vs Q8 baseline
print("Configs that beat Q8 on BOTH train AND holdout:")
both_better = [r for r in runs if not _is_q8(r)
               and r["train"]["overall"] > q8["train"]["overall"]
               and r["holdout"]["overall"] > q8["holdout"]["overall"]]
both_better.sort(key=lambda r: -(r["train"]["overall"] + r["holdout"]["overall"]))
print(f"  count: {len(both_better)}")
for i, r in enumerate(both_better[:10], 1):
    p = r["params"]
    print(f"  #{i}: train={r['train']['overall']:.1f}% (+{r['train']['overall']-q8['train']['overall']:.1f}) "
          f"holdout={r['holdout']['overall']:.1f}% (+{r['holdout']['overall']-q8['holdout']['overall']:.1f}) "
          f"ivw={p['inflation_velocity_weight']} gvw={p['growth_velocity_weight']} gt={p['growth_thresh']} it={p['inflation_thresh']} m/m={p['macro_w']}/{p['market_w']}")
