#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/tengkuanas/Projects/PredictionMarketModel"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
LOG_FILE="${PROJECT_DIR}/data/phase10a5e_daemon.log"
PID_FILE="${PROJECT_DIR}/data/phase10a5e_daemon.pid"

mkdir -p "${PROJECT_DIR}/data"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Phase 10A.5e daemon is ALREADY RUNNING with PID ${PID}."
        exit 0
    else
        echo "Removing stale PID file: ${PID_FILE}"
        rm -f "$PID_FILE"
    fi
fi

echo "Starting Phase 10A.5e Unattended Multi-Day Daemon in background..."
export PYTHONUNBUFFERED=1
nohup "$VENV_PYTHON" -u "${PROJECT_DIR}/src/pipeline/run_phase10a5e_daemon.py" \
    --target-hours 72.0 \
    --cycle-sec 30.0 \
    --universe-refresh-sec 300.0 \
    --market-limit 25 \
    >> "$LOG_FILE" 2>&1 &
DAEMON_PID=$!
disown "$DAEMON_PID"

echo "$DAEMON_PID" > "$PID_FILE"
echo "Phase 10A.5e Daemon started successfully with PID: ${DAEMON_PID}"
echo "Log file: ${LOG_FILE}"
