#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${ENV_NAME:-py313}"
CONDA_BIN="${CONDA_BIN:-$(command -v conda || true)}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8080}"
URL="http://${HOST}:${PORT}/portfolio"
AUTO_OPEN="${AUTO_OPEN:-1}"
FALLBACK_OPEN="${FALLBACK_OPEN:-1}"
OPEN_WAIT_SECONDS="${OPEN_WAIT_SECONDS:-20}"
CACHE_ROOT="${CACHE_ROOT:-${ROOT_DIR}/.cache}"
MPLCONFIGDIR="${MPLCONFIGDIR:-${CACHE_ROOT}/matplotlib}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-${CACHE_ROOT}/xdg}"

if [[ -z "${CONDA_BIN}" ]]; then
  echo "conda executable not found" >&2
  exit 1
fi

cd "${ROOT_DIR}"
echo "Starting Portfolio Monitor at ${URL}"

mkdir -p "${MPLCONFIGDIR}" "${XDG_CACHE_HOME}"

export MARKET_HELPER_UI_SHOW=0
export MPLCONFIGDIR
export XDG_CACHE_HOME
"${CONDA_BIN}" run -n "${ENV_NAME}" python -m market_helper.presentation.dashboard.app --host "${HOST}" --port "${PORT}" --no-show &
SERVER_PID=$!

cleanup() {
  if kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
  fi
}

trap cleanup INT TERM

if [[ "${AUTO_OPEN}" != "0" && "${FALLBACK_OPEN}" != "0" ]]; then
  ATTEMPTS=$(( OPEN_WAIT_SECONDS * 2 ))
  READY=0
  for ((i=0; i<ATTEMPTS; i++)); do
    if curl -fsS "${URL}" >/dev/null 2>&1; then
      READY=1
      break
    fi
    sleep 0.5
  done

  if [[ "${READY}" == "1" ]]; then
    if command -v open >/dev/null 2>&1; then
      open "${URL}" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
      xdg-open "${URL}" >/dev/null 2>&1 || true
    fi
  else
    echo "Warning: ${URL} did not become ready within ${OPEN_WAIT_SECONDS}s" >&2
  fi
fi

wait "${SERVER_PID}"
