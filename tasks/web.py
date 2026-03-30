"""Web server invoke tasks."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from invoke import task, Context

PID_FILE = Path("/tmp/storageanalyser-web.pid")
HOST = "127.0.0.1"
PORT = 8888


def _is_running() -> int | None:
    """Return the PID if the server is running, else None."""
    if not PID_FILE.exists():
        return None
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, 0)
        return pid
    except (ProcessLookupError, PermissionError):
        PID_FILE.unlink(missing_ok=True)
        return None


@task
def start(ctx: Context) -> None:
    """Start the StorageAnalyser web server on 127.0.0.1:8888."""
    if _is_running():
        print(f"Server already running (PID {PID_FILE.read_text().strip()})")
        return

    proc = subprocess.Popen(
        ["uv", "run", "storageanalyser-web"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    PID_FILE.write_text(str(proc.pid))

    # Wait for server to be reachable
    import urllib.request
    import urllib.error

    url = f"http://{HOST}:{PORT}/"
    for _ in range(20):
        time.sleep(0.25)
        try:
            urllib.request.urlopen(url, timeout=1)
            print(f"Server started on http://{HOST}:{PORT}/ (PID {proc.pid})")
            return
        except (urllib.error.URLError, ConnectionError, OSError):
            continue

    print(f"Server process started (PID {proc.pid}) but not yet reachable at {url}")


@task
def stop(ctx: Context) -> None:
    """Stop the StorageAnalyser web server."""
    pid = _is_running()
    if pid is None:
        print("Server is not running")
        return
    os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    print(f"Server stopped (PID {pid})")


@task
def restart(ctx: Context) -> None:
    """Restart the web server."""
    stop(ctx)
    time.sleep(0.5)
    start(ctx)


@task
def status(ctx: Context) -> None:
    """Check if the web server is running."""
    pid = _is_running()
    if pid:
        print(f"Server is running on http://{HOST}:{PORT}/ (PID {pid})")
    else:
        print("Server is not running")
