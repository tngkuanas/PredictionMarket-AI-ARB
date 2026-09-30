"""Detached Background Daemon Launcher for Phase 10A.5e using OS session decoupling (setsid)."""

import os
import sys
import subprocess
from pathlib import Path

PROJECT_DIR = Path("/Users/tengkuanas/Projects/PredictionMarketModel")
LOG_FILE = PROJECT_DIR / "data" / "phase10a5e_daemon.log"
PID_FILE = PROJECT_DIR / "data" / "phase10a5e_daemon.pid"
PYTHON_BIN = PROJECT_DIR / ".venv" / "bin" / "python"
DAEMON_SCRIPT = PROJECT_DIR / "src" / "pipeline" / "run_phase10a5e_daemon.py"


def launch():
    PROJECT_DIR.joinpath("data").mkdir(parents=True, exist_ok=True)

    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            os.kill(old_pid, 0)
            print(f"Phase 10A.5e Daemon is ALREADY RUNNING with PID: {old_pid}")
            return
        except (ValueError, OSError):
            PID_FILE.unlink(missing_ok=True)

    log_fd = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [
            str(PYTHON_BIN),
            "-u",
            str(DAEMON_SCRIPT),
            "--target-hours", "72.0",
            "--cycle-sec", "30.0",
            "--universe-refresh-sec", "300.0",
            "--market-limit", "25"
        ],
        stdout=log_fd,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=str(PROJECT_DIR),
        env=env,
        start_new_session=True
    )

    PID_FILE.write_text(str(proc.pid))
    print(f"Phase 10A.5e Daemon started detached with PID: {proc.pid}")
    print(f"Logging to: {LOG_FILE}")


if __name__ == "__main__":
    launch()
