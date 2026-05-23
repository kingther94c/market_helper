"""Q3 — Real latency measurement for the Q8 macro calibration.

Redesigned probes (in scripts/research/anchors.py) start a 60-bday
lead-in BEFORE the canonical transition date and measure how many bdays
elapse from the canonical date until the engine first labels the target
state and HOLDS it for `min_hold` consecutive bdays.

For each probe, compute latency under:
  - baseline (Q7)
  - Q8 winner
  - balanced + decay engaged (mw=0.10)
  - inflation_macro_heavy

Output: data/research_artifacts/macro_latency.json
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
    load_concept_specs, load_panel, load_series_specs,
)
from market_helper.regimes.methods.macro_regime import load_macro_regime_config
from market_helper.regimes.methods.market_regime import load_market_regime_config
from market_helper.regimes.engine_v2 import load_regime_engine_config

from scripts.research.anchors import LATENCY_PROBES, LatencyProbe
from scripts.research.macro_robustness import (
    BASELINE, Q8_WINNER, RUNNERUP_BALANCED_IT008, RUNNERUP_INFLATION_HEAVY,
    RUNNERUP_LOW_DECAY, _run_one_config, axis_label,
)
from scripts.research.macro_calibration_grid import (
    _merge_market_panel, MACRO_PANEL, REGIME_CFG, FRED_CFG, MARKET_CFG,
)


OUT = REPO_ROOT / "data/research_artifacts/macro_latency.json"


CONTENDERS = [BASELINE, Q8_WINNER, RUNNERUP_BALANCED_IT008,
              RUNNERUP_INFLATION_HEAVY, RUNNERUP_LOW_DECAY]


def measure_probe_latency(df: pd.DataFrame, probe: LatencyProbe, gt: float, it: float) -> dict:
    """For a per-day score frame, compute the latency from probe.transition_date
    until the engine first labels probe.target on probe.axis for probe.min_hold
    consecutive bdays.

    Returns:
      - prior_state_bdays: how many bdays in the lead-in did the engine spend
        in a state DIFFERENT from probe.target (sanity check that we have a
        real transition to measure)
      - latency_bdays: bdays from transition_date to first sustained label of target
      - label_at_transition: what the engine labeled on the canonical transition day
      - earliest_match_date: first date matching the target & holding
    """
    lead = pd.Timestamp(probe.lead_in_start)
    trans = pd.Timestamp(probe.transition_date)
    score_col = "final_g" if probe.axis == "growth" else "final_i"
    threshold = gt if probe.axis == "growth" else it
    labels = df[score_col].apply(lambda s: axis_label(s, threshold, -threshold))
    # Lead-in slice
    lead_mask = (df["date"] >= lead) & (df["date"] < trans)
    lead_labels = labels[lead_mask]
    prior_state_bdays = int((lead_labels != probe.target).sum())
    # Find first sustained match at or after transition_date
    forward_mask = df["date"] >= trans
    fwd_labels = labels[forward_mask].reset_index(drop=True)
    fwd_dates = df.loc[forward_mask, "date"].reset_index(drop=True)
    first_match = None
    for i in range(len(fwd_labels) - probe.min_hold + 1):
        if all(fwd_labels.iloc[i + j] == probe.target for j in range(probe.min_hold)):
            first_match = i
            break
    if first_match is None:
        return {
            "probe": probe.name,
            "axis": probe.axis,
            "target": probe.target,
            "transition_date": str(trans.date()),
            "prior_state_bdays_in_leadin": prior_state_bdays,
            "label_at_transition": labels[df["date"] == trans].iloc[0] if (df["date"] == trans).any() else None,
            "latency_bdays": None,
            "earliest_match_date": None,
            "note": f"Engine never labeled {probe.target} (sustained) within available window",
        }
    earliest = fwd_dates.iloc[first_match]
    # bdays between trans and earliest (use pd.bdate_range diff)
    latency = len(pd.bdate_range(trans, earliest)) - 1
    return {
        "probe": probe.name,
        "axis": probe.axis,
        "target": probe.target,
        "transition_date": str(trans.date()),
        "prior_state_bdays_in_leadin": prior_state_bdays,
        "label_at_transition": labels[df["date"] == trans].iloc[0] if (df["date"] == trans).any() else None,
        "latency_bdays": int(latency),
        "earliest_match_date": str(earliest.date()),
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

    print(f"running {len(CONTENDERS)} contender configs...", flush=True)
    frames = {}
    for params in CONTENDERS:
        print(f"  {params['name']}", flush=True)
        frames[params["name"]] = _run_one_config(
            params,
            base_engine=base_engine, base_macro=base_macro,
            macro_panel=macro_panel, market_panel=market_panel,
            macro_specs=macro_specs, macro_concepts=macro_concepts,
            market_method=market_method,
        )

    print(f"measuring {len(LATENCY_PROBES)} probes per config...", flush=True)
    rows = []
    for probe in LATENCY_PROBES:
        for params in CONTENDERS:
            df = frames[params["name"]]
            m = measure_probe_latency(
                df, probe,
                gt=params["growth_thresh"], it=params["inflation_thresh"],
            )
            m["config_name"] = params["name"]
            rows.append(m)

    # Aggregate: per contender, mean & median latency across probes
    by_config = {}
    for params in CONTENDERS:
        lats = [r["latency_bdays"] for r in rows
                if r["config_name"] == params["name"] and r["latency_bdays"] is not None]
        by_config[params["name"]] = {
            "n_probes": len([r for r in rows if r["config_name"] == params["name"]]),
            "n_detected": len(lats),
            "mean_latency_bdays": round(sum(lats) / max(len(lats), 1), 1) if lats else None,
            "median_latency_bdays": int(sorted(lats)[len(lats)//2]) if lats else None,
            "max_latency_bdays": max(lats) if lats else None,
            "all_latencies": lats,
        }

    out = {
        "n_probes": len(LATENCY_PROBES),
        "n_contenders": len(CONTENDERS),
        "by_config": by_config,
        "all_rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print()
    print("=== Latency summary (bdays from canonical transition to first sustained target label) ===")
    print()
    print(f"{'Probe':40s} | {'Baseline':10s} | {'Q8':10s} | {'B+it=.08':10s} | {'I-heavy':10s} | {'mw=0.10':10s}")
    print("-" * 110)
    for probe in LATENCY_PROBES:
        # Sanitize for cp1252-only consoles (Windows PowerShell default).
        safe_name = probe.name.replace("→", "->")[:40]
        cells = [safe_name]
        for params in CONTENDERS:
            r = next((x for x in rows if x["probe"] == probe.name and x["config_name"] == params["name"]), None)
            if r and r["latency_bdays"] is not None:
                cells.append(f"{r['latency_bdays']:3d}bd")
            else:
                cells.append("never")
        print(f"{cells[0]:40s} | {cells[1]:10s} | {cells[2]:10s} | {cells[3]:10s} | {cells[4]:10s} | {cells[5]:10s}")
    print()
    print("By config (mean / median / max bdays):")
    for name, summary in by_config.items():
        print(f"  {name[:50]:50s} mean={summary['mean_latency_bdays']} median={summary['median_latency_bdays']} max={summary['max_latency_bdays']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
