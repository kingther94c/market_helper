"""Q2 — Label-ambiguity attribution for the Q8 macro calibration.

For each anchor, compute baseline & Q8 match% under:
  - primary consensus label
  - alternative consensus label (if anchor has one defined in anchors.py)

Then attribute each "Miss" (match% < 60%) to:
  - Definition-dependent: anchor's `confidence` == "definition-dependent"
    AND match% jumps >= 30pp under alt label → framing artifact, not failure
  - Defensible-disagreement: anchor's `confidence` == "defensible" AND
    alt label flips match% above 60% → reasonable analysts would agree
  - Genuine signal failure: anchor's `confidence` == "clear" OR neither
    label achieves match%>=60% → real shortcoming we should surface

Also reports per-confidence-class average match% so the user can see the
"easy to match" subset performance separately from the "definition-bound"
subset.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.research.anchors import ANCHORS_LEVEL, Anchor
from scripts.research.macro_robustness import (
    BASELINE, Q8_WINNER, _run_one_config, axis_label,
)
from scripts.research.macro_calibration_grid import (
    _merge_market_panel, MACRO_PANEL, REGIME_CFG, FRED_CFG, MARKET_CFG,
)
from market_helper.data_sources.fred.macro_panel import (
    load_concept_specs, load_panel, load_series_specs,
)
from market_helper.regimes.methods.macro_regime import load_macro_regime_config
from market_helper.regimes.methods.market_regime import load_market_regime_config
from market_helper.regimes.engine_v2 import load_regime_engine_config


OUT = REPO_ROOT / "data/research_artifacts/macro_label_ambiguity.json"


def _per_anchor_match(df: pd.DataFrame, a: Anchor, gt: float, it: float,
                      *, use_alt: bool = False) -> tuple[float, float]:
    g_label = a.alt_g if (use_alt and a.alt_g) else a.g_consensus
    i_label = a.alt_i if (use_alt and a.alt_i) else a.i_consensus
    lo, hi = pd.Timestamp(a.start), pd.Timestamp(a.end)
    win = df[(df["date"] >= lo) & (df["date"] <= hi)]
    if win.empty:
        return 0.0, 0.0
    g = win["final_g"].apply(lambda s: axis_label(s, gt, -gt))
    i = win["final_i"].apply(lambda s: axis_label(s, it, -it))
    return (
        round(100.0 * (g == g_label).mean(), 1),
        round(100.0 * (i == i_label).mean(), 1),
    )


def main() -> int:
    print("loading panels...", flush=True)
    base_engine = load_regime_engine_config(REGIME_CFG)
    base_macro = load_macro_regime_config(FRED_CFG)
    macro_specs = load_series_specs(FRED_CFG)
    macro_concepts = load_concept_specs(FRED_CFG)
    market_method = load_market_regime_config(MARKET_CFG)
    macro_panel = load_panel(MACRO_PANEL)
    market_panel = _merge_market_panel()

    print("running baseline + Q8...", flush=True)
    base_df = _run_one_config(
        BASELINE,
        base_engine=base_engine, base_macro=base_macro,
        macro_panel=macro_panel, market_panel=market_panel,
        macro_specs=macro_specs, macro_concepts=macro_concepts,
        market_method=market_method,
    )
    q8_df = _run_one_config(
        Q8_WINNER,
        base_engine=base_engine, base_macro=base_macro,
        macro_panel=macro_panel, market_panel=market_panel,
        macro_specs=macro_specs, macro_concepts=macro_concepts,
        market_method=market_method,
    )

    print("attributing per anchor...", flush=True)
    per_anchor = []
    for a in ANCHORS_LEVEL:
        b_g, b_i = _per_anchor_match(base_df, a, BASELINE["growth_thresh"], BASELINE["inflation_thresh"])
        q_g, q_i = _per_anchor_match(q8_df, a, Q8_WINNER["growth_thresh"], Q8_WINNER["inflation_thresh"])
        b_g_alt, b_i_alt = _per_anchor_match(base_df, a, BASELINE["growth_thresh"], BASELINE["inflation_thresh"], use_alt=True)
        q_g_alt, q_i_alt = _per_anchor_match(q8_df, a, Q8_WINNER["growth_thresh"], Q8_WINNER["inflation_thresh"], use_alt=True)

        # Attribute Q8's per-axis verdict
        def _attribute(match_primary: float, match_alt: float, has_alt: bool) -> str:
            if match_primary >= 60:
                return "PASS"
            if not has_alt:
                return ("ambiguous" if a.confidence != "clear" else "FAIL (clear)")
            jump = match_alt - match_primary
            if a.confidence == "definition-dependent" and jump >= 30:
                return f"definition-artifact (alt={match_alt:.0f}%)"
            if a.confidence == "defensible" and match_alt >= 60:
                return f"label-defensible (alt={match_alt:.0f}%)"
            return "FAIL"

        per_anchor.append({
            "name": a.name,
            "confidence": a.confidence,
            "consensus": f"g={a.g_consensus}, i={a.i_consensus}",
            "baseline_g_match": b_g,
            "baseline_i_match": b_i,
            "q8_g_match": q_g,
            "q8_i_match": q_i,
            "alt_g": a.alt_g,
            "alt_i": a.alt_i,
            "baseline_g_match_alt": b_g_alt if a.alt_g else None,
            "baseline_i_match_alt": b_i_alt if a.alt_i else None,
            "q8_g_match_alt": q_g_alt if a.alt_g else None,
            "q8_i_match_alt": q_i_alt if a.alt_i else None,
            "q8_g_verdict": _attribute(q_g, q_g_alt, bool(a.alt_g)),
            "q8_i_verdict": _attribute(q_i, q_i_alt, bool(a.alt_i)),
        })

    # Per-confidence-class summary
    by_conf = {}
    for c in ("clear", "defensible", "definition-dependent"):
        in_class = [x for x in per_anchor if x["confidence"] == c]
        if not in_class:
            continue
        by_conf[c] = {
            "n_anchors": len(in_class),
            "baseline_g_avg": round(mean(x["baseline_g_match"] for x in in_class), 1),
            "baseline_i_avg": round(mean(x["baseline_i_match"] for x in in_class), 1),
            "q8_g_avg": round(mean(x["q8_g_match"] for x in in_class), 1),
            "q8_i_avg": round(mean(x["q8_i_match"] for x in in_class), 1),
        }

    # Count verdicts
    verdicts = {
        "g": {},
        "i": {},
    }
    for x in per_anchor:
        verdicts["g"][x["q8_g_verdict"]] = verdicts["g"].get(x["q8_g_verdict"], 0) + 1
        verdicts["i"][x["q8_i_verdict"]] = verdicts["i"].get(x["q8_i_verdict"], 0) + 1

    out = {
        "n_anchors": len(per_anchor),
        "per_anchor": per_anchor,
        "by_confidence_class": by_conf,
        "q8_verdict_counts": verdicts,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print()
    print("=== Per-anchor verdicts (Q8) ===")
    print(f"{'Anchor':30s} | {'conf':18s} | {'g_match':8s} {'i_match':8s} | {'g_verdict':30s} {'i_verdict':30s}")
    print("-" * 145)
    for x in per_anchor:
        print(f"{x['name']:30s} | {x['confidence']:18s} | {x['q8_g_match']:6.1f}% {x['q8_i_match']:6.1f}% | {x['q8_g_verdict']:30s} {x['q8_i_verdict']:30s}")
    print()
    print("=== Match% by confidence class ===")
    for c, s in by_conf.items():
        print(f"  {c:25s} ({s['n_anchors']:2d} anchors): baseline g={s['baseline_g_avg']:.1f}%/i={s['baseline_i_avg']:.1f}% -> Q8 g={s['q8_g_avg']:.1f}%/i={s['q8_i_avg']:.1f}%")
    print()
    print("=== Q8 verdict tally ===")
    print(f"  growth: {verdicts['g']}")
    print(f"  inflation: {verdicts['i']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
