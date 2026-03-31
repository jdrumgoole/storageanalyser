"""Constants for disk analysis."""

from __future__ import annotations

import sys

_IS_WINDOWS = sys.platform == "win32"
_IS_MACOS = sys.platform == "darwin"

# Directories that are almost always safe to nuke (relative to HOME)
_JUNK_DIRS_COMMON: list[tuple[str, str]] = [
    (".cache", "XDG / CLI tool caches"),
    (".npm/_cacache", "npm cache"),
    (".yarn/cache", "Yarn cache"),
    (".gradle/caches", "Gradle build cache"),
    (".m2/repository", "Maven local repo"),
    (".cargo/registry", "Cargo crate cache"),
]

_JUNK_DIRS_MACOS: list[tuple[str, str]] = [
    ("Library/Caches", "App caches — regenerated automatically"),
    ("Library/Logs", "System & app log files"),
    (".Trash", "Finder trash"),
    (".cocoapods/repos", "CocoaPods spec repos"),
    ("Library/Developer/Xcode/DerivedData", "Xcode build artifacts"),
    ("Library/Developer/Xcode/Archives", "Xcode old archives"),
    ("Library/Developer/CoreSimulator", "iOS Simulator data"),
    ("Library/Application Support/Code/CachedExtensionVSIXs", "VS Code extension cache"),
    ("Library/Application Support/Slack/Cache", "Slack cache"),
    ("Library/Application Support/Slack/Service Worker/CacheStorage", "Slack SW cache"),
    ("Library/Application Support/discord/Cache", "Discord cache"),
    ("Library/Application Support/Google/Chrome/Default/Service Worker/CacheStorage", "Chrome SW cache"),
    ("Library/Containers/com.docker.docker/Data/vms", "Docker Desktop VM images"),
    ("Library/Group Containers/group.com.docker/cache", "Docker group cache"),
]

_JUNK_DIRS_WINDOWS: list[tuple[str, str]] = [
    ("AppData/Local/Temp", "Windows temporary files"),
    ("AppData/Local/Microsoft/Windows/Explorer", "Windows thumbnail cache"),
    ("AppData/Local/CrashDumps", "Windows crash dumps"),
    ("AppData/Local/Programs/Python/Launcher", "Python launcher cache"),
    ("AppData/Local/pip/cache", "pip download cache"),
    ("AppData/Roaming/Code/CachedExtensionVSIXs", "VS Code extension cache"),
    ("AppData/Roaming/Slack/Cache", "Slack cache"),
    ("AppData/Roaming/Slack/Service Worker/CacheStorage", "Slack SW cache"),
    ("AppData/Roaming/discord/Cache", "Discord cache"),
    ("AppData/Local/Google/Chrome/User Data/Default/Service Worker/CacheStorage", "Chrome SW cache"),
    ("AppData/Local/Docker/wsl", "Docker Desktop WSL data"),
]

if _IS_MACOS:
    JUNK_DIRS: list[tuple[str, str]] = _JUNK_DIRS_COMMON + _JUNK_DIRS_MACOS
elif _IS_WINDOWS:
    JUNK_DIRS: list[tuple[str, str]] = _JUNK_DIRS_COMMON + _JUNK_DIRS_WINDOWS
else:
    JUNK_DIRS: list[tuple[str, str]] = _JUNK_DIRS_COMMON

# Patterns that indicate disposable project artifacts (searched recursively)
ARTIFACT_DIR_NAMES: set[str] = {
    "node_modules",
    "__pycache__",
    ".tox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".eggs",
    "*.egg-info",
    "target",        # Rust / Java
    ".next",         # Next.js
    ".nuxt",         # Nuxt
    ".parcel-cache", # Parcel
    ".turbo",        # Turborepo
    "venv",
    ".venv",
    "env",
}

# File extensions for common large/disposable files
LARGE_FILE_EXTENSIONS: set[str] = {
    ".iso", ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    ".vmdk", ".vdi", ".qcow2",          # VM images
    ".avi", ".mov", ".mp4", ".mkv",      # Video
    ".wav", ".flac",                     # Lossless audio
    ".psd", ".sketch",                   # Design files
    ".core",                             # Core dumps
}

if _IS_MACOS:
    LARGE_FILE_EXTENSIONS |= {".dmg", ".pkg", ".app", ".ipa"}
elif _IS_WINDOWS:
    LARGE_FILE_EXTENSIONS |= {".msi", ".exe", ".cab", ".wim"}

# Directories skipped by default during the walk.
# Hidden dirs (starting with ".") are skipped unless they appear in
# SCANNABLE_HIDDEN_DIRS below.  The names here are matched against the
# final path component regardless of depth.
_SKIP_DIRS_COMMON: dict[str, str] = {
    "CloudStorage": "Cloud-synced storage (Google Drive, iCloud, OneDrive, Dropbox)",
}

_SKIP_DIRS_MACOS: dict[str, str] = {
    "Photos Library.photoslibrary": "macOS Photos library (managed by Photos.app)",
    "Music": "macOS Music library",
    "Movies": "macOS Movies folder",
    ".Spotlight-V100": "Spotlight index data",
    ".fseventsd": "macOS filesystem event logs",
    ".DocumentRevisions-V100": "macOS document versioning data",
}

_SKIP_DIRS_WINDOWS: dict[str, str] = {
    "AppData": "Windows application data (contains caches scanned separately)",
    "$Recycle.Bin": "Windows Recycle Bin",
    "System Volume Information": "Windows system restore data",
    "NTUSER.DAT": "Windows registry hive (file, not dir — skipped for safety)",
}

if _IS_MACOS:
    DEFAULT_SKIP_DIRS: dict[str, str] = {**_SKIP_DIRS_COMMON, **_SKIP_DIRS_MACOS}
elif _IS_WINDOWS:
    DEFAULT_SKIP_DIRS: dict[str, str] = {**_SKIP_DIRS_COMMON, **_SKIP_DIRS_WINDOWS}
else:
    DEFAULT_SKIP_DIRS: dict[str, str] = {**_SKIP_DIRS_COMMON}

# Hidden directories that ARE scanned (they contain caches/junk worth flagging).
# All other dot-directories are skipped.
SCANNABLE_HIDDEN_DIRS: set[str] = {
    ".cache", ".npm", ".yarn", ".gradle", ".m2",
    ".cargo", ".tox",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".next", ".nuxt", ".parcel-cache", ".turbo",
    ".venv", ".eggs",
}

if _IS_MACOS:
    SCANNABLE_HIDDEN_DIRS |= {".cocoapods", ".Trash"}

STALE_THRESHOLD_DAYS = 365  # Files not accessed in this long are "stale"

ONE_KB = 1024
ONE_MB = ONE_KB * 1024
ONE_GB = ONE_MB * 1024
