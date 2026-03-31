"""Cache for scan history — stores file counts and ignore dirs per scanned path."""

from __future__ import annotations

import json
from pathlib import Path

from storageanalyser.platform import cache_dir

CACHE_DIR = cache_dir()
CACHE_FILE = CACHE_DIR / "scan_history.json"
IGNORE_DIRS_FILE = CACHE_DIR / "ignore_dirs.json"


class ScanCache:
    """Persists file counts from previous scans for progress estimation."""

    def __init__(self, cache_file: Path = CACHE_FILE) -> None:
        self._file = cache_file
        self._data: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        try:
            return json.loads(self._file.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._data, indent=2))
        except OSError:
            pass

    def get_expected_files(self, path: str) -> int | None:
        """Return the cached file count for a path, or None if unknown."""
        return self._data.get(path)

    def update(self, path: str, file_count: int) -> None:
        """Store the file count for a path and persist to disk."""
        self._data[path] = file_count
        self._save()


class IgnoreDirsCache:
    """Persists ignored directories per scan root across runs."""

    def __init__(self, cache_file: Path = IGNORE_DIRS_FILE) -> None:
        self._file = cache_file
        self._data: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        try:
            return json.loads(self._file.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(json.dumps(self._data, indent=2))
        except OSError:
            pass

    def get(self, path: str) -> list[str]:
        """Return the cached ignore dirs for a scan root, or empty list."""
        return self._data.get(path, [])

    def update(self, path: str, ignore_dirs: list[str]) -> None:
        """Store ignore dirs for a scan root and persist to disk."""
        if ignore_dirs:
            self._data[path] = ignore_dirs
        elif path in self._data:
            del self._data[path]
        self._save()
