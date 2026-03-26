#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${ENV_NAME:-py313}"
CONDA_BIN="${CONDA_BIN:-$(command -v conda || true)}"
ACCOUNT_ENV="${ACCOUNT_ENV:-prod}"
LOCAL_ACCOUNT_CONFIG="${ROOT_DIR}/configs/report_accounts.local.env"
DEFAULT_PROD_ACCOUNT_ID="${DEFAULT_PROD_ACCOUNT_ID:-}"
DEFAULT_DEV_ACCOUNT_ID="${DEFAULT_DEV_ACCOUNT_ID:-}"

if [[ -f "${LOCAL_ACCOUNT_CONFIG}" ]]; then
    # shellcheck disable=SC1090
    source "${LOCAL_ACCOUNT_CONFIG}"
fi

usage() {
    cat <<EOF
Usage:
  ./scripts/run_report.sh snapshot --positions PATH --prices PATH [--output PATH]
  ./scripts/run_report.sh ibkr-json --ibkr-positions PATH --ibkr-prices PATH [--output PATH] [--as-of ISO8601]
  ./scripts/run_report.sh ibkr-live [--output PATH] [--account ACCOUNT_ID] [--host HOST] [--port PORT] [--client-id ID] [--timeout SECONDS] [--as-of ISO8601]
  ./scripts/run_report.sh risk-html --positions-csv PATH --returns PATH [--proxy PATH] [--output PATH]

Modes:
  snapshot    Generate a report from normalized position/price snapshots.
  ibkr-json   Generate a report from raw IBKR positions/prices payloads.
  ibkr-live   Generate a report from a live local TWS / IB Gateway session via ib_async.
  risk-html   Generate an HTML risk report from a position CSV plus return/proxy inputs.

Environment:
  ENV_NAME    Conda environment name to use. Defaults to: py313
  CONDA_BIN   Optional explicit path to the conda executable.
  ACCOUNT_ENV Live-account profile. Use prod or dev. Defaults to: prod
  LOCAL_ACCOUNT_CONFIG Optional local account config file. Defaults to: configs/report_accounts.local.env
EOF
}

fail() {
    echo "$1" >&2
    exit 1
}

lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

require_value() {
    local flag="$1"
    local value="${2:-}"
    [[ -n "${value}" ]] || fail "Missing value for ${flag}"
}

require_file() {
    local label="$1"
    local path="$2"
    [[ -f "${path}" ]] || fail "Missing ${label} file: ${path}"
}

[[ $# -gt 0 ]] || {
    usage
    exit 1
}

case "${1}" in
    -h|--help)
        usage
        exit 0
        ;;
esac

MODE="$1"
shift

case "${MODE}" in
    snapshot)
        CLI_COMMAND="position-report"
        DEFAULT_OUTPUT="${ROOT_DIR}/outputs/reports/position_report.csv"
        ;;
    ibkr-json)
        CLI_COMMAND="ibkr-position-report"
        DEFAULT_OUTPUT="${ROOT_DIR}/outputs/reports/ibkr_position_report.csv"
        ;;
    ibkr-live)
        CLI_COMMAND="ibkr-live-position-report"
        DEFAULT_OUTPUT="${ROOT_DIR}/outputs/reports/live_ibkr_position_report.csv"
        ;;
    risk-html)
        CLI_COMMAND="risk-html-report"
        DEFAULT_OUTPUT="${ROOT_DIR}/outputs/reports/portfolio_risk_report.html"
        ;;
    *)
        fail "Unknown mode: ${MODE}"
        ;;
esac

POSITIONS_PATH=""
PRICES_PATH=""
IBKR_POSITIONS_PATH=""
IBKR_PRICES_PATH=""
OUTPUT_PATH=""
ACCOUNT_ID=""
HOST="127.0.0.1"
PORT="7497"
CLIENT_ID="1"
TIMEOUT="4.0"
AS_OF=""
POSITIONS_CSV_PATH=""
RETURNS_PATH=""
PROXY_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --positions)
            require_value "$1" "${2:-}"
            POSITIONS_PATH="$2"
            shift 2
            ;;
        --prices)
            require_value "$1" "${2:-}"
            PRICES_PATH="$2"
            shift 2
            ;;
        --ibkr-positions)
            require_value "$1" "${2:-}"
            IBKR_POSITIONS_PATH="$2"
            shift 2
            ;;
        --ibkr-prices)
            require_value "$1" "${2:-}"
            IBKR_PRICES_PATH="$2"
            shift 2
            ;;
        --output)
            require_value "$1" "${2:-}"
            OUTPUT_PATH="$2"
            shift 2
            ;;
        --account)
            require_value "$1" "${2:-}"
            ACCOUNT_ID="$2"
            shift 2
            ;;
        --host)
            require_value "$1" "${2:-}"
            HOST="$2"
            shift 2
            ;;
        --port)
            require_value "$1" "${2:-}"
            PORT="$2"
            shift 2
            ;;
        --client-id)
            require_value "$1" "${2:-}"
            CLIENT_ID="$2"
            shift 2
            ;;
        --as-of)
            require_value "$1" "${2:-}"
            AS_OF="$2"
            shift 2
            ;;
        --positions-csv)
            require_value "$1" "${2:-}"
            POSITIONS_CSV_PATH="$2"
            shift 2
            ;;
        --returns)
            require_value "$1" "${2:-}"
            RETURNS_PATH="$2"
            shift 2
            ;;
        --proxy)
            require_value "$1" "${2:-}"
            PROXY_PATH="$2"
            shift 2
            ;;
        --timeout)
            require_value "$1" "${2:-}"
            TIMEOUT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown argument: $1"
            ;;
    esac
