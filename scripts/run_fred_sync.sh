#!/usr/bin/env bash
# Sync the FRED macro panel used by the regime-detection macro_regime method.
#
# Reads series definitions from configs/regime_detection/fred_series.yml
# (override with FRED_SERIES_CONFIG). Writes per-series feather caches and
# the joined daily panel to data/interim/fred/.
#
# Requires FRED_API_KEY in the environment or local.env. local.env is read
# from <MARKET_HELPER_GDRIVE_ROOT>/local.env when ROOT is set, otherwise
# falls back to configs/portfolio_monitor/local.env.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DEFAULT_LOCAL_CONFIG="configs/portfolio_monitor/local.env"
if [ -n "${MARKET_HELPER_GDRIVE_ROOT:-}" ] && [ -f "${MARKET_HELPER_GDRIVE_ROOT}/local.env" ]; then
    LOCAL_CONFIG="${MARKET_HELPER_GDRIVE_ROOT}/local.env"
else
    LOCAL_CONFIG="${DEFAULT_LOCAL_CONFIG}"
fi

CONFIG="${FRED_SERIES_CONFIG:-configs/regime_detection/fred_series.yml}"
CACHE_DIR="${FRED_CACHE_DIR:-data/interim/fred}"
START="${FRED_OBSERVATION_START:-2005-01-01}"
FORCE="${FRED_FORCE_REFRESH:-0}"

if [ ! -f "$CONFIG" ]; then
    echo "Missing FRED series config: $CONFIG" >&2
    exit 1
fi

if [ -z "${FRED_API_KEY:-}" ] && [ -f "${LOCAL_CONFIG}" ]; then
    set -a
    # shellcheck disable=SC1090
    source "${LOCAL_CONFIG}"
    set +a
fi

if [ -z "${FRED_API_KEY:-}" ]; then
    echo "FRED_API_KEY is not set. Export it (e.g. 'export FRED_API_KEY=...') or add it to ${LOCAL_CONFIG}." >&2
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
