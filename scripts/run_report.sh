#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${ENV_NAME:-py313}"
CONDA_BIN="${CONDA_BIN:-$(command -v conda || true)}"
ACCOUNT_ENV="${ACCOUNT_ENV:-prod}"
CANONICAL_LOCAL_CONFIG="${ROOT_DIR}/configs/portfolio_monitor/local.env"
LOCAL_CONFIG="${CANONICAL_LOCAL_CONFIG}"
DEFAULT_PROD_ACCOUNT_ID="${DEFAULT_PROD_ACCOUNT_ID:-}"
DEFAULT_DEV_ACCOUNT_ID="${DEFAULT_DEV_ACCOUNT_ID:-}"

if [[ -f "${LOCAL_CONFIG}" ]]; then
    # shellcheck disable=SC1090
    source "${LOCAL_CONFIG}"
fi

usage() {
    cat <<EOF
Usage:
  ./scripts/run_report.sh snapshot --positions PATH --prices PATH [--output PATH]
  ./scripts/run_report.sh ibkr-json --ibkr-positions PATH --ibkr-prices PATH [--output PATH] [--as-of ISO8601]
  ./scripts/run_report.sh ibkr-live [--output PATH] [--account ACCOUNT_ID] [--host HOST] [--port PORT] [--client-id ID] [--timeout SECONDS] [--as-of ISO8601]
  ./scripts/run_report.sh ibkr-live-html [--output PATH] [--positions-output PATH] [--returns PATH] [--proxy PATH] [--regime PATH] [--security-reference PATH] [--risk-config PATH] [--allocation-policy PATH] [--account ACCOUNT_ID] [--host HOST] [--port PORT] [--client-id ID] [--timeout SECONDS] [--as-of ISO8601]
  ./scripts/run_report.sh risk-html --positions-csv PATH [--returns PATH] [--proxy PATH] [--regime PATH] [--security-reference PATH] [--risk-config PATH] [--allocation-policy PATH] [--output PATH]
  ./scripts/run_report.sh security-reference-sync [--output PATH]
  ./scripts/run_report.sh etf-sector-sync --symbol TICKER [--symbol TICKER] [--output PATH] [--api-key KEY]
  ./scripts/run_report.sh mapping-table --workbook PATH [--output PATH]

Modes:
  snapshot    Generate a report from normalized position/price snapshots.
  ibkr-json   Generate a report from raw IBKR positions/prices payloads.
  ibkr-live   Generate a report from a live local TWS / IB Gateway session via ib_async.
  ibkr-live-html Generate live IBKR positions first, then build the HTML risk report in one run.
  risk-html   Generate an HTML risk report from a position CSV plus return/proxy inputs.
  security-reference-sync Rebuild the generated security reference from configs/security_universe.csv.
  etf-sector-sync Fetch ETF sector weights from FMP into configs/portfolio_monitor/us_sector_lookthrough.json.
  mapping-table Extract a security-reference CSV seed from a target workbook.

Environment:
  ENV_NAME    Conda environment name to use. Defaults to: py313
  CONDA_BIN   Optional explicit path to the conda executable.
  FMP_API_KEY Optional default API key for etf-sector-sync.
  ACCOUNT_ENV Live-account profile. Use prod or dev. Defaults to: prod
  LOCAL_CONFIG Optional local config file. Defaults to: configs/portfolio_monitor/local.env
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

open_report_path() {
    local path="$1"
    if command -v open >/dev/null 2>&1; then
        open "${path}" >/dev/null 2>&1 &
        return 0
    fi
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "${path}" >/dev/null 2>&1 &
        return 0
    fi
    return 1
}

resolve_live_account() {
    if [[ -n "${ACCOUNT_ID}" ]]; then
        return
    fi

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

    [[ -n "${ACCOUNT_ID}" ]] || fail "No default account configured for ACCOUNT_ENV=${ACCOUNT_ENV}. Set it in ${CANONICAL_LOCAL_CONFIG} or pass --account explicitly."
    echo "Using default ${ACCOUNT_ENV} live account: ${ACCOUNT_ID}"
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
        DEFAULT_OUTPUT="${ROOT_DIR}/data/artifacts/portfolio_monitor/position_report.csv"
        ;;
    ibkr-json)
        CLI_COMMAND="ibkr-position-report"
        DEFAULT_OUTPUT="${ROOT_DIR}/data/artifacts/portfolio_monitor/ibkr_position_report.csv"
        ;;
    ibkr-live)
        CLI_COMMAND="ibkr-live-position-report"
        DEFAULT_OUTPUT="${ROOT_DIR}/data/artifacts/portfolio_monitor/live_ibkr_position_report.csv"
        ;;
    ibkr-live-html)
        CLI_COMMAND=""
        DEFAULT_OUTPUT="${ROOT_DIR}/data/artifacts/portfolio_monitor/portfolio_risk_report.html"
        DEFAULT_POSITIONS_OUTPUT="${ROOT_DIR}/data/artifacts/portfolio_monitor/live_ibkr_position_report.csv"
        ;;
    risk-html)
        CLI_COMMAND="risk-html-report"
        DEFAULT_OUTPUT="${ROOT_DIR}/data/artifacts/portfolio_monitor/portfolio_risk_report.html"
        ;;
    security-reference-sync)
        CLI_COMMAND="security-reference-sync"
        DEFAULT_OUTPUT="${ROOT_DIR}/data/artifacts/portfolio_monitor/security_reference.csv"
        ;;
    etf-sector-sync)
        CLI_COMMAND="etf-sector-sync"
        DEFAULT_OUTPUT="${ROOT_DIR}/configs/portfolio_monitor/us_sector_lookthrough.json"
        ;;
    mapping-table)
        CLI_COMMAND="extract-report-mapping"
        DEFAULT_OUTPUT="${ROOT_DIR}/data/artifacts/portfolio_monitor/target_report_security_reference.csv"
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
POSITIONS_OUTPUT_PATH=""
ACCOUNT_ID=""
HOST="127.0.0.1"
PORT="7497"
CLIENT_ID="1"
TIMEOUT="4.0"
AS_OF=""
POSITIONS_CSV_PATH=""
RETURNS_PATH=""
PROXY_PATH=""
REGIME_PATH=""
SECURITY_REFERENCE_PATH=""
RISK_CONFIG_PATH=""
ALLOCATION_POLICY_PATH=""
WORKBOOK_PATH=""
FMP_API_KEY="${FMP_API_KEY:-}"
SYMBOLS=()

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
        --positions-output)
            require_value "$1" "${2:-}"
            POSITIONS_OUTPUT_PATH="$2"
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
        --regime)
            require_value "$1" "${2:-}"
            REGIME_PATH="$2"
            shift 2
            ;;
        --security-reference|--mapping-table)
            require_value "$1" "${2:-}"
            SECURITY_REFERENCE_PATH="$2"
            shift 2
            ;;
        --risk-config)
            require_value "$1" "${2:-}"
            RISK_CONFIG_PATH="$2"
            shift 2
            ;;
        --allocation-policy)
            require_value "$1" "${2:-}"
            ALLOCATION_POLICY_PATH="$2"
            shift 2
            ;;
        --workbook)
            require_value "$1" "${2:-}"
            WORKBOOK_PATH="$2"
            shift 2
            ;;
        --api-key)
            require_value "$1" "${2:-}"
            FMP_API_KEY="$2"
            shift 2
            ;;
        --symbol)
            require_value "$1" "${2:-}"
            SYMBOLS+=("$2")
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

