#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/env.yml"
ENV_NAME="${ENV_NAME:-py313}"
CONDA_BIN="${CONDA_BIN:-$(command -v conda || true)}"

if [[ -z "${CONDA_BIN}" ]]; then
    echo "Conda is required. Install conda or set CONDA_BIN to your conda executable." >&2
    exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "Missing environment definition: ${ENV_FILE}" >&2
    exit 1
fi

if "${CONDA_BIN}" run -n "${ENV_NAME}" python --version >/dev/null 2>&1; then
    cat <<EOF
Conda environment '${ENV_NAME}' is already installed.

Activate it with:
conda activate "${ENV_NAME}"
EOF
    exit 0
fi

echo "Conda environment '${ENV_NAME}' was not found. Recreating it from ${ENV_FILE}."
"${CONDA_BIN}" env remove -n "${ENV_NAME}" -y >/dev/null 2>&1 || true
"${CONDA_BIN}" env create -f "${ENV_FILE}"

echo "Installing Playwright Chromium for headless dashboard snapshots..."
"${CONDA_BIN}" run -n "${ENV_NAME}" python -m playwright install chromium

cat <<EOF
Conda environment '${ENV_NAME}' is ready.

Activate it with:
conda activate "${ENV_NAME}"
EOF
