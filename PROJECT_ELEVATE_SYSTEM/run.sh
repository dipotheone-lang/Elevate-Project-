#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# United Brothers Co. — PROJECT ELEVATE — one-command launcher (Mac / Linux)
# مشغّل بنقرة واحدة
#
# Creates a virtual environment (first run only), installs dependencies, and
# runs the full A -> Z pipeline. Re-run any time; setup is cached.
#
# Usage:
#   ./run.sh              # run the full pipeline
#   ./run.sh test         # run the test suite instead
# ---------------------------------------------------------------------------
set -euo pipefail

# Always operate from this script's directory.
cd "$(dirname "$0")"

# Pick a Python 3 interpreter.
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "ERROR: Python 3 not found. Install it from https://python.org/downloads" >&2
  exit 1
fi

echo "==> Using $($PY --version)"

# Create the virtual environment on first run.
if [ ! -d ".venv" ]; then
  echo "==> Creating virtual environment (.venv) ..."
  "$PY" -m venv .venv
fi

# Activate it.
# shellcheck disable=SC1091
source .venv/bin/activate

# Install/refresh dependencies (quiet).
echo "==> Installing dependencies ..."
python -m pip install --upgrade pip >/dev/null
if [ "${1:-}" = "test" ]; then
  pip install -q -r requirements-dev.txt
  echo "==> Running test suite ..."
  python -m pytest tests/ -v
else
  pip install -q -r requirements.txt
  echo "==> Running the full PROJECT ELEVATE pipeline (A -> Z) ..."
  python run_pipeline.py
  echo ""
  echo "==> Done. Open the results in ./outputs/ :"
  echo "    - boq_audit_report.md"
  echo "    - site_daily_digest.md"
  echo "    - gainsharing_result.md"
  echo "    - UNITED_BROTHERS_ELEVATE_MASTER.xlsx  (open in Excel)"
fi