if [[ "${MODE}" == "ibkr-live-html" ]]; then
    POSITIONS_OUTPUT_PATH="${POSITIONS_OUTPUT_PATH:-${DEFAULT_POSITIONS_OUTPUT}}"
    mkdir -p "$(dirname "${POSITIONS_OUTPUT_PATH}")"

    resolve_live_account

    LIVE_COMMAND=(
        "${CONDA_BIN}" run -n "${ENV_NAME}" python -m market_helper.cli.main ibkr-live-position-report
        --output "${POSITIONS_OUTPUT_PATH}"
        --host "${HOST}"
        --port "${PORT}"
        --client-id "${CLIENT_ID}"
        --timeout "${TIMEOUT}"
    )
    [[ -n "${ACCOUNT_ID}" ]] && LIVE_COMMAND+=(--account "${ACCOUNT_ID}")
    [[ -n "${AS_OF}" ]] && LIVE_COMMAND+=(--as-of "${AS_OF}")

    RISK_COMMAND=(
        "${CONDA_BIN}" run -n "${ENV_NAME}" python -m market_helper.cli.main risk-html-report
        --positions-csv "${POSITIONS_OUTPUT_PATH}"
        --output "${OUTPUT_PATH}"
    )
    [[ -n "${RETURNS_PATH}" ]] && { require_file "returns" "${RETURNS_PATH}"; RISK_COMMAND+=(--returns "${RETURNS_PATH}"); }
    [[ -n "${PROXY_PATH}" ]] && { require_file "proxy" "${PROXY_PATH}"; RISK_COMMAND+=(--proxy "${PROXY_PATH}"); }
    [[ -n "${REGIME_PATH}" ]] && { require_file "regime" "${REGIME_PATH}"; RISK_COMMAND+=(--regime "${REGIME_PATH}"); }
    [[ -n "${SECURITY_REFERENCE_PATH}" ]] && { require_file "security reference" "${SECURITY_REFERENCE_PATH}"; RISK_COMMAND+=(--security-reference "${SECURITY_REFERENCE_PATH}"); }
    [[ -n "${RISK_CONFIG_PATH}" ]] && { require_file "risk config" "${RISK_CONFIG_PATH}"; RISK_COMMAND+=(--risk-config "${RISK_CONFIG_PATH}"); }
    [[ -n "${ALLOCATION_POLICY_PATH}" ]] && { require_file "allocation policy" "${ALLOCATION_POLICY_PATH}"; RISK_COMMAND+=(--allocation-policy "${ALLOCATION_POLICY_PATH}"); }

    echo "Running ibkr-live-html workflow..."
    "${LIVE_COMMAND[@]}"
    echo "Live positions written to ${POSITIONS_OUTPUT_PATH}"
    "${RISK_COMMAND[@]}"
    echo "Report written to ${OUTPUT_PATH}"
    if open_report_path "${OUTPUT_PATH}"; then
        echo "Opened report in your default browser."
    else
        echo "No supported desktop opener found. Open manually: ${OUTPUT_PATH}"
    fi
    exit 0
