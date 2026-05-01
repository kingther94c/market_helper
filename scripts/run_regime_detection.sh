#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT="${1:-data/artifacts/regime_detection/regime_snapshots.json}"
MACRO_PANEL="${2:-data/interim/fred/macro_panel.feather}"
MARKET_PANEL="${3:-data/interim/market_regime/market_panel.feather}"

conda run -n py313 python -m market_helper.cli.main regime-detect-multi \
  --methods all \
  --macro-panel "$MACRO_PANEL" \
  --market-panel "$MARKET_PANEL" \
  --output "$OUT"
