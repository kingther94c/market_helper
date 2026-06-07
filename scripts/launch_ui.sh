#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="${ENV_NAME:-py313}"
CONDA_BIN="${CONDA_BIN:-$(command -v conda || true)}"

# HOST is the *bind* address the dashboard listens on. Default 127.0.0.1
# — the dashboard has no auth of its own, so binding broadly (0.0.0.0)
# would expose it to anything on the LAN / Wi-Fi.
#
# For cross-device access from a Tailnet, use **Tailscale Serve** instead
# of broadening the bind. One-shot setup:
#   tailscale serve --bg https / http://127.0.0.1:18080
# Then any tailnet device reaches the report at
#   https://<this-host>.<tailnet>.ts.net/portfolio/portfolio_dashboard_report.html
# Tailscale's tunnel + ACLs are the security boundary; the local bind
# stays loopback-only and the LAN can't see the port.
#
# To override (e.g. broaden the bind for a quick same-LAN test):
#   HOST=0.0.0.0 ./scripts/launch_ui.sh
HOST="${HOST:-127.0.0.1}"
# 18080 instead of the more common 8080 to dodge collisions with Tomcat /
# Jenkins / Spring Boot / Docker port mappings on developer machines.
PORT="${PORT:-18080}"

# Browser navigates to a concrete address; 0.0.0.0 is a listen-only
# sentinel, so substitute loopback for the browser/redirect target.
if [[ "${HOST}" == "0.0.0.0" || "${HOST}" == "::" ]]; then
  OPEN_HOST="127.0.0.1"
else
  OPEN_HOST="${HOST}"
fi
URL="http://${OPEN_HOST}:${PORT}/portfolio"

AUTO_OPEN="${AUTO_OPEN:-1}"
FALLBACK_OPEN="${FALLBACK_OPEN:-1}"
CACHE_ROOT="${CACHE_ROOT:-${ROOT_DIR}/.cache}"
MPLCONFIGDIR="${MPLCONFIGDIR:-${CACHE_ROOT}/matplotlib}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-${CACHE_ROOT}/xdg}"

if [[ -z "${CONDA_BIN}" ]]; then
  echo "conda executable not found" >&2
  exit 1
fi

cd "${ROOT_DIR}"
echo "Starting Portfolio Monitor at ${URL} (binding on ${HOST}:${PORT})"

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
  # Open a local loading page (file://) instead of ${URL} directly. It loads
  # instantly, polls ${URL}, and auto-redirects the moment the dashboard is
  # listening — so we never land on the cold-start window where the port is
  # still refused and the browser shows a connection error.
  OPEN_TARGET="${URL}"
  if [[ -f "${SCRIPT_DIR}/loading.html" ]]; then
    OPEN_TARGET="file://${SCRIPT_DIR}/loading.html?target=${URL}"
  fi
  if command -v open >/dev/null 2>&1; then
    open "${OPEN_TARGET}" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "${OPEN_TARGET}" >/dev/null 2>&1 || true
  fi
fi

wait "${SERVER_PID}"
