"""Helper utilities for disk analysis."""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path

from storageanalyser.constants import ONE_GB, ONE_KB, ONE_MB


def human_size(nbytes: int | float) -> str:
    """Return a concise human-readable size string."""
    if nbytes >= ONE_GB:
        return f"{nbytes / ONE_GB:.1f} GB"
    if nbytes >= ONE_MB:
        return f"{nbytes / ONE_MB:.1f} MB"
    if nbytes >= ONE_KB:
        return f"{nbytes / ONE_KB:.1f} KB"
    return f"{nbytes} B"


def sha256_head(path: Path, chunk: int = 65536) -> str | None:
    """Hash the first 64 KB of a file — fast enough for duplicate detection."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            h.update(f.read(chunk))
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def file_age_days(st: os.stat_result) -> int:
    """Days since last access (atime) or modification (mtime), whichever is newer."""
    newest = max(st.st_atime, st.st_mtime)
    return int((time.time() - newest) / 86400)


class Colour:
    """ANSI helpers — degrades gracefully if piped."""
    enabled = sys.stdout.isatty()

    @staticmethod
    def _wrap(code: str, text: str) -> str:
        if Colour.enabled:
            return f"\033[{code}m{text}\033[0m"
        return text

    @classmethod
    def bold(cls, t: str) -> str:
        return cls._wrap("1", t)

    @classmethod
    def red(cls, t: str) -> str:
        return cls._wrap("91", t)

    @classmethod
    def yellow(cls, t: str) -> str:
        return cls._wrap("93", t)

    @classmethod
    def green(cls, t: str) -> str:
        return cls._wrap("92", t)

    @classmethod
    def cyan(cls, t: str) -> str:
        return cls._wrap("96", t)

    @classmethod
    def dim(cls, t: str) -> str:
        return cls._wrap("2", t)
