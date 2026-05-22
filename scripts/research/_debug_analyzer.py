"""Debug why analyzer picked a sub-optimal recommendation."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
d = json.loads((REPO / "data/research_artifacts/macro_calibration_analysis.json").read_text())

print(f"n_configs: {d['n_configs']}")
print(f"strict_improvers_count: {d['strict_improvers_count']}")
print(f"pareto_front_count: {d['pareto_front_count']}")
print(f"safe_count: {d['safe_count']}")
print()
print(f"recommendation: composite={d['recommendation']['composite']:.2f}")
print(f"  params: {d['recommendation']['params']}")
m = d['recommendation']['metrics']
print(f"  match: g={m['g_avg_match_pct']} i={m['i_avg_match_pct']} risk={m['risk_avg_match_pct']} overall={m['overall_avg_match_pct']}")
print(f"  stab: g_run={m['g_median_run_bdays']} i_run={m['i_median_run_bdays']}")
print()
print(f"top 5 strict_improvers:")
for i, p in enumerate(d['strict_improvers_top10'][:5], 1):
    pm = p['metrics']
    print(f"  #{i}: comp={p['composite']:.2f} overall={pm['overall_avg_match_pct']:.1f}% runs={pm['g_median_run_bdays']}/{pm['i_median_run_bdays']}bd "
          f"blend={p['params']['blend_name']} gt={p['params']['growth_thresh']} it={p['params']['inflation_thresh']} mw={p['params']['min_weight']}")
print()
print(f"top 5 by composite (top10_composite):")
for i, p in enumerate(d['top10_composite'][:5], 1):
    pm = p['metrics']
    print(f"  #{i}: comp={p['composite']:.2f} overall={pm['overall_avg_match_pct']:.1f}% is_baseline={p.get('is_baseline')} "
          f"blend={p['params']['blend_name']} gt={p['params']['growth_thresh']} it={p['params']['inflation_thresh']} mw={p['params']['min_weight']}")
