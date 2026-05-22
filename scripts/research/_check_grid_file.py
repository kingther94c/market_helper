"""Quick check of grid file integrity (n configs, range of metrics)."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
d = json.loads((REPO / "data/research_artifacts/macro_calibration_grid.json").read_text())
print(f"configs: {len(d)}")
print(f"first params: {d[0]['params']}")
print(f"last params: {d[-1]['params']}")

# Best by each metric
best_g = max(d, key=lambda r: r["g_avg_match_pct"])
best_i = max(d, key=lambda r: r["i_avg_match_pct"])
best_overall = max(d, key=lambda r: r["overall_avg_match_pct"])
best_stab = max(d, key=lambda r: r["g_median_run_bdays"] + r["i_median_run_bdays"])
print()
print(f"best g_match: {best_g['g_avg_match_pct']}% — {best_g['params']}")
print(f"best i_match: {best_i['i_avg_match_pct']}% — {best_i['params']}")
print(f"best overall: {best_overall['overall_avg_match_pct']}% — {best_overall['params']}")
print(f"best stability: g={best_stab['g_median_run_bdays']}bd i={best_stab['i_median_run_bdays']}bd — {best_stab['params']}")

# Find baseline
for r in d:
    p = r["params"]
    if p["min_weight"] == 0.65 and p["growth_thresh"] == 0.15 and p["inflation_thresh"] == 0.12 and p["axis_min_consecutive"] == 5 and p["blend_name"] == "baseline_macro_light":
        print()
        print(f"BASELINE: g={r['g_avg_match_pct']}% i={r['i_avg_match_pct']}% risk={r['risk_avg_match_pct']}% overall={r['overall_avg_match_pct']}% g_run={r['g_median_run_bdays']}bd i_run={r['i_median_run_bdays']}bd")
        break
else:
    print("BASELINE NOT FOUND in grid")
