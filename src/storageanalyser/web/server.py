"""FastAPI web server for storageanalyser."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Query, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from storageanalyser.web.scan_manager import ScanConfig, ScanManager

WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="StorageAnalyser")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    """Prevent browser caching of static assets during development."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


app.add_middleware(NoCacheStaticMiddleware)

scan_manager = ScanManager()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the main page."""
    from storageanalyser import __version__
    response = templates.TemplateResponse(request, "index.html", {
        "default_path": str(Path.home()),
        "version": __version__,
    })
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/api/scan/skipped-dirs")
async def skipped_dirs() -> JSONResponse:
    """Return the list of directories skipped by default."""
    from storageanalyser.constants import DEFAULT_SKIP_DIRS
    return JSONResponse({
        "dirs": [{"name": name, "reason": reason}
                 for name, reason in sorted(DEFAULT_SKIP_DIRS.items())]
    })


@app.post("/api/scan")
async def start_scan(
    path: str = Query(default=str(Path.home())),
    top_n: int = Query(default=20, ge=1, le=200),
    find_duplicates: bool = Query(default=False),
    threshold_mb: int = Query(default=100, ge=1),
    workers: int = Query(default=8, ge=1, le=32),
    ignore_dirs: list[str] = Query(default=[]),
    include_dirs: list[str] = Query(default=[]),
) -> JSONResponse:
    """Start a new scan."""
    config = ScanConfig(
        path=path,
        top_n=top_n,
        find_duplicates=find_duplicates,
        threshold_mb=threshold_mb,
        workers=workers,
        ignore_dirs=ignore_dirs,
        include_dirs=include_dirs,
    )
    try:
        scan_id = await scan_manager.start_scan(config)
    except RuntimeError:
        return JSONResponse(
            {"error": "A scan is already running"},
            status_code=409,
        )
    except ValueError as exc:
        return JSONResponse(
            {"error": str(exc)},
            status_code=422,
        )
    return JSONResponse({"scan_id": scan_id, "status": "started"})


@app.get("/api/scan/events", response_model=None)
async def scan_events() -> StreamingResponse | JSONResponse:
    """SSE endpoint for scan progress."""
    if not scan_manager.is_active and scan_manager._queue is None:
        return JSONResponse({"error": "No scan in progress"}, status_code=409)

    async def event_stream() -> None:
        async for event in scan_manager.subscribe():
            yield f"data: {event}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/scan/status")
async def scan_status() -> JSONResponse:
    """Check current scan status."""
    return JSONResponse({
        "active": scan_manager.is_active,
        "scan_id": scan_manager.scan_id,
        "has_result": scan_manager.result is not None,
        "error": scan_manager.error,
    })


@app.get("/api/scan/ignore-dirs")
async def get_ignore_dirs(path: str = Query(default="")) -> JSONResponse:
    """Return cached ignore dirs for a scan root."""
    resolved = str(Path(path).expanduser().resolve()) if path else ""
    dirs = scan_manager.get_ignore_dirs(resolved)
    return JSONResponse({"ignore_dirs": dirs})


@app.get("/api/scan/result")
async def scan_result() -> JSONResponse:
    """Get the scan result."""
    data = scan_manager.result_to_dict()
    if data is None:
        return JSONResponse({"error": "No scan result available"}, status_code=404)
    return JSONResponse(data)


@app.get("/api/scan/script")
async def download_script(paths: list[str] = Query(default=[])) -> PlainTextResponse:
    """Generate a cleanup script for selected paths."""
    if scan_manager.result is None:
        return PlainTextResponse("No scan result available", status_code=404)
    if not paths:
        return PlainTextResponse("No paths selected", status_code=400)
    script = scan_manager.generate_script(paths)
    return PlainTextResponse(
        script,
        media_type="text/plain",
        headers={"Content-Disposition": "attachment; filename=cleanup.sh"},
    )


@app.post("/api/scan/cancel")
async def cancel_scan() -> JSONResponse:
    """Cancel the running scan."""
    if not scan_manager.is_active:
        return JSONResponse({"error": "No scan in progress"}, status_code=409)
    cancelled = scan_manager.cancel()
    return JSONResponse({"status": "cancelled" if cancelled else "not_running"})


@app.post("/api/scan/reset")
async def reset_scan() -> JSONResponse:
    """Reset scan state to allow a new scan."""
    if scan_manager.is_active:
        return JSONResponse({"error": "Cannot reset while scan is running"}, status_code=409)
    scan_manager.reset()
    return JSONResponse({"status": "reset"})


# ── Google Drive endpoints ────────────────────────────────────

_gdrive_result: dict | None = None
_gdrive_scanning = False


@app.get("/api/gdrive/status")
async def gdrive_status() -> JSONResponse:
    """Check Google Drive configuration and auth status."""
    from storageanalyser import gdrive
    return JSONResponse({
        "configured": gdrive.is_configured(),
        "authenticated": gdrive.has_token(),
        "scanning": _gdrive_scanning,
        "has_result": _gdrive_result is not None,
    })


@app.post("/api/gdrive/credentials")
async def upload_gdrive_credentials(file: UploadFile = File(...)) -> JSONResponse:
    """Upload Google OAuth2 credentials JSON."""
    import json as _json
    from storageanalyser import gdrive
    try:
        content = await file.read()
        creds = _json.loads(content)
        gdrive.save_credentials(creds)
        return JSONResponse({"status": "saved"})
    except (ValueError, _json.JSONDecodeError) as exc:
        return JSONResponse({"error": f"Invalid JSON: {exc}"}, status_code=422)


@app.post("/api/gdrive/auth")
async def gdrive_auth() -> JSONResponse:
    """Start Google Drive OAuth2 flow (opens browser for consent)."""
    import asyncio
    from storageanalyser import gdrive
    if not gdrive.is_configured():
        return JSONResponse(
            {"error": "Upload credentials JSON first"}, status_code=400
        )
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: gdrive.authenticate(port=0))
        return JSONResponse({"status": "authenticated"})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/gdrive/scan")
async def gdrive_scan(
    find_duplicates: bool = Query(default=False),
) -> JSONResponse:
    """Start a Google Drive scan."""
    import asyncio
    from storageanalyser import gdrive

    global _gdrive_result, _gdrive_scanning

    if _gdrive_scanning:
        return JSONResponse({"error": "Scan already running"}, status_code=409)
    if not gdrive.has_token():
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    _gdrive_scanning = True
    _gdrive_result = None

    loop = asyncio.get_event_loop()

    def _run() -> None:
        global _gdrive_result, _gdrive_scanning
        try:
            service = gdrive.authenticate()
            result = gdrive.scan_drive(service, find_duplicates=find_duplicates)
            _gdrive_result = result

            # Save to database for dedup
            from storageanalyser.database import ScanDatabase
            db = ScanDatabase()
            db.delete_scans_for_source("gdrive", "Google Drive")
            db_scan_id = db.create_scan("gdrive", "Google Drive")
            db_files = [
                {
                    "source": "gdrive",
                    "path": f"gdrive://{f['id']}",
                    "name": f["name"],
                    "size": f["size"],
                    "md5": f.get("md5"),
                    "modified_time": f.get("modified_time"),
                    "mime_type": f.get("mime_type"),
                    "web_link": f.get("web_view_link"),
                }
                for f in result["files"]
                if f["size"] > 0
            ]
            for i in range(0, len(db_files), 5000):
                db.add_files(db_scan_id, db_files[i:i + 5000])
            db.finish_scan(db_scan_id, len(db_files), result["total_size"])
            db.close()
        except Exception as exc:
            _gdrive_result = {"error": str(exc)}
        finally:
            _gdrive_scanning = False

    loop.run_in_executor(None, _run)
    return JSONResponse({"status": "started"})


@app.get("/api/gdrive/result")
async def gdrive_result() -> JSONResponse:
    """Get the Google Drive scan result."""
    if _gdrive_scanning:
        return JSONResponse({"status": "scanning"}, status_code=202)
    if _gdrive_result is None:
        return JSONResponse({"error": "No scan result"}, status_code=404)
    if "error" in _gdrive_result:
        return JSONResponse({"error": _gdrive_result["error"]}, status_code=500)

    # Limit files to top 200 for the response
    result = dict(_gdrive_result)
    result["files"] = result["files"][:200]
    return JSONResponse(result)


@app.post("/api/gdrive/disconnect")
async def gdrive_disconnect() -> JSONResponse:
    """Remove Google Drive auth token."""
    global _gdrive_result
    from storageanalyser import gdrive
    gdrive.disconnect()
    _gdrive_result = None
    return JSONResponse({"status": "disconnected"})


# ── Dedup endpoints ───────────────────────────────────────────

_dedup_computing = False


@app.get("/api/dedup/stats")
async def dedup_stats() -> JSONResponse:
    """Get stats about cached scan data."""
    from storageanalyser.database import ScanDatabase
    db = ScanDatabase()
    stats = db.get_stats()
    stats["computing_checksums"] = _dedup_computing
    db.close()
    return JSONResponse(stats)


@app.post("/api/dedup/checksum")
async def dedup_compute_checksums() -> JSONResponse:
    """Compute MD5 checksums for local dedup candidates."""
    import asyncio
    from storageanalyser.database import ScanDatabase

    global _dedup_computing
    if _dedup_computing:
        return JSONResponse({"error": "Already computing"}, status_code=409)

    _dedup_computing = True
    loop = asyncio.get_event_loop()

    def _run() -> None:
        global _dedup_computing
        try:
            db = ScanDatabase()
            db.compute_missing_checksums(workers=8)
            db.close()
        finally:
            _dedup_computing = False

    loop.run_in_executor(None, _run)
    return JSONResponse({"status": "started"})


@app.get("/api/dedup/results")
async def dedup_results(min_size: int = Query(default=1024)) -> JSONResponse:
    """Find duplicates across all cached scans."""
    from storageanalyser.database import ScanDatabase
    db = ScanDatabase()
    results = db.find_duplicates(min_size)
    db.close()
    return JSONResponse(results)


# Module-level reference so the shutdown endpoint can signal it
_shutdown_event: "asyncio.Event | None" = None


@app.post("/api/shutdown")
async def shutdown() -> JSONResponse:
    """Shut down the server."""
    import os
    # Return the response first, then trigger shutdown after a short delay
    # so the client receives the response before the process exits.
    if _shutdown_event is not None:
        _shutdown_event.set()
    else:
        import threading
        threading.Timer(0.2, lambda: os._exit(0)).start()
    return JSONResponse({"status": "shutting_down"})


def _check_port_available(host: str, port: int) -> bool:
    """Return True if the port is available for binding.

    Uses SO_REUSEADDR to match uvicorn's behaviour — lingering TIME_WAIT
    or CLOSE_WAIT connections from a previous run won't block a restart.
    """
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def run(*, open_browser: bool = False, port: int = 8888) -> None:
    """Entry point for storageanalyser-web command."""
    import asyncio
    import threading
    import webbrowser
    import uvicorn

    global _shutdown_event

    host = "127.0.0.1"
    url = f"http://{host}:{port}/"

    if not _check_port_available(host, port):
        print(
            f"Error: port {port} is already in use.\n"
            f"Either stop the other process or use a different port:\n"
            f"  storageanalyser --web --port {port + 1}",
            file=sys.stderr,
        )
        sys.exit(1)

    config = uvicorn.Config(
        "storageanalyser.web.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="warning" if open_browser else "info",
    )
    uvi_server = uvicorn.Server(config)

    _shutdown_event = asyncio.Event()

    def _sigint_handler(signum: int, frame: object) -> None:
        """Handle Ctrl-C by signalling the shutdown event."""
        print("\nShutting down…", file=sys.stderr)
        _shutdown_event.set()

    signal.signal(signal.SIGINT, _sigint_handler)

    if open_browser:
        def _open_browser() -> None:
            """Wait for the server to start, then open the browser."""
            import time
            import urllib.request
            import urllib.error
            for _ in range(40):
                time.sleep(0.25)
                try:
                    urllib.request.urlopen(url, timeout=1)
                    break
                except (urllib.error.URLError, ConnectionError, OSError):
                    continue
            print(f"StorageAnalyser web UI: {url}")
            webbrowser.open(url)

        threading.Thread(target=_open_browser, daemon=True).start()

    async def _serve_until_shutdown() -> None:
        """Run the server until the shutdown event is set."""
        serve_task = asyncio.create_task(uvi_server.serve())
        shutdown_task = asyncio.create_task(_shutdown_event.wait())
        await asyncio.wait(
            [serve_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if not serve_task.done():
            uvi_server.should_exit = True
            await serve_task

    asyncio.run(_serve_until_shutdown())
    print("Server stopped.")


if __name__ == "__main__":
    import argparse as _ap
    _p = _ap.ArgumentParser(description="StorageAnalyser web server")
    _p.add_argument("--port", type=int, default=8888, help="Port to listen on (default: 8888)")
    _args = _p.parse_args()
    run(port=_args.port)