done

[[ -n "${CONDA_BIN}" ]] || fail "Conda is required. Install conda or set CONDA_BIN to your conda executable."

OUTPUT_PATH="${OUTPUT_PATH:-${DEFAULT_OUTPUT}}"
mkdir -p "$(dirname "${OUTPUT_PATH}")"

COMMAND=(
    "${CONDA_BIN}" run -n "${ENV_NAME}" python -m market_helper.cli.main "${CLI_COMMAND}"
    --output "${OUTPUT_PATH}"
)

case "${MODE}" in
    snapshot)
        [[ -n "${POSITIONS_PATH}" ]] || fail "snapshot mode requires --positions"
        [[ -n "${PRICES_PATH}" ]] || fail "snapshot mode requires --prices"
        require_file "positions" "${POSITIONS_PATH}"
        require_file "prices" "${PRICES_PATH}"
        COMMAND+=(--positions "${POSITIONS_PATH}" --prices "${PRICES_PATH}")
        ;;
    ibkr-json)
        [[ -n "${IBKR_POSITIONS_PATH}" ]] || fail "ibkr-json mode requires --ibkr-positions"
        [[ -n "${IBKR_PRICES_PATH}" ]] || fail "ibkr-json mode requires --ibkr-prices"
        require_file "IBKR positions" "${IBKR_POSITIONS_PATH}"
        require_file "IBKR prices" "${IBKR_PRICES_PATH}"
        COMMAND+=(--ibkr-positions "${IBKR_POSITIONS_PATH}" --ibkr-prices "${IBKR_PRICES_PATH}")
        ;;
    ibkr-live)
        if [[ -z "${ACCOUNT_ID}" ]]; then
            case "$(lower "${ACCOUNT_ENV}")" in
                prod|production)
                    ACCOUNT_ID="${DEFAULT_PROD_ACCOUNT_ID}"
                    ;;
                dev|development|paper|test)
                    ACCOUNT_ID="${DEFAULT_DEV_ACCOUNT_ID}"
                    ;;
                *)
                    fail "Unsupported ACCOUNT_ENV=${ACCOUNT_ENV}. Use prod or dev, or pass --account explicitly."
                    ;;
            esac
            [[ -n "${ACCOUNT_ID}" ]] || fail "No default account configured for ACCOUNT_ENV=${ACCOUNT_ENV}. Set it in ${LOCAL_ACCOUNT_CONFIG} or pass --account explicitly."
            echo "Using default ${ACCOUNT_ENV} live account: ${ACCOUNT_ID}"
        fi
        COMMAND+=(--host "${HOST}" --port "${PORT}" --client-id "${CLIENT_ID}" --timeout "${TIMEOUT}")
        [[ -n "${ACCOUNT_ID}" ]] && COMMAND+=(--account "${ACCOUNT_ID}")
        ;;
    risk-html)
        [[ -n "${POSITIONS_CSV_PATH}" ]] || fail "risk-html mode requires --positions-csv"
        [[ -n "${RETURNS_PATH}" ]] || fail "risk-html mode requires --returns"
        require_file "positions csv" "${POSITIONS_CSV_PATH}"
        require_file "returns" "${RETURNS_PATH}"
        COMMAND+=(--positions-csv "${POSITIONS_CSV_PATH}" --returns "${RETURNS_PATH}")
        [[ -n "${PROXY_PATH}" ]] && { require_file "proxy" "${PROXY_PATH}"; COMMAND+=(--proxy "${PROXY_PATH}"); }
        ;;
esac

[[ -n "${AS_OF}" ]] && COMMAND+=(--as-of "${AS_OF}")

echo "Running ${MODE} report workflow..."
"${COMMAND[@]}"
echo "Report written to ${OUTPUT_PATH}"
