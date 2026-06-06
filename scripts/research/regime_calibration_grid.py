"""Grid-search calibration research for the regime engine's risk overlay
and axis hysteresis.

Reads each checked-in anchor fixture (COVID 2020, GFC 2008-09, 2022
inflation, 2025 tariff), runs the market-implied layer under every
combination of the parameter grid, and measures:

  - true-positive trigger rate inside the crisis window
  - false-positive trigger rate inside the matched benign window
  - latency to first stress trigger from the named critical day
  - max-depth growth score during the crisis window
  - median axis-state run length (whipsaw / over-smoothing diagnostic)

Outputs a JSON record per (config × anchor) to data/research_artifacts/
for downstream HTML rendering.

Design choices documented inline; this is research code, not production
code — kept short, single-file, no test coverage.
"""
from __future__ import annotations

import itertools
import json
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Sequence

import pandas as pd

from market_helper.regimes.engine_v2 import (
    LayerConfig,
    RegimeEngineConfig,
    RegimeThresholds,
    RiskOverlayConfig,
    load_regime_engine_config,
    run_regime_engine_v2,
)
from market_helper.regimes.methods.market_regime import load_market_regime_config


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "unit" / "regimes" / "fixtures"
OUT_DIR = REPO_ROOT / "data" / "research_artifacts"
REGIME_ENGINE_CONFIG = REPO_ROOT / "configs" / "regime_detection" / "regime_engine.yml"
MARKET_REGIME_CONFIG = REPO_ROOT / "configs" / "regime_detection" / "market_regime.yml"


# ---------------------------------------------------------------------------
# Anchor definitions: crisis + benign window pairs.
# Crisis = where risk overlay SHOULD fire. Benign = where it SHOULD NOT.
# Critical day = the single date most associated with the episode start.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Anchor:
    name: str
    fixture: str
    crisis_window: tuple[str, str]
    benign_window: tuple[str, str]
    critical_day: str  # date stress overlay should ideally trigger on or near
    trough_day: str  # date with the deepest expected growth score


ANCHORS: tuple[Anchor, ...] = (
    Anchor(
        name="COVID 2020",
        fixture="market_panel_covid_2020.feather",
        crisis_window=("2020-02-24", "2020-04-30"),
        benign_window=("2019-06-03", "2020-02-19"),
        critical_day="2020-02-24",  # first big-vol session (SPY -3.4%)
        trough_day="2020-03-18",
    ),
    Anchor(
        name="GFC 2008-09",
        fixture="market_panel_gfc_2008.feather",
        crisis_window=("2008-09-15", "2008-12-31"),
        benign_window=("2007-12-03", "2008-08-29"),
        critical_day="2008-09-15",  # Lehman bankruptcy day
        trough_day="2008-11-20",
    ),
    Anchor(
        name="2022 Inflation Surge",
        fixture="market_panel_inflation_2022.feather",
        crisis_window=("2022-06-01", "2022-10-31"),
        benign_window=("2021-09-01", "2022-02-28"),
        critical_day="2022-06-13",  # post-CPI 9.1% panic
        trough_day="2022-10-12",
    ),
    Anchor(
        name="2025 Tariff Shock",
        fixture="market_panel_tariff_2025.feather",
        crisis_window=("2025-04-02", "2025-05-15"),
        benign_window=("2024-06-03", "2025-03-31"),
        critical_day="2025-04-02",  # Liberation Day announcement
        trough_day="2025-04-09",
    ),
)


# ---------------------------------------------------------------------------
# Grid: parameters to sweep. Cardinality kept small (4 * 4 * 3 = 48 configs
# per anchor) so the run completes in a few minutes.
# ---------------------------------------------------------------------------


GRID = {
    "risk_enter_threshold": [0.55, 0.65, 0.75, 0.85],
    "risk_min_consecutive_days": [1, 2, 3, 5],
    "axis_min_consecutive_days": [3, 5, 10],
}

CURRENT_CONFIG = {
    "risk_enter_threshold": 0.75,
    "risk_min_consecutive_days": 3,
    "axis_min_consecutive_days": 5,
}


@dataclass
class RunMetrics:
    config: dict
    anchor: str
    crisis_days: int = 0
    crisis_stress_days: int = 0
    benign_days: int = 0
    benign_stress_days: int = 0
    critical_day_stress: bool | None = None  # None if date missing from results
    critical_day_latency_bdays: int | None = None  # bdays from critical_day to first stress on/after
    trough_growth_score: float | None = None
    crisis_max_negative_growth: float | None = None
    median_axis_run_length: float | None = None

    def to_dict(self) -> dict:
        out = dict(self.__dict__)
        return out


def _build_config(base_cfg: RegimeEngineConfig, params: dict) -> RegimeEngineConfig:
    """Clone base config and apply grid parameters. Market-only: macro + ML disabled."""
    layers = dict(base_cfg.layers)
    layers["macro_nowcast"] = LayerConfig(enabled=False)
    new_risk = replace(
        base_cfg.risk_overlay,
        enter_threshold=float(params["risk_enter_threshold"]),
        min_consecutive_days=int(params["risk_min_consecutive_days"]),
    )
    new_thresh = replace(
        base_cfg.regime_thresholds,
        min_consecutive_days=int(params["axis_min_consecutive_days"]),
    )
    return replace(
        base_cfg,
        layers=layers,
        risk_overlay=new_risk,
        regime_thresholds=new_thresh,
    )


