#!/usr/bin/env python3
"""
disk_analyzer.py — macOS Disk Space Analyzer & Cleanup Recommender

Scans your home directory (and optionally other paths) to find:
  - Large files hogging space
  - Stale files you haven't touched in ages
  - Known junk directories (caches, logs, build artifacts, node_modules, etc.)
  - Duplicate files (by size + hash)

Outputs a prioritised list of cleanup recommendations with estimated space savings.

Requirements: Python 3.9+ (uses stdlib only — no pip install needed)

Usage:
    python disk_analyzer.py                  # Scan ~/
    python disk_analyzer.py /Volumes/Data    # Scan a specific path
    python disk_analyzer.py --top 30         # Show top 30 large files
    python disk_analyzer.py --duplicates     # Include duplicate detection (slower)
    python disk_analyzer.py --json           # Machine-readable JSON output
    python disk_analyzer.py --dry-run        # Pair with --interactive for preview
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

STALE_THRESHOLD_DAYS = 365  # Files not accessed in this long are "stale"

ONE_KB = 1024
ONE_MB = ONE_KB * 1024
ONE_GB = ONE_MB * 1024

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class Category(str, Enum):
    JUNK_DIR = "junk_directory"
    ARTIFACT = "build_artifact"
    LARGE_FILE = "large_file"
    STALE_FILE = "stale_file"
    DUPLICATE = "duplicate"
    DOWNLOAD = "old_download"


@dataclass
class Recommendation:
    path: str
    size: int
    category: Category
    reason: str
    age_days: int | None = None

    @property
    def priority_score(self) -> float:
        """Higher = better candidate for deletion."""
        score = self.size / ONE_MB  # base: size in MB
        if self.category in (Category.JUNK_DIR, Category.ARTIFACT):
            score *= 3  # almost always safe
        if self.category == Category.DUPLICATE:
            score *= 2
        if self.age_days and self.age_days > STALE_THRESHOLD_DAYS:
            score *= 1.5
        return score


@dataclass
class ScanResult:
    root: str
    total_scanned: int = 0
    total_size: int = 0
    errors: int = 0
    recommendations: list[Recommendation] = field(default_factory=list)
    duplicates: list[list[str]] = field(default_factory=list)
    scan_seconds: float = 0.0

    @property
    def reclaimable(self) -> int:
        seen: set[str] = set()
        total = 0
        for r in self.recommendations:
            if r.path not in seen:
                seen.add(r.path)
                total += r.size
        return total


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class DiskAnalyzer:
    def __init__(
        self,
        root: Path,
        *,
        top_n: int = 20,
        find_duplicates: bool = False,
        large_threshold: int = 100 * ONE_MB,
        progress: bool = True,
        workers: int = 8,
        ignore_dirs: list[str] | None = None,
    ):
        self.root = root.expanduser().resolve()
        self.top_n = top_n
        self.find_duplicates = find_duplicates
        self.large_threshold = large_threshold
        self.progress = progress and sys.stdout.isatty()
        self.workers = workers

        # Resolve ignore dirs to absolute paths for reliable prefix matching,
        # and also keep bare names for simple basename matching (e.g. "node_modules")
        self._ignore_resolved: set[Path] = set()
        self._ignore_names: set[str] = set()
        for d in (ignore_dirs or []):
            p = Path(d).expanduser()
            if p.is_absolute() or os.sep in d:
                self._ignore_resolved.add(p.resolve())
            else:
                # Bare name like "node_modules" — match by directory name anywhere
                self._ignore_names.add(d)

        self._result = ScanResult(root=str(self.root))
        self._size_index: dict[int, list[Path]] = defaultdict(list)  # for dupe detection
        self._seen_inodes: set[int] = set()  # skip hard-link duplicates

    # ----- directory walking helpers -----

    def _should_skip(self, path: Path) -> bool:
        """Skip things that will waste time or cause problems."""
        name = path.name

        # User-specified ignore list (bare names or resolved absolute paths)
        if name in self._ignore_names:
            return True
        try:
            if path.resolve() in self._ignore_resolved:
                return True
        except (OSError, PermissionError):
            pass

        if name.startswith("."):
            # Allow specific dot-dirs we care about
            if name not in {".cache", ".npm", ".yarn", ".gradle", ".m2",
                            ".cocoapods", ".cargo", ".Trash", ".tox",
                            ".pytest_cache", ".mypy_cache", ".ruff_cache",
                            ".next", ".nuxt", ".parcel-cache", ".turbo",
                            ".venv", ".eggs"}:
                # Skip hidden dirs we don't explicitly scan
                if path.is_dir():
                    return True
        # Skip system-y things
        if name in {"Photos Library.photoslibrary", "Music", "Movies",
                     ".Spotlight-V100", ".fseventsd", ".DocumentRevisions-V100"}:
            return True
        return False

    def _walk(self, top: Path) -> Iterator[tuple[Path, os.stat_result]]:
        """Walk the tree yielding (path, stat) — handles permission errors."""
        try:
            with os.scandir(top) as entries:
                dirs: list[Path] = []
                for entry in entries:
                    p = Path(entry.path)
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except (OSError, PermissionError):
                        self._result.errors += 1
                        continue

                    # Skip symlinks entirely
                    if stat.S_ISLNK(st.st_mode):
                        continue

                    # Dedup hard links
                    if st.st_ino in self._seen_inodes:
                        continue
                    self._seen_inodes.add(st.st_ino)

                    if stat.S_ISDIR(st.st_mode):
                        if not self._should_skip(p):
                            dirs.append(p)
                    elif stat.S_ISREG(st.st_mode):
                        self._result.total_scanned += 1
                        self._result.total_size += st.st_size
                        yield p, st

                for d in dirs:
                    yield from self._walk(d)
        except PermissionError:
            self._result.errors += 1

    # ----- analysis passes -----

    def _check_junk_dirs(self) -> None:
        """Check well-known junk/cache directories — sized in parallel."""
        home = Path.home()

        def _size_one(rel: str, reason: str) -> Recommendation | None:
            target = home / rel
            if not target.exists() or not target.is_dir():
                return None
            try:
                size = sum(
                    f.stat().st_size
                    for f in target.rglob("*")
                    if f.is_file()
                )
            except (OSError, PermissionError):
                size = 0
            if size > ONE_MB:
                return Recommendation(
                    path=str(target),
                    size=size,
                    category=Category.JUNK_DIR,
                    reason=reason,
                )
            return None

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {
                pool.submit(_size_one, rel, reason): rel
                for rel, reason in JUNK_DIRS
            }
            for fut in as_completed(futures):
                rec = fut.result()
                if rec:
                    self._result.recommendations.append(rec)

    def _check_artifacts(self, path: Path, st: os.stat_result) -> None:
        """Flag node_modules, __pycache__, etc. encountered during the walk."""
        # We check parent components for artifact dir names
        parts = path.parts
        for part in parts:
            if part in ARTIFACT_DIR_NAMES:
                # Report at the artifact directory level
                idx = parts.index(part)
                artifact_dir = Path(*parts[: idx + 1])
                # Avoid duplicate recommendations for same dir
                artifact_str = str(artifact_dir)
                if not any(r.path == artifact_str for r in self._result.recommendations):
                    try:
                        size = sum(
                            f.stat().st_size
                            for f in artifact_dir.rglob("*")
                            if f.is_file()
                        )
                    except (OSError, PermissionError):
                        size = st.st_size
                    if size > ONE_MB:
                        self._result.recommendations.append(
                            Recommendation(
                                path=artifact_str,
                                size=size,
                                category=Category.ARTIFACT,
                                reason=f"Build/dependency artifact ({part}/)",
                            )
                        )
                break  # only flag outermost artifact dir

    def _check_large_file(self, path: Path, st: os.stat_result) -> None:
        if st.st_size >= self.large_threshold:
            ext = path.suffix.lower()
            age = file_age_days(st)
            reason = f"Large file ({human_size(st.st_size)})"
            if ext in LARGE_FILE_EXTENSIONS:
                reason += f" — {ext} files are often disposable"
            self._result.recommendations.append(
                Recommendation(
                    path=str(path),
                    size=st.st_size,
                    category=Category.LARGE_FILE,
                    reason=reason,
                    age_days=age,
                )
            )

    def _check_stale_file(self, path: Path, st: os.stat_result) -> None:
        age = file_age_days(st)
        if age > STALE_THRESHOLD_DAYS and st.st_size > 10 * ONE_MB:
            self._result.recommendations.append(
                Recommendation(
                    path=str(path),
                    size=st.st_size,
                    category=Category.STALE_FILE,
                    reason=f"Not accessed in {age} days ({human_size(st.st_size)})",
                    age_days=age,
                )
            )

    def _check_downloads(self) -> None:
        """Specifically flag old items in ~/Downloads."""
        dl = Path.home() / "Downloads"
        if not dl.exists():
            return
        cutoff = time.time() - (180 * 86400)  # 6 months
        for entry in dl.iterdir():
            try:
                st = entry.stat()
                if max(st.st_atime, st.st_mtime) < cutoff and st.st_size > ONE_MB:
                    self._result.recommendations.append(
                        Recommendation(
                            path=str(entry),
                            size=st.st_size if entry.is_file() else self._dir_size(entry),
                            category=Category.DOWNLOAD,
                            reason=f"In ~/Downloads for {file_age_days(st)} days",
                            age_days=file_age_days(st),
                        )
                    )
            except (OSError, PermissionError):
                continue

    @staticmethod
    def _dir_size(p: Path) -> int:
        try:
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        except (OSError, PermissionError):
            return 0

    def _detect_duplicates(self) -> None:
        """Group files by size, then hash heads in parallel to find duplicates."""
        if not self.find_duplicates:
            return
        # Only check files > 1 MB to keep it practical
        candidates = {sz: paths for sz, paths in self._size_index.items()
                      if len(paths) > 1 and sz > ONE_MB}

        # Flatten to a list of (size, path) for the thread pool
        to_hash: list[tuple[int, Path]] = [
            (sz, p)
            for sz, paths in candidates.items()
            for p in paths
        ]

        if not to_hash:
            return

        hash_groups: dict[str, list[Path]] = defaultdict(list)

        # Hash file heads in parallel — GIL releases for open()/read()/hashlib
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            future_to_meta = {
                pool.submit(sha256_head, p): (sz, p)
                for sz, p in to_hash
            }
            for fut in as_completed(future_to_meta):
                sz, p = future_to_meta[fut]
                h = fut.result()
                if h:
                    hash_groups[f"{sz}:{h}"].append(p)

        for key, paths in hash_groups.items():
            if len(paths) < 2:
                continue
            # Keep the first, recommend deleting the rest
            self._result.duplicates.append([str(p) for p in paths])
            sz = int(key.split(":")[0])
            for p in paths[1:]:
                self._result.recommendations.append(
                    Recommendation(
                        path=str(p),
                        size=sz,
                        category=Category.DUPLICATE,
                        reason=f"Duplicate of {paths[0].name} ({human_size(sz)})",
                    )
                )

    # ----- main entry point -----

    def scan(self) -> ScanResult:
        t0 = time.monotonic()

        # Phase 1: well-known junk dirs (parallel sizing across thread pool)
        if self.progress:
            print(Colour.cyan(f"▸ Checking known cache/junk directories ({self.workers} threads)..."))
        self._check_junk_dirs()

        # Phase 2: check ~/Downloads specifically
        if self.progress:
            print(Colour.cyan("▸ Scanning ~/Downloads for old files..."))
        self._check_downloads()

        # Phase 3: full tree walk
        if self.progress:
            print(Colour.cyan(f"▸ Walking {self.root} (this may take a moment)..."))

        count = 0
        for path, st in self._walk(self.root):
            count += 1
            if self.progress and count % 5000 == 0:
                print(f"  …scanned {count:,} files ({human_size(self._result.total_size)})…",
                      end="\r", flush=True)

            self._check_large_file(path, st)
            self._check_stale_file(path, st)
            # Artifact check only for files under the scan root
            self._check_artifacts(path, st)

            if self.find_duplicates:
                self._size_index[st.st_size].append(path)

        if self.progress:
            print()  # clear the \r line

        # Phase 4: duplicate detection
        if self.find_duplicates:
            if self.progress:
                print(Colour.cyan(f"▸ Detecting duplicates ({self.workers} threads hashing)..."))
            self._detect_duplicates()

        self._result.scan_seconds = time.monotonic() - t0

        # Sort by priority (highest first) and deduplicate
        seen: set[str] = set()
        unique: list[Recommendation] = []
        for r in sorted(self._result.recommendations,
                        key=lambda r: r.priority_score, reverse=True):
            if r.path not in seen:
                seen.add(r.path)
                unique.append(r)
        self._result.recommendations = unique

        return self._result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


CATEGORY_LABELS: dict[Category, str] = {
    Category.JUNK_DIR: "🗑  Cache/Junk",
    Category.ARTIFACT: "📦 Build Artifact",
    Category.LARGE_FILE: "💾 Large File",
    Category.STALE_FILE: "🕸  Stale File",
    Category.DUPLICATE: "♊ Duplicate",
    Category.DOWNLOAD: "⬇️  Old Download",
}

CATEGORY_COMMANDS: dict[Category, str] = {
    Category.JUNK_DIR: "rm -rf '{path}'",
    Category.ARTIFACT: "rm -rf '{path}'",
    Category.LARGE_FILE: "rm '{path}'",
    Category.STALE_FILE: "rm '{path}'",
    Category.DUPLICATE: "rm '{path}'",
    Category.DOWNLOAD: "rm -rf '{path}'",
}


def print_report(result: ScanResult, top_n: int) -> None:
    """Pretty-print the analysis to the terminal."""
    print()
    print(Colour.bold("═" * 72))
    print(Colour.bold("  macOS Disk Space Analyzer — Report"))
    print(Colour.bold("═" * 72))
    print()
    print(f"  Scanned root:    {result.root}")
    print(f"  Files scanned:   {result.total_scanned:,}")
    print(f"  Total size:      {human_size(result.total_size)}")
    print(f"  Scan time:       {result.scan_seconds:.1f}s")
    print(f"  Read errors:     {result.errors:,}")
    print()

    recs = result.recommendations[:top_n]
    if not recs:
        print(Colour.green("  ✓ No significant cleanup recommendations found. Tidy disk!"))
        return

    print(Colour.bold(f"  Top {len(recs)} Cleanup Recommendations"))
    print(Colour.bold(f"  (sorted by impact — estimated reclaimable: "
                      f"{Colour.red(human_size(result.reclaimable))})"))
    print()

    # Group by category for the summary
    by_cat: dict[Category, int] = defaultdict(int)
    for r in result.recommendations:
        by_cat[r.category] += r.size

    print(Colour.bold("  Breakdown by category:"))
    for cat in Category:
        if cat in by_cat:
            label = CATEGORY_LABELS[cat]
            print(f"    {label:<22} {human_size(by_cat[cat]):>10}")
    print()

    # Detailed list
    print(Colour.bold("  ─" * 36))
    for i, r in enumerate(recs, 1):
        label = CATEGORY_LABELS[r.category]
        age_str = f" (age: {r.age_days}d)" if r.age_days else ""
        size_str = human_size(r.size)

        # Shorten path for display
        display_path = r.path.replace(str(Path.home()), "~")

        print(f"  {Colour.bold(f'{i:>3}.')}  {label}")
        print(f"       {Colour.yellow(display_path)}")
        print(f"       {size_str}{age_str} — {r.reason}")
        print(f"       {Colour.dim(CATEGORY_COMMANDS[r.category].format(path=r.path))}")
        print()

    # Duplicates section
    if result.duplicates:
        print(Colour.bold("  Duplicate Groups Found:"))
        for group in result.duplicates[:10]:
            print(f"    • {group[0].replace(str(Path.home()), '~')}")
            for dup in group[1:]:
                print(f"      ≡ {dup.replace(str(Path.home()), '~')}")
            print()

    # Generate a cleanup script
    print(Colour.bold("  ─" * 36))
    print(Colour.bold("  Quick Cleanup Script"))
    print(Colour.dim("  (Review carefully before running!)"))
    print()
    print(Colour.dim("  # Save this to cleanup.sh, review, then: bash cleanup.sh"))
    for r in recs[:15]:
        cmd = CATEGORY_COMMANDS[r.category].format(path=r.path)
        print(f"  {cmd}  # {human_size(r.size)} — {r.reason}")

    print()
    print(Colour.bold("═" * 72))
    print(Colour.dim("  ⚠  Always review before deleting! Use Finder's Quick Look (Space bar)"))
    print(Colour.dim("     to inspect files. Move to Trash first if unsure: mv <file> ~/.Trash/"))
    print(Colour.bold("═" * 72))
    print()


def print_json(result: ScanResult, top_n: int) -> None:
    """Dump the result as JSON for piping to other tools."""
    output = {
        "root": result.root,
        "total_scanned": result.total_scanned,
        "total_size": result.total_size,
        "total_size_human": human_size(result.total_size),
        "reclaimable": result.reclaimable,
        "reclaimable_human": human_size(result.reclaimable),
        "scan_seconds": round(result.scan_seconds, 2),
        "errors": result.errors,
        "recommendations": [
            {
                "path": r.path,
                "size": r.size,
                "size_human": human_size(r.size),
                "category": r.category.value,
                "reason": r.reason,
                "age_days": r.age_days,
                "priority_score": round(r.priority_score, 2),
            }
            for r in result.recommendations[:top_n]
        ],
        "duplicate_groups": result.duplicates[:20],
    }
    json.dump(output, sys.stdout, indent=2)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="macOS Disk Space Analyzer — find what's eating your disk",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                           Scan home directory
  %(prog)s /Volumes/ExternalDrive    Scan a specific path
  %(prog)s --top 50 --duplicates     Deep scan with dupe detection
  %(prog)s --json | jq '.recommendations[:5]'
  %(prog)s --threshold 50            Flag files over 50 MB (default: 100)
  %(prog)s --ignoredir node_modules --ignoredir ~/Photos
""",
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=str(Path.home()),
        help="Root directory to scan (default: ~/)",
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=20,
        help="Number of recommendations to show (default: 20)",
    )
    parser.add_argument(
        "--duplicates", "-d",
        action="store_true",
        help="Enable duplicate file detection (slower — hashes file heads)",
    )
    parser.add_argument(
        "--threshold", "-t",
        type=int,
        default=100,
        help="Large file threshold in MB (default: 100)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable coloured output",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=8,
        help="Thread pool size for parallel I/O (default: 8)",
    )
    parser.add_argument(
        "--ignoredir",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory to skip (repeatable). Absolute path or bare name "
             "matched anywhere, e.g. --ignoredir node_modules --ignoredir ~/Photos",
    )

    args = parser.parse_args()

    if args.no_color:
        Colour.enabled = False

    root = Path(args.path)
    if not root.exists():
        print(f"Error: {root} does not exist", file=sys.stderr)
        sys.exit(1)

    analyzer = DiskAnalyzer(
        root,
        top_n=args.top,
        find_duplicates=args.duplicates,
        large_threshold=args.threshold * ONE_MB,
        progress=not args.json,
        workers=args.workers,
        ignore_dirs=args.ignoredir,
    )

    result = analyzer.scan()

    if args.json:
        print_json(result, args.top)
    else:
        print_report(result, args.top)


if __name__ == "__main__":
    main()
