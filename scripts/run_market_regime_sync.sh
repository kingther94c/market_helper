#!/usr/bin/env bash
# Sync the Yahoo Finance market panel used by the regime-detection market_regime method.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIG="${MARKET_REGIME_CONFIG:-configs/regime_detection/market_regime.yml}"
CACHE_DIR="${MARKET_REGIME_CACHE_DIR:-data/interim/market_regime}"
PERIOD="${YAHOO_PERIOD:-max}"
INTERVAL="${YAHOO_INTERVAL:-1d}"

if [ ! -f "$CONFIG" ]; then
    if [ -f "${CONFIG%.yml}.example.yml" ]; then
        echo "No $CONFIG found; copy $(basename "${CONFIG%.yml}.example.yml") to $(basename "$CONFIG") first." >&2
    else
        echo "Missing market regime config: $CONFIG" >&2
    fi
    exit 1
fi

conda run -n py313 python -m market_helper.cli.main market-regime-sync \
    --config "$CONFIG" \
    --cache-dir "$CACHE_DIR" \
    --period "$PERIOD" \
    --interval "$INTERVAL"
