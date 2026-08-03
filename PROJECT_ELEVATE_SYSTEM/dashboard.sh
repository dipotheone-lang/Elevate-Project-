#!/usr/bin/env bash
# United Brothers Co. — launch the PROJECT ELEVATE dashboard locally (Mac/Linux).
set -euo pipefail
cd "$(dirname "$0")"
PY="$(command -v python3 || command -v python)"
[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
pip install -q -r requirements-dashboard.txt
echo "==> Opening the dashboard in your browser..."
streamlit run dashboard.py
