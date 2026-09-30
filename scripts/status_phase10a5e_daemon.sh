#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/tengkuanas/Projects/PredictionMarketModel"
PID_FILE="${PROJECT_DIR}/data/phase10a5e_daemon.pid"
LOG_FILE="${PROJECT_DIR}/data/phase10a5e_daemon.log"
HEALTH_FILE="${PROJECT_DIR}/data/phase10a5c_health_monitor.json"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "=== Phase 10A.5e Daemon Status: RUNNING (PID ${PID}) ==="
    else
        echo "=== Phase 10A.5e Daemon Status: NOT RUNNING (Stale PID ${PID}) ==="
    fi
else
    echo "=== Phase 10A.5e Daemon Status: STOPPED (No PID file) ==="
fi

if [ -f "$HEALTH_FILE" ]; then
    echo "--- Latest Health Telemetry ---"
    cat "$HEALTH_FILE"
    echo ""
fi

if [ -f "$LOG_FILE" ]; then
    echo "--- Recent Log Output (Last 15 lines) ---"
    tail -n 15 "$LOG_FILE"
fi
