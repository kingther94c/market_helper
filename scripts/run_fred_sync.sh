#!/usr/bin/env bash
# Sync the FRED macro panel used by the regime-detection macro_rules method.
#
# Reads series definitions from configs/regime_detection/fred_series.yml
# (override with FRED_SERIES_CONFIG). Writes per-series feather caches and
# the joined daily panel to data/interim/fred/.
#
# Requires FRED_API_KEY in the environment (or set via local.env).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIG="${FRED_SERIES_CONFIG:-configs/regime_detection/fred_series.yml}"
CACHE_DIR="${FRED_CACHE_DIR:-data/interim/fred}"
START="${FRED_OBSERVATION_START:-2005-01-01}"
FORCE="${FRED_FORCE_REFRESH:-0}"

if [ ! -f "$CONFIG" ]; then
    if [ -f "${CONFIG%.yml}.example.yml" ]; then
        echo "No $CONFIG found; copy $(basename "${CONFIG%.yml}.example.yml") to $(basename "$CONFIG") first." >&2
    else
        echo "Missing FRED series config: $CONFIG" >&2
    fi
    exit 1
fi

if [ -z "${FRED_API_KEY:-}" ] && [ -f configs/portfolio_monitor/local.env ]; then
    set -a
    # shellcheck disable=SC1091
    source configs/portfolio_monitor/local.env
    set +a
fi

if [ -z "${FRED_API_KEY:-}" ]; then
    echo "FRED_API_KEY is not set. Add it to configs/portfolio_monitor/local.env or the environment." >&2
    exit 1
fi

FORCE_FLAG=""
if [ "$FORCE" = "1" ] || [ "$FORCE" = "true" ]; then
    FORCE_FLAG="--force"
fi

conda run -n py313 python -m market_helper.cli.main fred-macro-sync \
    --config "$CONFIG" \
    --cache-dir "$CACHE_DIR" \
    --observation-start "$START" \
    $FORCE_FLAG
