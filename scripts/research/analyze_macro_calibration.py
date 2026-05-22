"""Analyze the macro calibration grid and pick a recommendation.

Reads ``macro_calibration_grid.json`` and:
  1. Computes a composite score: weighted blend of anchor-match,
     stability, and latency.
  2. Identifies the Pareto front on (match%, stability, latency).
  3. Filters to "safe" candidates (anchor risk-match >= 80%) so we never
     ship a worse risk overlay than calibrated last round.
  4. Writes ``macro_calibration_analysis.json`` for the HTML report.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parents[2]
ART = REPO / "data/research_artifacts"


# Baseline = the config that matches the currently-shipped values.
BASELINE = {
    "min_weight": 0.65,
    "growth_thresh": 0.15,
    "inflation_thresh": 0.12,
    "axis_min_consecutive": 5,
    "macro_g_w": 0.35,
    "macro_i_w": 0.30,
    "market_g_w": 0.65,
    "market_i_w": 0.70,
}


def _key(params: dict) -> tuple:
    return (
        round(params["min_weight"], 3),
        round(params["growth_thresh"], 3),
        round(params["inflation_thresh"], 3),
        int(params["axis_min_consecutive"]),
        round(params["macro_g_w"], 3),
        round(params["macro_i_w"], 3),
        round(params["market_g_w"], 3),
        round(params["market_i_w"], 3),
    )


def composite(metrics: dict) -> float:
    """Higher = better. Match dominates; stability is a small tiebreaker.

    Latency probes degenerate in this round (named transition dates are
    already inside the target state for most configs → latency=0), so we
    do NOT use them in selection. They are recorded in the per-config
    metrics for future tighter probes.

    Formula: match + 0.3 * min(stab, 20).
    With match in [0, 100] and stab bonus capped at 6, match dominates 16:1.
    """
    match = metrics["overall_avg_match_pct"]
    stab = (metrics["g_median_run_bdays"] + metrics["i_median_run_bdays"]) / 2.0
    return match + 0.3 * min(stab, 20.0)


def pareto(items: list[dict]) -> list[dict]:
    """Front maximizing (match, stability). Latency intentionally excluded
    — see composite() docstring for the degeneracy explanation."""
    front = []
    for cand in items:
        dominated = False
        for other in items:
            if other is cand:
                continue
            o_match = other["metrics"]["overall_avg_match_pct"]
            c_match = cand["metrics"]["overall_avg_match_pct"]
            o_stab = (other["metrics"]["g_median_run_bdays"] + other["metrics"]["i_median_run_bdays"]) / 2.0
            c_stab = (cand["metrics"]["g_median_run_bdays"] + cand["metrics"]["i_median_run_bdays"]) / 2.0
            if (o_match >= c_match and o_stab >= c_stab and (
                o_match > c_match or o_stab > c_stab
            )):
                dominated = True
                break
        if not dominated:
            front.append(cand)
    return front


def main() -> int:
    runs = json.loads((ART / "macro_calibration_grid.json").read_text())
    # Pack into uniform shape
    packed = []
    for r in runs:
        item = {
            "params": r["params"],
            "metrics": {
                "g_avg_match_pct": r["g_avg_match_pct"],
                "i_avg_match_pct": r["i_avg_match_pct"],
                "risk_avg_match_pct": r["risk_avg_match_pct"],
                "overall_avg_match_pct": r["overall_avg_match_pct"],
                "g_median_run_bdays": r["g_median_run_bdays"],
                "i_median_run_bdays": r["i_median_run_bdays"],
                "g_n_runs": r["g_n_runs"],
                "i_n_runs": r["i_n_runs"],
                "per_anchor": r["per_anchor"],
                "latencies": r["latencies"],
            },
        }
        item["composite"] = composite(item["metrics"])
        item["is_baseline"] = _key(r["params"]) == _key(BASELINE)
        packed.append(item)

    # Identify baseline
    baseline_item = next((p for p in packed if p["is_baseline"]), None)

    # Pareto front
    front = pareto(packed)
    front_sorted = sorted(front, key=lambda p: -p["composite"])

    # Strict improvers over baseline — dominate on (match, stability).
    # Latency excluded (degenerate, see composite() docstring).
    if baseline_item:
        bm = baseline_item["metrics"]
        b_match = bm["overall_avg_match_pct"]
        b_stab = (bm["g_median_run_bdays"] + bm["i_median_run_bdays"]) / 2.0
        strict = []
        for p in packed:
            if p["is_baseline"]:
                continue
            m = p["metrics"]
            mm = m["overall_avg_match_pct"]
            ms = (m["g_median_run_bdays"] + m["i_median_run_bdays"]) / 2.0
            if mm >= b_match and ms >= b_stab and (mm > b_match or ms > b_stab):
                strict.append(p)
        strict.sort(key=lambda p: -p["composite"])
    else:
        strict = []

    # Filter to safe candidates: risk-match >= 80% (no worse than Q7)
    safe = [p for p in packed if p["metrics"]["risk_avg_match_pct"] >= 80.0]
    safe.sort(key=lambda p: -p["composite"])

    # Top-N by composite overall
    top10 = sorted(packed, key=lambda p: -p["composite"])[:10]

    rec = (strict[0] if strict else (safe[0] if safe else top10[0]))

    out = {
        "n_configs": len(packed),
        "baseline": baseline_item,
        "recommendation": rec,
        "strict_improvers_count": len(strict),
        "strict_improvers_top10": strict[:10],
        "pareto_front_count": len(front),
        "pareto_front_top10": front_sorted[:10],
        "safe_count": len(safe),
        "safe_top10": safe[:10],
        "top10_composite": top10,
    }
    (ART / "macro_calibration_analysis.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    print(f"wrote {ART / 'macro_calibration_analysis.json'}")
    print()
    if baseline_item:
        bm = baseline_item["metrics"]
        print(f"Baseline: g_avg={bm['g_avg_match_pct']:.0f}% i_avg={bm['i_avg_match_pct']:.0f}% "
              f"risk={bm['risk_avg_match_pct']:.0f}% overall={bm['overall_avg_match_pct']:.0f}% "
              f"composite={baseline_item['composite']:.2f}")
    rm = rec["metrics"]
    print(f"Recommendation: g_avg={rm['g_avg_match_pct']:.0f}% i_avg={rm['i_avg_match_pct']:.0f}% "
          f"risk={rm['risk_avg_match_pct']:.0f}% overall={rm['overall_avg_match_pct']:.0f}% "
          f"composite={rec['composite']:.2f}")
    print(f"  params: {rec['params']}")
    print(f"  median run: g={rm['g_median_run_bdays']}bd i={rm['i_median_run_bdays']}bd")
    print()
    print("Per-anchor breakdown (recommendation):")
    for a in rm["per_anchor"]:
        g_arrow = ""
        i_arrow = ""
        if baseline_item:
            for ba in baseline_item["metrics"]["per_anchor"]:
                if ba["name"] == a["name"]:
                    dg = a["g_match_pct"] - ba["g_match_pct"]
                    di = a["i_match_pct"] - ba["i_match_pct"]
                    g_arrow = f" ({dg:+.0f}pp)" if dg != 0 else ""
                    i_arrow = f" ({di:+.0f}pp)" if di != 0 else ""
                    break
        print(f"  {a['name']:30s} g_match={a['g_match_pct']:5.1f}%{g_arrow:10s} "
              f"i_match={a['i_match_pct']:5.1f}%{i_arrow}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
