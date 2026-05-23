"""Rebuild the FRED macro panel from cached series only — no API call.

Useful when fred-macro-sync's incremental API fetch is failing but the
raw series cache is good enough. Applies transforms (including the new
Q9 velocity specs) and writes data/interim/fred/macro_panel.feather.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from market_helper.data_sources.fred.macro_panel import (
    DEFAULT_CACHE_DIR,
    DEFAULT_PANEL_FILENAME,
    build_panel,
    load_series_specs,
)

CONFIG = REPO / "configs/regime_detection/fred_series.yml"
CACHE_DIR = REPO / DEFAULT_CACHE_DIR
PANEL_PATH = CACHE_DIR / DEFAULT_PANEL_FILENAME

specs = load_series_specs(CONFIG)
print(f"loaded {len(specs)} specs from {CONFIG}")
panel = build_panel(specs, cache_dir=CACHE_DIR)
print(f"built panel: {panel.shape}, last date = {panel['date'].max() if not panel.empty else 'n/a'}")
print(f"columns sample: {[c for c in panel.columns if not c.startswith('_age')][:10]}")
velocity_cols = [c for c in panel.columns if "velocity" in c]
print(f"velocity columns: {velocity_cols}")
panel.to_feather(PANEL_PATH)
print(f"wrote {PANEL_PATH} ({PANEL_PATH.stat().st_size:,} bytes)")
