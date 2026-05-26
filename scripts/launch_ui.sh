#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${ENV_NAME:-py313}"
CONDA_BIN="${CONDA_BIN:-$(command -v conda || true)}"

# HOST is the *bind* address the dashboard listens on. Default 0.0.0.0 so
# the server is reachable from other devices on the LAN / Tailnet (the
# iframe report URL works cross-device). Override with `HOST=127.0.0.1
# ./scripts/launch_ui.sh` to scope back to localhost-only. Dashboard has
# no auth of its own — Tailscale ACLs / host firewall are the security
# boundary; don't open the port to the public internet.
HOST="${HOST:-0.0.0.0}"
# 18080 instead of the more common 8080 to dodge collisions with Tomcat /
# Jenkins / Spring Boot / Docker port mappings on developer machines.
PORT="${PORT:-18080}"

# Browser navigates to a concrete address; 0.0.0.0 is a listen-only
# sentinel. The readiness probe also targets the concrete address since
# /dev/tcp/0.0.0.0 doesn't make sense for an outgoing connect.
if [[ "${HOST}" == "0.0.0.0" || "${HOST}" == "::" ]]; then
  OPEN_HOST="127.0.0.1"
else
  OPEN_HOST="${HOST}"
fi
URL="http://${OPEN_HOST}:${PORT}/portfolio"

AUTO_OPEN="${AUTO_OPEN:-1}"
FALLBACK_OPEN="${FALLBACK_OPEN:-1}"
OPEN_WAIT_SECONDS="${OPEN_WAIT_SECONDS:-60}"
CACHE_ROOT="${CACHE_ROOT:-${ROOT_DIR}/.cache}"
MPLCONFIGDIR="${MPLCONFIGDIR:-${CACHE_ROOT}/matplotlib}"
XDG_CACHE_HOME="${XDG_CACHE_HOME:-${CACHE_ROOT}/xdg}"

if [[ -z "${CONDA_BIN}" ]]; then
  echo "conda executable not found" >&2
  exit 1
fi

cd "${ROOT_DIR}"
echo "Starting Portfolio Monitor at ${URL} (bound on ${HOST}:${PORT})"

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
  TCP_READY=0
  HTTP_READY=0
  SERVER_DIED=0
  for ((i=0; i<ATTEMPTS; i++)); do
    if ! kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
      SERVER_DIED=1
      break
    fi
    if [[ "${TCP_READY}" == "0" ]]; then
      if (exec 3<>"/dev/tcp/${OPEN_HOST}/${PORT}") >/dev/null 2>&1; then
        TCP_READY=1
      fi
    fi
    if [[ "${TCP_READY}" == "1" ]]; then
      if curl -fsS "${URL}" >/dev/null 2>&1; then
        HTTP_READY=1
        break
      fi
    fi
    sleep 0.5
  done

  if [[ "${SERVER_DIED}" == "1" ]]; then
    echo "Error: dashboard server exited before becoming ready (pid ${SERVER_PID})" >&2
  elif [[ "${TCP_READY}" == "1" ]]; then
    if [[ "${HTTP_READY}" != "1" ]]; then
      echo "Note: ${URL} not yet serving after ${OPEN_WAIT_SECONDS}s; opening anyway, browser will retry" >&2
    fi
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
