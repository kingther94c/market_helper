"""Q4 — Concept-level attribution for the Q8 macro calibration.

For each anchor, pick 3 representative dates (start, middle, end), and
for both baseline & Q8 configs, dump:
  - per-layer growth/inflation scores
  - per-concept contributions (which series within labor/realized_broad/etc
    pushed scores)
  - top series contributors

Output: data/research_artifacts/macro_concept_attribution.json + brief
console summary of what concepts drove Q8's biggest wins/losses.

This addresses: "which concept-level contributors explain major
successes and failures?"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from market_helper.data_sources.fred.macro_panel import (
    load_concept_specs,
    load_panel,
    load_series_specs,
)
from market_helper.regimes.engine_v2 import (
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.macro_regime import load_macro_regime_config
from market_helper.regimes.methods.market_regime import load_market_regime_config

from scripts.research.anchors import ANCHORS_LEVEL
from scripts.research.macro_robustness import (
    BASELINE, Q8_WINNER, _run_one_config, axis_label,
)
from scripts.research.macro_calibration_grid import (
    _merge_market_panel, MACRO_PANEL, REGIME_CFG, FRED_CFG, MARKET_CFG,
)


OUT = REPO_ROOT / "data/research_artifacts/macro_concept_attribution.json"


def _pick_representative_dates(start: str, end: str) -> list[pd.Timestamp]:
    """Start, midpoint, end."""
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    m = s + (e - s) / 2
    # Snap to weekdays (Mon=0..Fri=4)
    while m.weekday() > 4:
        m += pd.Timedelta(days=1)
    return [s, m, e]


def _run_full_results(params: dict, *, base_engine, base_macro,
                      macro_panel, market_panel, macro_specs,
                      macro_concepts, market_method) -> list:
    """Run engine and return the FULL FinalRegimeResult list (not a frame).

    We need the per-result `top_contributors` and `layer_outputs`, not just
    the score series.
    """
    from scripts.research.macro_calibration_grid import (
        _build_engine_cfg, _build_macro_cfg,
    )
    engine = _build_engine_cfg(
        base_engine,
        growth_thresh=params["growth_thresh"],
        inflation_thresh=params["inflation_thresh"],
        axis_min_consecutive=params["axis_min_consecutive"],
        macro_g_w=params["macro_g_w"],
        macro_i_w=params["macro_i_w"],
        market_g_w=params["market_g_w"],
        market_i_w=params["market_i_w"],
    )
    macro = _build_macro_cfg(base_macro, min_weight=params["min_weight"])
    return run_regime_engine_v2(
        config=engine,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        macro_concepts=macro_concepts,
        macro_method_config=macro,
        market_panel=market_panel,
        market_config=market_method,
    )


def _extract_attribution(result, gt: float, it: float) -> dict:
    """Pull layer scores + top contributors out of one FinalRegimeResult."""
    g_label = axis_label(result.final_growth_score, gt, -gt)
    i_label = axis_label(result.final_inflation_score, it, -it)
    layer = {}
    for lo in result.layer_outputs:
        if not lo.enabled or not lo.available:
            continue
        layer[lo.layer_name] = {
            "growth": float(lo.growth_score) if lo.growth_score is not None else None,
            "inflation": float(lo.inflation_score) if lo.inflation_score is not None else None,
            "top_pos": [(name, round(v, 3)) for name, v in lo.top_positive_contributors[:3]],
            "top_neg": [(name, round(v, 3)) for name, v in lo.top_negative_contributors[:3]],
        }
    return {
        "date": str(result.date)[:10],
        "final_g": round(result.final_growth_score, 3),
        "final_i": round(result.final_inflation_score, 3),
        "g_label": g_label,
        "i_label": i_label,
        "risk_score": round(result.risk_score, 3),
        "risk_on": bool(result.risk_overlay_on),
        "layer_outputs": layer,
        "top_contributors": [(name, round(v, 3)) for name, v in result.top_contributors[:5]],
    }


def main() -> int:
    print("loading panels...", flush=True)
    base_engine = load_regime_engine_config(REGIME_CFG)
    base_macro = load_macro_regime_config(FRED_CFG)
    macro_specs = load_series_specs(FRED_CFG)
    macro_concepts = load_concept_specs(FRED_CFG)
    market_method = load_market_regime_config(MARKET_CFG)
    macro_panel = load_panel(MACRO_PANEL)
    market_panel = _merge_market_panel()

    print("running baseline...", flush=True)
    baseline_results = _run_full_results(
        BASELINE,
        base_engine=base_engine, base_macro=base_macro,
        macro_panel=macro_panel, market_panel=market_panel,
        macro_specs=macro_specs, macro_concepts=macro_concepts,
        market_method=market_method,
    )
    print("running Q8 winner...", flush=True)
    q8_results = _run_full_results(
        Q8_WINNER,
        base_engine=base_engine, base_macro=base_macro,
        macro_panel=macro_panel, market_panel=market_panel,
        macro_specs=macro_specs, macro_concepts=macro_concepts,
        market_method=market_method,
    )

    # Index by date
    baseline_by_date = {pd.Timestamp(str(r.date)[:10]): r for r in baseline_results}
    q8_by_date = {pd.Timestamp(str(r.date)[:10]): r for r in q8_results}

    print(f"attributing across {len(ANCHORS_LEVEL)} anchors...", flush=True)
    out_anchors = []
    for a in ANCHORS_LEVEL:
        dates = _pick_representative_dates(a.start, a.end)
        # Snap each to nearest available date
        baseline_keys = pd.DatetimeIndex(baseline_by_date.keys())
        snapped = []
        for d in dates:
            idx = baseline_keys.searchsorted(d, side="left")
            if idx >= len(baseline_keys):
                idx = len(baseline_keys) - 1
            snapped.append(baseline_keys[idx])
        snapped = sorted(set(snapped))
        per_date = []
        for sd in snapped:
            b = baseline_by_date.get(sd)
            q = q8_by_date.get(sd)
            if not (b and q):
                continue
            per_date.append({
                "date": str(sd.date()),
                "baseline": _extract_attribution(
                    b, BASELINE["growth_thresh"], BASELINE["inflation_thresh"]
                ),
                "q8": _extract_attribution(
                    q, Q8_WINNER["growth_thresh"], Q8_WINNER["inflation_thresh"]
                ),
            })
        out_anchors.append({
            "name": a.name,
            "window": [a.start, a.end],
            "confidence": a.confidence,
            "g_consensus": a.g_consensus,
            "i_consensus": a.i_consensus,
            "brief": a.brief,
            "per_date": per_date,
        })

    out = {
        "n_anchors": len(out_anchors),
        "baseline_config": BASELINE,
        "q8_config": Q8_WINNER,
        "anchors": out_anchors,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}")
    print()

    # Print human-readable summary for the most informative anchors
    print("=== Concept attribution highlights ===")
    print()
    for anchor in out_anchors:
        # Pick the middle date (most representative)
        mid_idx = len(anchor["per_date"]) // 2
        if mid_idx >= len(anchor["per_date"]):
            continue
        date_row = anchor["per_date"][mid_idx]
        b = date_row["baseline"]
        q = date_row["q8"]
        if b["g_label"] == q["g_label"] and b["i_label"] == q["i_label"]:
            continue  # no label change at midpoint
        print(f"--- {anchor['name']} (consensus g={anchor['g_consensus']} i={anchor['i_consensus']}, conf={anchor['confidence']}) ---")
        print(f"    Date: {date_row['date']}")
        print(f"    Baseline: g={b['final_g']:+.2f} ({b['g_label']}) | i={b['final_i']:+.2f} ({b['i_label']})")
        print(f"        macro layer: g={b['layer_outputs'].get('macro_nowcast',{}).get('growth','—')} i={b['layer_outputs'].get('macro_nowcast',{}).get('inflation','—')}")
        print(f"        market layer: g={b['layer_outputs'].get('market_implied',{}).get('growth','—')} i={b['layer_outputs'].get('market_implied',{}).get('inflation','—')}")
        print(f"        top contributors: {b['top_contributors'][:3]}")
        print(f"    Q8:       g={q['final_g']:+.2f} ({q['g_label']}) | i={q['final_i']:+.2f} ({q['i_label']})")
        print(f"        macro layer: g={q['layer_outputs'].get('macro_nowcast',{}).get('growth','—')} i={q['layer_outputs'].get('macro_nowcast',{}).get('inflation','—')}")
        print(f"        market layer: g={q['layer_outputs'].get('market_implied',{}).get('growth','—')} i={q['layer_outputs'].get('market_implied',{}).get('inflation','—')}")
        print(f"        top contributors: {q['top_contributors'][:3]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
