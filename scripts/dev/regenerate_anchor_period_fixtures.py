"""Regenerate the pinned anchor-period fixtures used by regime backtest tests.

Slices `data/interim/market_regime/market_panel.feather` (produced by
`market-regime-sync --force`) into per-anchor windows and writes them under
`tests/unit/regimes/fixtures/`. Run this after a config change that materially
alters the symbol set or the windows the engine reads, then re-run
`tests/unit/regimes/test_anchor_periods.py` and update the pinned expectations
if they shifted intentionally.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PANEL = REPO_ROOT / "data" / "interim" / "market_regime" / "market_panel.feather"
FIXTURE_DIR = REPO_ROOT / "tests" / "unit" / "regimes" / "fixtures"

ANCHORS: tuple[tuple[str, str, str], ...] = (
    # (filename stem, start_date, end_date)
    # COVID 2020: ~1 year of warmup + crash + recovery
    ("market_panel_covid_2020", "2019-01-01", "2020-12-31"),
    # GFC 2008-09: warmup from mid-2007 (~5 months of warmup eaten by
    # normalization windows; first usable result lands ~Nov 2007), through
    # the recovery year.
    ("market_panel_gfc_2008", "2007-06-01", "2009-12-31"),
    # 2022 inflation surge: warmup from mid-2021, through the post-peak
    # disinflation period. Documents the market-only-layer LIMITATION
    # case where commodity proxies decouple from headline CPI.
    ("market_panel_inflation_2022", "2021-06-01", "2023-06-30"),
    # 2025 tariff shock: warmup from start of 2024, through April-Sep 2025
    # tariff regime. Recent + textbook stagflationary shock.
    ("market_panel_tariff_2025", "2024-01-01", "2025-09-30"),
)


def main() -> int:
    if not SOURCE_PANEL.exists():
        raise SystemExit(
            f"Missing source panel at {SOURCE_PANEL}. Run "
            "`python -m market_helper.cli.main market-regime-sync --force` first."
        )
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    panel = pd.read_feather(SOURCE_PANEL)
    for stem, start, end in ANCHORS:
        sliced = panel[(panel["date"] >= start) & (panel["date"] <= end)].reset_index(drop=True)
        out_path = FIXTURE_DIR / f"{stem}.feather"
        sliced.to_feather(out_path)
        print(
            f"wrote {out_path.name}: rows={len(sliced)} "
            f"range=[{sliced['date'].min()} .. {sliced['date'].max()}] "
            f"bytes={out_path.stat().st_size}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
