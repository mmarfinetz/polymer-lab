#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${RADONPY_SOURCE_DIR:-}" ]]; then
  echo "RADONPY_SOURCE_DIR must point to a reviewed RadonPy checkout" >&2
  exit 2
fi

if [[ ! -d "${RADONPY_SOURCE_DIR}/dist" ]]; then
  echo "RadonPy dist directory not found: ${RADONPY_SOURCE_DIR}/dist" >&2
  exit 2
fi

python -m pip install --no-index --find-links="${RADONPY_SOURCE_DIR}/dist" radonpy-pypi
python -m pip install -e .

echo "Set RADONPY_AUTOMD_DIR=${RADONPY_SOURCE_DIR}/AutoMD_scripts in the worker environment."

