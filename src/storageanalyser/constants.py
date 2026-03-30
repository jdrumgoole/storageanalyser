"""Constants for disk analysis."""

from __future__ import annotations

# Directories that are almost always safe to nuke (relative to HOME)
JUNK_DIRS: list[tuple[str, str]] = [
    ("Library/Caches", "App caches — regenerated automatically"),
    ("Library/Logs", "System & app log files"),
    (".Trash", "Finder trash"),
    (".cache", "XDG / CLI tool caches"),
    (".npm/_cacache", "npm cache"),
    (".yarn/cache", "Yarn cache"),
    (".gradle/caches", "Gradle build cache"),
    (".m2/repository", "Maven local repo"),
    (".cocoapods/repos", "CocoaPods spec repos"),
    (".cargo/registry", "Cargo crate cache"),
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
    ".dmg", ".iso", ".pkg", ".app", ".ipa",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".rar", ".7z",
    ".vmdk", ".vdi", ".qcow2",          # VM images
    ".avi", ".mov", ".mp4", ".mkv",      # Video
    ".wav", ".flac",                     # Lossless audio
    ".psd", ".sketch",                   # Design files
    ".core",                             # Core dumps
}

# Directories skipped by default during the walk.
# Hidden dirs (starting with ".") are skipped unless they appear in
# SCANNABLE_HIDDEN_DIRS below.  The names here are matched against the
# final path component regardless of depth.
DEFAULT_SKIP_DIRS: dict[str, str] = {
    "Photos Library.photoslibrary": "macOS Photos library (managed by Photos.app)",
    "Music": "macOS Music library",
    "Movies": "macOS Movies folder",
    ".Spotlight-V100": "Spotlight index data",
    ".fseventsd": "macOS filesystem event logs",
    ".DocumentRevisions-V100": "macOS document versioning data",
    "CloudStorage": "Cloud-synced storage (Google Drive, iCloud, OneDrive, Dropbox)",
}

# Hidden directories that ARE scanned (they contain caches/junk worth flagging).
# All other dot-directories are skipped.
SCANNABLE_HIDDEN_DIRS: set[str] = {
    ".cache", ".npm", ".yarn", ".gradle", ".m2",
    ".cocoapods", ".cargo", ".Trash", ".tox",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".next", ".nuxt", ".parcel-cache", ".turbo",
    ".venv", ".eggs",
}

STALE_THRESHOLD_DAYS = 365  # Files not accessed in this long are "stale"

ONE_KB = 1024
ONE_MB = ONE_KB * 1024
ONE_GB = ONE_MB * 1024
