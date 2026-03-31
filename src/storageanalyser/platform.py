"""Platform-specific helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"


def cache_dir() -> Path:
    """Return the platform-appropriate cache directory for storageanalyser."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA", "")
        if base:
            return Path(base) / "storageanalyser" / "cache"
        return Path.home() / "AppData" / "Local" / "storageanalyser" / "cache"
    return Path.home() / ".cache" / "storageanalyser"


def config_dir() -> Path:
    """Return the platform-appropriate config directory for storageanalyser."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA", "")
        if base:
            return Path(base) / "storageanalyser" / "config"
        return Path.home() / "AppData" / "Local" / "storageanalyser" / "config"
    return Path.home() / ".config" / "storageanalyser"
