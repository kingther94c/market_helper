"""Per-anchor compare: Q9 winner vs Phase-1 neighborhood-robust top.

Output: macro_q9_vs_robust_top_per_anchor.json — for the addendum to
embed as a "why the holdout numbers move" section.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"

grid = json.loads((ART / "macro_calibration_grid_q9.json").read_text())

Q9_KEY = dict(inflation_velocity_weight=1.0, growth_velocity_weight=0.0,
              growth_thresh=0.10, inflation_thresh=0.15, macro_w=0.6, market_w=0.4)
# Phase-1 top robust = ivw=0.7 gt=0.10 it=0.10 m/m=0.6/0.4
TOP_KEY = dict(inflation_velocity_weight=0.7, growth_velocity_weight=0.0,
               growth_thresh=0.10, inflation_thresh=0.10, macro_w=0.6, market_w=0.4)

def _match(p, key):
    return all(abs(float(p[k]) - float(v)) < 1e-6 for k, v in key.items())

q9 = next(r for r in grid if _match(r["params"], Q9_KEY))
top = next(r for r in grid if _match(r["params"], TOP_KEY))

# Combine train + holdout per_anchor into one keyed dict per config
def _all_anchors(r):
    out = {}
    for a in r["train"]["per_anchor"]:
        out[a["name"]] = {"set": "train", **a}
    for a in r["holdout"]["per_anchor"]:
        out[a["name"]] = {"set": "holdout", **a}
    return out

q9_anchors = _all_anchors(q9)
top_anchors = _all_anchors(top)

print(f"{'Anchor':30s} {'set':8s} | Q9 g/i     | Top g/i     | Δg     Δi")
print("-" * 100)
diffs = []
for name in q9_anchors:
    qa = q9_anchors[name]
    ta = top_anchors[name]
    dg = ta["g_match_pct"] - qa["g_match_pct"]
    di = ta["i_match_pct"] - qa["i_match_pct"]
    diffs.append({
        "anchor": name,
        "set": qa["set"],
        "q9_g": qa["g_match_pct"], "q9_i": qa["i_match_pct"],
        "top_g": ta["g_match_pct"], "top_i": ta["i_match_pct"],
        "delta_g": round(dg, 1), "delta_i": round(di, 1),
    })
    mark = ""
    if abs(dg) >= 10 or abs(di) >= 10:
        mark = " <<<"
    print(f"{name:30s} {qa['set']:8s} | {qa['g_match_pct']:5.1f}/{qa['i_match_pct']:5.1f} | {ta['g_match_pct']:5.1f}/{ta['i_match_pct']:5.1f} | {dg:+5.1f} {di:+5.1f}{mark}")

(ART / "macro_q9_vs_robust_top_per_anchor.json").write_text(
    json.dumps({
        "q9_params": q9["params"], "top_params": top["params"],
        "per_anchor": diffs,
    }, indent=2),
    encoding="utf-8",
)
print(f"\nwrote {ART / 'macro_q9_vs_robust_top_per_anchor.json'}")
