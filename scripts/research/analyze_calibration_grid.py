"""Analyze the calibration grid output and select a recommended config.

Reads ``calibration_grid_results.json``, aggregates per-config (across
anchors) into composite metrics, then identifies the Pareto front on:

  (a) crisis-window stress hit-rate (higher is better)
  (b) benign-window stress false-positive rate (lower is better)
  (c) average latency from critical day to first stress trigger (lower better)

Picks the candidate that strictly improves the current config OR offers
the best dominated trade-off. Writes a summary JSON for the HTML report.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, median

REPO_ROOT = Path(__file__).resolve().parents[2]
ART_DIR = REPO_ROOT / "data" / "research_artifacts"


CURRENT_PARAMS = {
    "risk_enter_threshold": 0.75,
    "risk_min_consecutive_days": 3,
    "axis_min_consecutive_days": 5,
}


def _config_key(params: dict) -> tuple[float, int, int]:
    return (
        float(params["risk_enter_threshold"]),
        int(params["risk_min_consecutive_days"]),
        int(params["axis_min_consecutive_days"]),
    )


def main() -> int:
    runs = json.loads((ART_DIR / "calibration_grid_results.json").read_text(encoding="utf-8"))

    # Group runs by config tuple
    by_config: dict[tuple, list[dict]] = {}
    for run in runs:
        by_config.setdefault(_config_key(run["config"]), []).append(run)

    # Per-config composite metrics
    summaries = []
    for key, anchor_runs in by_config.items():
        ret, rcd, acd = key
        crisis_hit_rates: list[float] = []
        benign_fp_rates: list[float] = []
        critical_latencies: list[float] = []  # bdays; cap at 60 if never
        critical_same_day_hits = 0
        trough_growth: list[float] = []
        crisis_max_neg: list[float] = []
        median_run_lengths: list[float] = []
        per_anchor: list[dict] = []
        for r in anchor_runs:
            crisis_hit = r["crisis_stress_days"] / max(r["crisis_days"], 1)
            benign_fp = r["benign_stress_days"] / max(r["benign_days"], 1)
            crisis_hit_rates.append(crisis_hit)
            benign_fp_rates.append(benign_fp)
            latency = r.get("critical_day_latency_bdays")
            critical_latencies.append(60.0 if latency is None else float(latency))
            if r.get("critical_day_stress") is True and latency == 0:
                critical_same_day_hits += 1
            tg = r.get("trough_growth_score")
            if tg is not None:
                trough_growth.append(float(tg))
            cmn = r.get("crisis_max_negative_growth")
            if cmn is not None:
                crisis_max_neg.append(float(cmn))
            mrl = r.get("median_axis_run_length")
            if mrl is not None:
                median_run_lengths.append(float(mrl))
            per_anchor.append({
                "anchor": r["anchor"],
                "crisis_hit_rate": crisis_hit,
                "benign_fp_rate": benign_fp,
                "critical_latency_bdays": latency,
                "critical_day_stress": r.get("critical_day_stress"),
                "trough_growth_score": tg,
                "crisis_max_negative_growth": cmn,
                "median_axis_run_length": mrl,
            })
        summaries.append({
            "risk_enter_threshold": ret,
            "risk_min_consecutive_days": rcd,
            "axis_min_consecutive_days": acd,
            "avg_crisis_hit_rate": mean(crisis_hit_rates),
            "avg_benign_fp_rate": mean(benign_fp_rates),
            "avg_critical_latency_bdays": mean(critical_latencies),
            "critical_same_day_hits": critical_same_day_hits,
            "avg_crisis_max_neg_growth": mean(crisis_max_neg) if crisis_max_neg else None,
            "median_axis_run_length_median": median(median_run_lengths) if median_run_lengths else None,
            "per_anchor": per_anchor,
            "is_current": (ret, rcd, acd) == _config_key(CURRENT_PARAMS),
        })

    # Score: maximize hit_rate - 2*fp_rate - 0.02*latency
    for s in summaries:
        s["composite_score"] = (
            s["avg_crisis_hit_rate"]
            - 2.0 * s["avg_benign_fp_rate"]
            - 0.02 * s["avg_critical_latency_bdays"]
        )

    # Pareto front on (hit_rate up, fp_rate down, latency down)
    front: list[dict] = []
    for cand in summaries:
        dominated = False
        for other in summaries:
            if other is cand:
                continue
            if (
                other["avg_crisis_hit_rate"] >= cand["avg_crisis_hit_rate"]
                and other["avg_benign_fp_rate"] <= cand["avg_benign_fp_rate"]
                and other["avg_critical_latency_bdays"] <= cand["avg_critical_latency_bdays"]
                and (
                    other["avg_crisis_hit_rate"] > cand["avg_crisis_hit_rate"]
                    or other["avg_benign_fp_rate"] < cand["avg_benign_fp_rate"]
                    or other["avg_critical_latency_bdays"] < cand["avg_critical_latency_bdays"]
                )
            ):
                dominated = True
                break
        if not dominated:
            front.append(cand)

    summaries.sort(key=lambda s: -s["composite_score"])
    front_sorted = sorted(front, key=lambda s: -s["composite_score"])

    current = next(s for s in summaries if s["is_current"])
    # Strict improvers over current: dominate current
    strict_improvers = [
        s for s in summaries
        if not s["is_current"]
        and s["avg_crisis_hit_rate"] >= current["avg_crisis_hit_rate"]
        and s["avg_benign_fp_rate"] <= current["avg_benign_fp_rate"]
        and s["avg_critical_latency_bdays"] <= current["avg_critical_latency_bdays"]
        and (
            s["avg_crisis_hit_rate"] > current["avg_crisis_hit_rate"]
            or s["avg_benign_fp_rate"] < current["avg_benign_fp_rate"]
            or s["avg_critical_latency_bdays"] < current["avg_critical_latency_bdays"]
        )
    ]
    strict_improvers.sort(key=lambda s: -s["composite_score"])

    out = {
        "current": current,
        "top_10_by_composite": summaries[:10],
        "pareto_front_size": len(front),
        "pareto_front": front_sorted,
        "strict_improvers_over_current": strict_improvers,
        "recommendation": (
            strict_improvers[0] if strict_improvers
            else (front_sorted[0] if front_sorted else None)
        ),
    }
    out_path = ART_DIR / "calibration_analysis.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    rec = out["recommendation"]
    print()
    print("Current config:")
    print(f"  ret={current['risk_enter_threshold']}, rcd={current['risk_min_consecutive_days']}, acd={current['axis_min_consecutive_days']}")
    print(f"  hit={current['avg_crisis_hit_rate']:.3f}  fp={current['avg_benign_fp_rate']:.3f}  latency={current['avg_critical_latency_bdays']:.1f}bd  same_day={current['critical_same_day_hits']}/4  score={current['composite_score']:.3f}")
    print()
    print(f"Pareto front size: {len(front)}")
    print(f"Strict improvers over current: {len(strict_improvers)}")
    if rec:
        print()
        print("Recommendation:")
        print(f"  ret={rec['risk_enter_threshold']}, rcd={rec['risk_min_consecutive_days']}, acd={rec['axis_min_consecutive_days']}")
        print(f"  hit={rec['avg_crisis_hit_rate']:.3f}  fp={rec['avg_benign_fp_rate']:.3f}  latency={rec['avg_critical_latency_bdays']:.1f}bd  same_day={rec['critical_same_day_hits']}/4  score={rec['composite_score']:.3f}")
        if rec["is_current"]:
            print("  (= current; no change recommended)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