fi

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
        resolve_live_account
        COMMAND+=(--host "${HOST}" --port "${PORT}" --client-id "${CLIENT_ID}" --timeout "${TIMEOUT}")
        [[ -n "${ACCOUNT_ID}" ]] && COMMAND+=(--account "${ACCOUNT_ID}")
        ;;
    risk-html)
        [[ -n "${POSITIONS_CSV_PATH}" ]] || fail "risk-html mode requires --positions-csv"
        require_file "positions csv" "${POSITIONS_CSV_PATH}"
        COMMAND+=(--positions-csv "${POSITIONS_CSV_PATH}")
        [[ -n "${RETURNS_PATH}" ]] && { require_file "returns" "${RETURNS_PATH}"; COMMAND+=(--returns "${RETURNS_PATH}"); }
        [[ -n "${PROXY_PATH}" ]] && { require_file "proxy" "${PROXY_PATH}"; COMMAND+=(--proxy "${PROXY_PATH}"); }
        [[ -n "${REGIME_PATH}" ]] && { require_file "regime" "${REGIME_PATH}"; COMMAND+=(--regime "${REGIME_PATH}"); }
        [[ -n "${SECURITY_REFERENCE_PATH}" ]] && { require_file "security reference" "${SECURITY_REFERENCE_PATH}"; COMMAND+=(--security-reference "${SECURITY_REFERENCE_PATH}"); }
        [[ -n "${RISK_CONFIG_PATH}" ]] && { require_file "risk config" "${RISK_CONFIG_PATH}"; COMMAND+=(--risk-config "${RISK_CONFIG_PATH}"); }
        [[ -n "${ALLOCATION_POLICY_PATH}" ]] && { require_file "allocation policy" "${ALLOCATION_POLICY_PATH}"; COMMAND+=(--allocation-policy "${ALLOCATION_POLICY_PATH}"); }
        ;;
    security-reference-sync)
        :
        ;;
    etf-sector-sync)
        [[ ${#SYMBOLS[@]} -gt 0 ]] || fail "etf-sector-sync mode requires at least one --symbol"
        for symbol in "${SYMBOLS[@]}"; do
            COMMAND+=(--symbol "${symbol}")
        done
        [[ -n "${FMP_API_KEY}" ]] && COMMAND+=(--api-key "${FMP_API_KEY}")
        ;;
    mapping-table)
        [[ -n "${WORKBOOK_PATH}" ]] || fail "mapping-table mode requires --workbook"
        require_file "workbook" "${WORKBOOK_PATH}"
        COMMAND+=(--workbook "${WORKBOOK_PATH}")
        ;;
esac

[[ -n "${AS_OF}" ]] && COMMAND+=(--as-of "${AS_OF}")

echo "Running ${MODE} report workflow..."
"${COMMAND[@]}"
echo "Report written to ${OUTPUT_PATH}"
