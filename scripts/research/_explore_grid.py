"""Explore the grid more deeply — look at top configs by various criteria."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
d = json.loads((REPO / "data/research_artifacts/macro_calibration_grid.json").read_text())

# Best 10 by overall match
print("Top 10 by overall_avg_match_pct:")
top = sorted(d, key=lambda r: -r["overall_avg_match_pct"])[:10]
for i, r in enumerate(top, 1):
    p = r["params"]
    print(f"  #{i:2d}: overall={r['overall_avg_match_pct']:5.1f}% g={r['g_avg_match_pct']:5.1f}% i={r['i_avg_match_pct']:5.1f}% risk={r['risk_avg_match_pct']:5.1f}% "
          f"runs(g/i)={r['g_median_run_bdays']}/{r['i_median_run_bdays']}bd | "
          f"mw={p['min_weight']} gt={p['growth_thresh']} it={p['inflation_thresh']} h={p['axis_min_consecutive']} blend={p['blend_name']}")

# Best by combined match - stability tradeoff
print()
print("Top 10 by composite (match + 0.5*stab):")
def composite(r):
    return r["overall_avg_match_pct"] + 0.5 * min((r["g_median_run_bdays"] + r["i_median_run_bdays"]) / 2.0, 60)
top2 = sorted(d, key=lambda r: -composite(r))[:10]
for i, r in enumerate(top2, 1):
    p = r["params"]
    print(f"  #{i:2d}: comp={composite(r):5.1f} overall={r['overall_avg_match_pct']:5.1f}% runs(g/i)={r['g_median_run_bdays']}/{r['i_median_run_bdays']}bd | "
          f"mw={p['min_weight']} gt={p['growth_thresh']} it={p['inflation_thresh']} h={p['axis_min_consecutive']} blend={p['blend_name']}")

# Best with stable runs (g_run >= 5)
print()
print("Top 10 with g_median_run >= 5 by overall_match:")
stable = [r for r in d if r["g_median_run_bdays"] >= 5 and r["i_median_run_bdays"] >= 5]
print(f"  ({len(stable)} configs qualify)")
top3 = sorted(stable, key=lambda r: -r["overall_avg_match_pct"])[:10]
for i, r in enumerate(top3, 1):
    p = r["params"]
    print(f"  #{i:2d}: overall={r['overall_avg_match_pct']:5.1f}% runs(g/i)={r['g_median_run_bdays']}/{r['i_median_run_bdays']}bd | "
          f"mw={p['min_weight']} gt={p['growth_thresh']} it={p['inflation_thresh']} h={p['axis_min_consecutive']} blend={p['blend_name']}")

# Baseline reference
for r in d:
    p = r["params"]
    if p["min_weight"] == 0.65 and p["growth_thresh"] == 0.15 and p["inflation_thresh"] == 0.12 and p["axis_min_consecutive"] == 5 and p["blend_name"] == "baseline_macro_light":
        print()
        print(f"BASELINE: overall={r['overall_avg_match_pct']:.1f}% g={r['g_avg_match_pct']:.1f}% i={r['i_avg_match_pct']:.1f}% "
              f"risk={r['risk_avg_match_pct']:.1f}% runs={r['g_median_run_bdays']}/{r['i_median_run_bdays']}bd composite={composite(r):.1f}")
        break
