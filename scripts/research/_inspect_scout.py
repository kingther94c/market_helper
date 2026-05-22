"""Quick inspector that pretty-prints the baseline scout output."""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
d = json.loads((REPO / "data/research_artifacts/macro_scout.json").read_text())

print()
print("=" * 130)
print(f"{'anchor':30s} | {'g_exp':7s} g_score(mean/min/max)  macro_g mkt_g | {'i_exp':7s} i_score(mean/min/max)  macro_i mkt_i | risk")
print("-" * 130)
for a in d["anchor_results"]:
    g_box = f"{a['g_mean_score']:+.2f}/{a['g_min_score']:+.2f}/{a['g_max_score']:+.2f}"
    i_box = f"{a['i_mean_score']:+.2f}/{a['i_min_score']:+.2f}/{a['i_max_score']:+.2f}"
    mg = a["macro_g_mean"] or 0.0
    mi = a["macro_i_mean"] or 0.0
    risk_actual = "On" if a["stress_days_pct"] > 0 else "Off"
    print(
        f"{a['name']:30s} | {a['g_consensus']:7s} {g_box:21s} {mg:+.2f}              "
        f"| {a['i_consensus']:7s} {i_box:21s} {mi:+.2f}              "
        f"| exp={a['risk_consensus']} act={risk_actual} {a['stress_days_pct']:.0f}%"
    )
print()
print(f"Thresholds: {d['thresholds']}")
print(f"Stability:")
s = d["stability"]
print(f"  growth state: median={s['growth_median_run_bdays']:.0f}bd mean={s['growth_mean_run_bdays']:.1f} n_runs={s['growth_n_runs']}")
print(f"  infl state:   median={s['infl_median_run_bdays']:.0f}bd mean={s['infl_mean_run_bdays']:.1f} n_runs={s['infl_n_runs']}")
print(f"  quadrant:     median={s['quadrant_median_run_bdays']:.0f}bd mean={s['quadrant_mean_run_bdays']:.1f} n_runs={s['quadrant_n_runs']}")
print()
print("=== Diagnosis hints ===")
for a in d["anchor_results"]:
    issues = []
    if a["g_match_pct"] < 60:
        issues.append(f"g_match={a['g_match_pct']:.0f}%")
    if a["i_match_pct"] < 60:
        issues.append(f"i_match={a['i_match_pct']:.0f}%")
    if not a["risk_match"]:
        issues.append(f"risk={a['risk_consensus']}/!={'On' if a['stress_days_pct']>0 else 'Off'}")
    if issues:
        print(f"  - {a['name']:30s} -> {', '.join(issues)}")
