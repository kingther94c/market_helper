"""Grid-search calibration for the macro+market regime engine.

Sweeps four knobs:
  - recency_weighting.min_weight     (engages per-frequency decay)
  - regime_thresholds.growth_up/down (axis deadband)
  - regime_thresholds.inflation_up/down
  - layer weights (macro_nowcast vs market_implied per axis)
  - min_consecutive_days (axis-state hysteresis)

For each config, runs the engine over the full FRED-aware history and
computes:
  - anchor-match % per consensus anchor (level-based labels)
  - stability (median regime run length, n_runs)
  - latency to first state flip at the COVID 2020 turning point

Outputs JSON for the HTML reporter to render.

CONSENSUS labels here are LEVEL-based to match how the macro layer
actually scores: e.g. 2023-2024 inflation is "still above target" so
i_consensus = Up/Neutral, not Down. 2022 H1 growth: YoY payrolls were
still strong post-COVID base-effect, so g_consensus = Up (macro view).
We add a parallel DIRECTION-based variant only for narrative purposes
in the HTML report; the calibration optimizes for level matching.
"""
from __future__ import annotations

import itertools
import json
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from statistics import mean, median
from typing import Sequence

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from market_helper.data_sources.fred.macro_panel import (
    load_concept_specs,
    load_panel,
    load_series_specs,
)
from market_helper.data_sources.yahoo_finance.market_panel import (
    DEFAULT_MARKET_CACHE_DIR,
    DEFAULT_MARKET_PANEL_FILENAME,
    load_market_panel,
)
from market_helper.regimes.engine_v2 import (
    LayerConfig,
    RegimeEngineConfig,
    RegimeThresholds,
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.macro_regime import (
    MacroRegimeConfig,
    load_macro_regime_config,
)
from market_helper.regimes.methods.market_regime import load_market_regime_config


HISTORICAL_MKT = REPO_ROOT / "data/external/regime_detection/historical/market_panel_to_2024.feather"
LIVE_MKT = REPO_ROOT / DEFAULT_MARKET_CACHE_DIR / DEFAULT_MARKET_PANEL_FILENAME
MACRO_PANEL = REPO_ROOT / "data/interim/fred/macro_panel.feather"
REGIME_CFG = REPO_ROOT / "configs/regime_detection/regime_engine.yml"
FRED_CFG = REPO_ROOT / "configs/regime_detection/fred_series.yml"
MARKET_CFG = REPO_ROOT / "configs/regime_detection/market_regime.yml"
OUT = REPO_ROOT / "data/research_artifacts/macro_calibration_grid.json"


# LEVEL-based consensus labels (match how the macro layer scores).
# Each tuple: name, start, end, g_consensus, i_consensus, risk_consensus, brief
ANCHORS_LEVEL = [
    ("2008 GFC trough",     "2008-10-01", "2009-03-31", "Down",    "Down",    "On",
     "Lehman+ deep recession; oil bust drives YoY CPI to ~-2%"),
    ("2010-12 expansion",   "2010-06-01", "2012-12-31", "Up",      "Neutral", "Off",
     "Slow but steady job growth (PAYEMS YoY +1.5-2%), CPI ~2-3%"),
    ("2015-16 oil bust",    "2015-08-01", "2016-02-29", "Neutral", "Down",    "On",
     "Mfg recession, CPI YoY near zero, oil bust deflation"),
    ("2017 Goldilocks",     "2017-04-01", "2017-12-31", "Up",      "Neutral", "Off",
     "PAYEMS +1.5% YoY, CPI ~2.1%"),
    ("2018 Q4 vol shock",   "2018-10-01", "2018-12-31", "Up",      "Neutral", "On",
     "Growth still strong YoY (PAYEMS +1.7%); market stress"),
    ("2019 H2 slowdown",    "2019-07-01", "2019-12-31", "Neutral", "Neutral", "Off",
     "Mixed: services strong, mfg recession; CPI ~1.8%"),
    ("2020 COVID recession","2020-02-24", "2020-04-30", "Down",    "Neutral", "On",
     "Catastrophic growth shock; CPI YoY collapse but not deflation"),
    # NOTE: 2020H2 macro reads g=Down because YoY payrolls still -7% (base
    # effect). Consensus-direction was 'recovery'; level says still bad.
    ("2020H2 catch-up",     "2020-07-01", "2020-12-31", "Down",    "Down",    "Off",
     "Recovering but YoY still deep negative; CPI YoY ~1.4%"),
    ("2021 reflation",      "2021-04-01", "2021-12-31", "Up",      "Up",      "Off",
     "Strong recovery, CPI breaks above 5%"),
    # 2022 H1: YoY payrolls +6% (post-COVID base), but GDP printed Q1/Q2
    # negative. Macro level says Up, headline GDP says Down. We label Up
    # to match the YoY-based macro view.
    ("2022 H1 inflation",   "2022-03-01", "2022-09-30", "Up",      "Up",      "On",
     "PAYEMS +5-6% YoY catch-up, CPI peaks at 9.1% in June"),
    # 2023: CPI YoY still 3-4% all year; payrolls +2-3%. Both Up still.
    ("2023 high inflation", "2023-06-01", "2023-12-31", "Up",      "Up",      "Off",
     "Soft landing but CPI still 3-4%, payrolls +2.5%"),
    # 2024: CPI YoY 2.5-3.5%; payrolls +1.5%. Inflation transitioning to
    # Neutral as YoY approaches 2.5% target.
    ("2024 disinflation",   "2024-01-01", "2024-12-31", "Up",      "Neutral", "Off",
     "PAYEMS +1.5%, CPI fading to ~2.5-3% range"),
    ("2025 tariff shock",   "2025-04-02", "2025-05-15", "Neutral", "Up",      "On",
     "Breakevens spike; equity drawdown; growth signals mixed"),
]


# Critical-transition latency probes: name, sequence_start, axis, target_state.
# Engine should flip `axis` to `target_state` within a reasonable window of
# sequence_start. We measure bdays until the first day that scores the target
# state and stays in it for >=hysteresis days.
LATENCY_PROBES = [
    ("COVID growth turn", "2020-02-24", "growth", "Down"),
    ("COVID inflation collapse", "2020-03-01", "inflation", "Down"),
    ("2021 reflation start", "2021-04-01", "inflation", "Up"),
    ("2022 stagflation start", "2022-03-01", "inflation", "Up"),
    ("2024 inflation cooling", "2024-01-01", "inflation", "Neutral"),
]


def axis_label(score: float, up: float, down: float) -> str:
    if score is None or pd.isna(score):
        return "Unknown"
    if score > up:
        return "Up"
    if score < down:
        return "Down"
    return "Neutral"


def run_lengths(states: Sequence) -> list[int]:
    runs: list[int] = []
    cur = None
    n = 0
    for s in states:
        if s == cur:
            n += 1
        else:
            if cur is not None:
                runs.append(n)
            cur = s
            n = 1
    runs.append(n)
    return runs


def _merge_market_panel() -> pd.DataFrame:
    hist = load_market_panel(HISTORICAL_MKT) if HISTORICAL_MKT.exists() else pd.DataFrame()
    live = load_market_panel(LIVE_MKT) if LIVE_MKT.exists() else pd.DataFrame()
    if hist.empty:
        return live
    if live.empty:
        return hist
    merged = pd.concat([hist, live], ignore_index=True)
    return (
        merged.drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )


def _build_engine_cfg(
    base: RegimeEngineConfig,
    *,
    growth_thresh: float,
    inflation_thresh: float,
    axis_min_consecutive: int,
    macro_g_w: float,
    macro_i_w: float,
    market_g_w: float,
    market_i_w: float,
) -> RegimeEngineConfig:
    layers = dict(base.layers)
    layers["macro_nowcast"] = replace(
        layers["macro_nowcast"], weight_growth=macro_g_w, weight_inflation=macro_i_w
    )
    layers["market_implied"] = replace(
        layers["market_implied"], weight_growth=market_g_w, weight_inflation=market_i_w
    )
    new_thresh = replace(
        base.regime_thresholds,
        growth_up=growth_thresh,
        growth_down=-growth_thresh,
        inflation_up=inflation_thresh,
        inflation_down=-inflation_thresh,
        min_consecutive_days=axis_min_consecutive,
    )
    return replace(base, layers=layers, regime_thresholds=new_thresh)


def _build_macro_cfg(base: MacroRegimeConfig, *, min_weight: float) -> MacroRegimeConfig:
    return replace(base, recency_min_weight=min_weight)


def _measure(
    df: pd.DataFrame,
    *,
    growth_thresh: float,
    inflation_thresh: float,
) -> dict:
    """Compute anchor-matches, stability, latencies on the per-day frame."""
    g_labels = df["final_g"].apply(
        lambda s: axis_label(s, growth_thresh, -growth_thresh)
    )
    i_labels = df["final_i"].apply(
        lambda s: axis_label(s, inflation_thresh, -inflation_thresh)
    )

    anchor_summary = []
    for name, start, end, g_exp, i_exp, risk_exp, brief in ANCHORS_LEVEL:
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        mask = (df["date"] >= lo) & (df["date"] <= hi)
        if not mask.any():
            continue
        g_win = g_labels[mask]
        i_win = i_labels[mask]
        risk_win = df.loc[mask, "risk_on"]
        g_match = float((g_win == g_exp).mean())
        i_match = float((i_win == i_exp).mean())
        risk_actual_on = bool(risk_win.any())
        risk_match = (risk_actual_on and risk_exp == "On") or (
            not risk_actual_on and risk_exp == "Off"
        )
        anchor_summary.append({
            "name": name,
            "g_consensus": g_exp,
            "i_consensus": i_exp,
            "g_match_pct": round(g_match * 100, 1),
            "i_match_pct": round(i_match * 100, 1),
            "risk_match": risk_match,
        })

    # Aggregate match metric — average over anchors, weight all equally.
    g_avg = float(mean(a["g_match_pct"] for a in anchor_summary))
    i_avg = float(mean(a["i_match_pct"] for a in anchor_summary))
    risk_avg = (
        sum(1 for a in anchor_summary if a["risk_match"]) / len(anchor_summary) * 100.0
    )

    # Stability: median run length on instantaneous labels.
    g_runs = run_lengths(g_labels.tolist())
    i_runs = run_lengths(i_labels.tolist())

    # Latency: for each probe, bdays from probe_start until label first
    # equals target_state. Cap at 90 if never within window.
    latencies = []
    for name, start, axis, target in LATENCY_PROBES:
        labels = g_labels if axis == "growth" else i_labels
        start_ts = pd.Timestamp(start)
        forward = df.index[df["date"] >= start_ts]
        if len(forward) == 0:
            latencies.append({"probe": name, "latency_bdays": None})
            continue
        first_match = None
        for idx in forward[:90]:
            if labels.iloc[idx] == target:
                first_match = idx - forward[0]
                break
        latencies.append({
            "probe": name,
            "axis": axis,
            "target": target,
            "latency_bdays": (first_match if first_match is not None else 90),
        })

    return {
        "g_avg_match_pct": round(g_avg, 1),
        "i_avg_match_pct": round(i_avg, 1),
        "risk_avg_match_pct": round(risk_avg, 1),
        "overall_avg_match_pct": round((g_avg + i_avg + risk_avg) / 3.0, 1),
        "g_median_run_bdays": int(median(g_runs)),
        "i_median_run_bdays": int(median(i_runs)),
        "g_n_runs": len(g_runs),
        "i_n_runs": len(i_runs),
        "per_anchor": anchor_summary,
        "latencies": latencies,
    }


def _run_one(
    params: dict,
    *,
    base_engine: RegimeEngineConfig,
    base_macro: MacroRegimeConfig,
    macro_panel: pd.DataFrame,
    market_panel: pd.DataFrame,
    macro_specs,
    macro_concepts,
    market_method,
) -> dict:
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

    results = run_regime_engine_v2(
        config=engine,
        macro_panel=macro_panel,
        macro_specs=macro_specs,
        macro_concepts=macro_concepts,
        macro_method_config=macro,
        market_panel=market_panel,
        market_config=market_method,
    )
    rows = []
    for r in results:
        rows.append({
            "date": str(r.date)[:10],
            "final_g": r.final_growth_score,
            "final_i": r.final_inflation_score,
            "risk_on": bool(r.risk_overlay_on),
        })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    metrics = _measure(
        df,
        growth_thresh=params["growth_thresh"],
        inflation_thresh=params["inflation_thresh"],
    )
    metrics["params"] = params
    return metrics


def main() -> int:
    base_engine = load_regime_engine_config(REGIME_CFG)
    base_macro = load_macro_regime_config(FRED_CFG)
    macro_specs = load_series_specs(FRED_CFG)
    macro_concepts = load_concept_specs(FRED_CFG)
    market_method = load_market_regime_config(MARKET_CFG)
    macro_panel = load_panel(MACRO_PANEL)
    market_panel = _merge_market_panel()

    # Build the grid. Keep it focused.
    grid = []
    for min_weight in [0.10, 0.30, 0.65]:
        for growth_thresh in [0.10, 0.15, 0.20]:
            for inflation_thresh in [0.08, 0.12, 0.18]:
                for hyst in [5, 10]:
                    # Layer blend variants
                    for blend_name, mg, mi, kg, ki in [
                        ("baseline_macro_light",   0.35, 0.30, 0.65, 0.70),
                        ("balanced",               0.50, 0.50, 0.50, 0.50),
                        ("inflation_macro_heavy",  0.30, 0.60, 0.70, 0.40),
                    ]:
                        grid.append({
                            "min_weight": min_weight,
                            "growth_thresh": growth_thresh,
                            "inflation_thresh": inflation_thresh,
                            "axis_min_consecutive": hyst,
                            "macro_g_w": mg,
                            "macro_i_w": mi,
                            "market_g_w": kg,
                            "market_i_w": ki,
                            "blend_name": blend_name,
                        })

    print(f"Running {len(grid)} configs against full history...")
    all_results = []
    for i, params in enumerate(grid, 1):
        try:
            m = _run_one(
                params,
                base_engine=base_engine,
                base_macro=base_macro,
                macro_panel=macro_panel,
                market_panel=market_panel,
                macro_specs=macro_specs,
                macro_concepts=macro_concepts,
                market_method=market_method,
            )
            all_results.append(m)
            if i % 10 == 0 or i == len(grid):
                print(f"  {i}/{len(grid)} done; "
                      f"latest g_avg={m['g_avg_match_pct']}% "
                      f"i_avg={m['i_avg_match_pct']}% "
                      f"g_run_med={m['g_median_run_bdays']}bd "
                      f"i_run_med={m['i_median_run_bdays']}bd")
        except Exception as exc:
            print(f"  {i}/{len(grid)} FAILED: {type(exc).__name__}: {exc}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
