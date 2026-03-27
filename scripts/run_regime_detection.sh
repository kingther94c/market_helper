#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

OUT="${1:-outputs/reports/regime_snapshots.json}"
RETURNS="${2:-data/processed/regime_returns.json}"
PROXY="${3:-data/processed/regime_proxies.json}"

conda run -n py313 python -m market_helper.cli.main regime-detect \
  --returns "$RETURNS" \
  --proxy "$PROXY" \
  --output "$OUT" \
  --indicators-output data/processed/indicator_snapshots.json