def _median_axis_run_length(states: Sequence[str]) -> float | None:
    if not states:
        return None
    runs: list[int] = []
    cur = states[0]
    n = 1
    for s in states[1:]:
        if s == cur:
            n += 1
        else:
            runs.append(n)
            cur = s
            n = 1
    runs.append(n)
    return float(pd.Series(runs).median())


def _measure(results, anchor: Anchor, config_dict: dict) -> RunMetrics:
    crisis_start, crisis_end = anchor.crisis_window
    benign_start, benign_end = anchor.benign_window
    crisis_lo, crisis_hi = pd.Timestamp(crisis_start), pd.Timestamp(crisis_end)
    benign_lo, benign_hi = pd.Timestamp(benign_start), pd.Timestamp(benign_end)
    critical = pd.Timestamp(anchor.critical_day)
    trough = pd.Timestamp(anchor.trough_day)

    by_date = {pd.Timestamp(str(r.date)[:10]): r for r in results}
    metrics = RunMetrics(config=config_dict, anchor=anchor.name)

    growth_states: list[str] = []
    crisis_growth_min = None
    for d, r in sorted(by_date.items()):
        if benign_lo <= d <= benign_hi:
            metrics.benign_days += 1
            if r.risk_overlay_on:
                metrics.benign_stress_days += 1
        if crisis_lo <= d <= crisis_hi:
            metrics.crisis_days += 1
            if r.risk_overlay_on:
                metrics.crisis_stress_days += 1
            g = float(r.final_growth_score)
            if crisis_growth_min is None or g < crisis_growth_min:
                crisis_growth_min = g
        # axis state for median-run-length stat (whole fixture)
        growth_states.append(_axis_state_label(r.final_growth_score, threshold=0.15))

    metrics.crisis_max_negative_growth = crisis_growth_min
    metrics.median_axis_run_length = _median_axis_run_length(growth_states)

    # Critical-day stress + latency
    if critical in by_date:
        metrics.critical_day_stress = bool(by_date[critical].risk_overlay_on)
        # latency: bdays from critical_day to first stress day on or after
        forward = [d for d in sorted(by_date) if d >= critical and by_date[d].risk_overlay_on]
        if forward:
            first_stress = forward[0]
            metrics.critical_day_latency_bdays = int((first_stress - critical).days)
    else:
        metrics.critical_day_stress = None
        metrics.critical_day_latency_bdays = None

    # Trough growth
    if trough in by_date:
        metrics.trough_growth_score = float(by_date[trough].final_growth_score)

    return metrics


def _axis_state_label(score: float, *, threshold: float) -> str:
    if score is None or pd.isna(score):
        return "NaN"
    if score > threshold:
        return "Up"
    if score < -threshold:
        return "Down"
    return "Neutral"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base_engine_cfg = load_regime_engine_config(REGIME_ENGINE_CONFIG)
    market_cfg = load_market_regime_config(MARKET_REGIME_CONFIG)

    all_runs: list[dict] = []
    grid_combinations = list(itertools.product(
        GRID["risk_enter_threshold"],
        GRID["risk_min_consecutive_days"],
        GRID["axis_min_consecutive_days"],
    ))
    total = len(grid_combinations) * len(ANCHORS)
    print(f"Running {total} (config x anchor) combinations...")

    counter = 0
    for ret, rcd, acd in grid_combinations:
        params = {
            "risk_enter_threshold": ret,
            "risk_min_consecutive_days": rcd,
            "axis_min_consecutive_days": acd,
        }
        cfg = _build_config(base_engine_cfg, params)
        for anchor in ANCHORS:
            counter += 1
            panel = pd.read_feather(FIXTURES_DIR / anchor.fixture)
            results = run_regime_engine_v2(
                config=cfg, market_panel=panel, market_config=market_cfg
            )
            metrics = _measure(results, anchor, params)
            all_runs.append(metrics.to_dict())
            if counter % 16 == 0 or counter == total:
                print(f"  {counter}/{total} done")

    out_path = OUT_DIR / "calibration_grid_results.json"
    out_path.write_text(json.dumps(all_runs, indent=2), encoding="utf-8")
    print(f"wrote {out_path}: {len(all_runs)} runs")

    # Also write a CSV for spreadsheeting
    csv_path = OUT_DIR / "calibration_grid_results.csv"
    rows = []
    for r in all_runs:
        row = {**r["config"]}
        row["anchor"] = r["anchor"]
        for k in (
            "crisis_days", "crisis_stress_days",
            "benign_days", "benign_stress_days",
            "critical_day_stress", "critical_day_latency_bdays",
            "trough_growth_score", "crisis_max_negative_growth",
            "median_axis_run_length",
        ):
            row[k] = r.get(k)
        rows.append(row)
    pd.DataFrame(rows).to_csv(csv_path, index=False)
    print(f"wrote {csv_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
