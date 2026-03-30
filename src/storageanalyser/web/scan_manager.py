"""Manages scan lifecycle — one scan at a time, with SSE progress."""

from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

from storageanalyser.analyzer import DiskAnalyzer
from storageanalyser.cache import IgnoreDirsCache, ScanCache
from storageanalyser.constants import ONE_MB
from storageanalyser.database import ScanDatabase
from storageanalyser.helpers import human_size
from storageanalyser.models import Category, ScanResult
from storageanalyser.report import CATEGORY_COMMANDS


@dataclass
class ScanConfig:
    path: str
    top_n: int = 20
    find_duplicates: bool = False
    threshold_mb: int = 100
    workers: int = 8
    ignore_dirs: list[str] = field(default_factory=list)
    include_dirs: list[str] = field(default_factory=list)


class ScanManager:
    """Coordinates background scans and exposes progress via async queue."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active = False
        self._scan_id: str | None = None
        self._queue: asyncio.Queue[str | None] | None = None
        self._result: ScanResult | None = None
        self._error: str | None = None
        self._analyzer: DiskAnalyzer | None = None
        self._cache = ScanCache()
        self._ignore_cache = IgnoreDirsCache()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def scan_id(self) -> str | None:
        return self._scan_id

    @property
    def result(self) -> ScanResult | None:
        return self._result

    @property
    def error(self) -> str | None:
        return self._error

    def get_ignore_dirs(self, path: str) -> list[str]:
        """Return cached ignore dirs for a scan root."""
        return self._ignore_cache.get(path)

    async def start_scan(self, config: ScanConfig) -> str:
        """Start a background scan. Returns the scan_id. Raises if already running."""
        async with self._lock:
            if self._active:
                raise RuntimeError("A scan is already running")

            root = Path(config.path).expanduser().resolve()
            if not root.exists() or not root.is_dir():
                raise ValueError(f"Path does not exist or is not a directory: {root}")

            self._active = True
            self._scan_id = uuid.uuid4().hex[:12]
            self._queue = asyncio.Queue()
            self._result = None
            self._error = None

        loop = asyncio.get_event_loop()
        scan_id = self._scan_id
        root_str = str(root)
        expected_files = self._cache.get_expected_files(root_str)

        def _run() -> None:
            def callback(phase: str, message: str, files: int, size: int) -> None:
                event = json.dumps({
                    "type": "progress",
                    "phase": phase,
                    "message": message,
                    "files_scanned": files,
                    "bytes_scanned": size,
                    "expected_files": expected_files,
                })
                loop.call_soon_threadsafe(self._queue.put_nowait, event)

            try:
                analyzer = DiskAnalyzer(
                    root,
                    top_n=config.top_n,
                    find_duplicates=config.find_duplicates,
                    large_threshold=config.threshold_mb * ONE_MB,
                    progress=False,
                    workers=config.workers,
                    ignore_dirs=config.ignore_dirs or None,
                    include_dirs=config.include_dirs or None,
                    progress_callback=callback,
                )
                self._analyzer = analyzer
                result = analyzer.scan()
                self._result = result
                self._cache.update(root_str, result.total_scanned)
                self._ignore_cache.update(root_str, config.ignore_dirs)

                # Save to database for dedup — carry forward checksums
                # for unchanged files (same path, size, mtime).
                # Create a thread-local connection to avoid locking issues.
                from datetime import datetime
                db = ScanDatabase()
                try:
                    md5_cache = db.get_checksum_cache("local", root_str)
                    db.delete_scans_for_source("local", root_str)
                    db_scan_id = db.create_scan("local", root_str)
                    db_files = []
                    for path, name, size, mtime in analyzer.scanned_files:
                        if size <= 0:
                            continue
                        mtime_iso = datetime.fromtimestamp(mtime).isoformat()
                        cached_md5 = md5_cache.get((path, size, mtime_iso))
                        db_files.append({
                            "source": "local",
                            "path": path,
                            "name": name,
                            "size": size,
                            "md5": cached_md5,
                            "modified_time": mtime_iso,
                            "mime_type": None,
                            "web_link": None,
                        })
                    # Batch insert in chunks of 5000
                    for i in range(0, len(db_files), 5000):
                        db.add_files(db_scan_id, db_files[i:i + 5000])
                    db.finish_scan(db_scan_id, len(db_files), result.total_size)
                finally:
                    db.close()

                done_event = json.dumps({"type": "done", "scan_id": scan_id})
                loop.call_soon_threadsafe(self._queue.put_nowait, done_event)
            except Exception as exc:
                self._error = str(exc)
                err_event = json.dumps({"type": "error", "message": str(exc)})
                loop.call_soon_threadsafe(self._queue.put_nowait, err_event)
            finally:
                self._analyzer = None
                loop.call_soon_threadsafe(self._queue.put_nowait, None)
                loop.call_soon_threadsafe(self._set_inactive)

        loop.run_in_executor(None, _run)
        return self._scan_id

    def _set_inactive(self) -> None:
        """Called on the event loop thread after the sentinel is enqueued."""
        self._active = False

    async def subscribe(self) -> AsyncGenerator[str, None]:
        """Yield SSE event strings from the scan queue until done."""
        if self._queue is None:
            return
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    def cancel(self) -> bool:
        """Cancel the running scan. Returns True if a scan was cancelled."""
        if self._analyzer is not None and not self._analyzer.cancelled:
            self._analyzer.cancelled = True
            return True
        return False

    def reset(self) -> None:
        """Clear stored result so a new scan can begin."""
        self._result = None
        self._error = None
        self._scan_id = None

    def result_to_dict(self) -> dict | None:
        """Serialize the current result to a JSON-compatible dict."""
        if self._result is None:
            return None
        r = self._result
        by_cat: dict[str, int] = {}
        for rec in r.recommendations:
            by_cat[rec.category.value] = by_cat.get(rec.category.value, 0) + rec.size

        try:
            du = shutil.disk_usage(r.root)
            disk_info = {
                "disk_total": du.total,
                "disk_total_human": human_size(du.total),
                "disk_used": du.used,
                "disk_used_human": human_size(du.used),
                "disk_free": du.free,
                "disk_free_human": human_size(du.free),
            }
        except OSError:
            disk_info = {
                "disk_total": 0, "disk_total_human": "Unknown",
                "disk_used": 0, "disk_used_human": "Unknown",
                "disk_free": 0, "disk_free_human": "Unknown",
            }

        return {
            "scan_id": self._scan_id,
            "root": r.root,
            "total_scanned": r.total_scanned,
            "total_size": r.total_size,
            "total_size_human": human_size(r.total_size),
            "reclaimable": r.reclaimable,
            "reclaimable_human": human_size(r.reclaimable),
            "scan_seconds": round(r.scan_seconds, 2),
            "errors": r.errors,
            **disk_info,
            "category_breakdown": by_cat,
            "recommendations": [
                {
                    "path": rec.path,
                    "size": rec.size,
                    "size_human": human_size(rec.size),
                    "category": rec.category.value,
                    "reason": rec.reason,
                    "age_days": rec.age_days,
                    "priority_score": rec.priority_score,
                    "cleanup_command": CATEGORY_COMMANDS[rec.category].format(path=shlex.quote(rec.path)),
                }
                for rec in r.recommendations
            ],
            "duplicate_groups": r.duplicates[:20],
        }

    def generate_script(self, paths: list[str]) -> str:
        """Generate a bash cleanup script for the given paths."""
        if self._result is None:
            return ""
        rec_by_path = {rec.path: rec for rec in self._result.recommendations}
        lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "# StorageAnalyser cleanup script",
            "# Review each line before running!",
            "",
        ]
        for p in paths:
            rec = rec_by_path.get(p)
            if rec:
                cmd = CATEGORY_COMMANDS[rec.category].format(path=shlex.quote(rec.path))
                lines.append(f"{cmd}  # {human_size(rec.size)} — {rec.reason}")
        lines.append("")
        return "\n".join(lines)
