#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/tengkuanas/Projects/PredictionMarketModel"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

"$VENV_PYTHON" "${PROJECT_DIR}/scripts/launch_daemon.py"
