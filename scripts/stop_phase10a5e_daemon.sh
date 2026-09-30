#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/tengkuanas/Projects/PredictionMarketModel"
PID_FILE="${PROJECT_DIR}/data/phase10a5e_daemon.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "Stopping Phase 10A.5e Daemon (PID ${PID})..."
        kill -15 "$PID"
        sleep 2
        if ps -p "$PID" > /dev/null 2>&1; then
            echo "Process still running, sending SIGKILL..."
            kill -9 "$PID"
        fi
        echo "Phase 10A.5e Daemon stopped."
    else
        echo "Process with PID ${PID} is not running."
    fi
    rm -f "$PID_FILE"
else
    echo "No PID file found. Phase 10A.5e Daemon is not running."
fi
