"""Sanity-run ONE config end-to-end to time the engine and verify mechanics."""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.research.macro_calibration_grid import (
    _run_one,
    _merge_market_panel,
    load_regime_engine_config,
    load_macro_regime_config,
    load_series_specs,
    load_concept_specs,
    load_market_regime_config,
    load_panel,
    REGIME_CFG,
    FRED_CFG,
    MARKET_CFG,
    MACRO_PANEL,
)

print("loading panels and configs...", flush=True)
base_engine = load_regime_engine_config(REGIME_CFG)
base_macro = load_macro_regime_config(FRED_CFG)
macro_specs = load_series_specs(FRED_CFG)
macro_concepts = load_concept_specs(FRED_CFG)
market_method = load_market_regime_config(MARKET_CFG)
macro_panel = load_panel(MACRO_PANEL)
market_panel = _merge_market_panel()
print(f"loaded; macro_panel {macro_panel.shape}, market_panel {market_panel.shape}", flush=True)

params = dict(
    min_weight=0.65, growth_thresh=0.15, inflation_thresh=0.12,
    axis_min_consecutive=5, macro_g_w=0.35, macro_i_w=0.30,
    market_g_w=0.65, market_i_w=0.70, blend_name="baseline",
)
t0 = time.perf_counter()
m = _run_one(
    params,
    base_engine=base_engine, base_macro=base_macro,
    macro_panel=macro_panel, market_panel=market_panel,
    macro_specs=macro_specs, macro_concepts=macro_concepts,
    market_method=market_method,
)
t1 = time.perf_counter()
print(f"1 run took {t1 - t0:.1f}s", flush=True)
print(f"overall={m['overall_avg_match_pct']}% g={m['g_avg_match_pct']}% "
      f"i={m['i_avg_match_pct']}% risk={m['risk_avg_match_pct']}%", flush=True)
print(f"g_med={m['g_median_run_bdays']}bd i_med={m['i_median_run_bdays']}bd", flush=True)
print(f"latencies: {m['latencies']}", flush=True)
