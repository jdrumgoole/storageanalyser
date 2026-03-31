"""Core disk analyzer engine."""

from __future__ import annotations

import os
import stat
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections.abc import Callable
from typing import Iterator

from storageanalyser.constants import (
    ARTIFACT_DIR_NAMES,
    DEFAULT_SKIP_DIRS,
    JUNK_DIRS,
    LARGE_FILE_EXTENSIONS,
    ONE_MB,
    SCANNABLE_HIDDEN_DIRS,
    STALE_THRESHOLD_DAYS,
)
from storageanalyser.helpers import Colour, file_age_days, human_size, sha256_head
from storageanalyser.models import Category, Recommendation, ScanResult
from storageanalyser.platform import IS_WINDOWS


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
        include_dirs: list[str] | None = None,
        progress_callback: Callable[[str, str, int, int], None] | None = None,
    ) -> None:
        self.root = root.expanduser().resolve()
        self.top_n = top_n
        self.find_duplicates = find_duplicates
        self.large_threshold = large_threshold
        self.progress = progress and sys.stdout.isatty()
        self.workers = workers

        self._ignore_resolved: set[Path] = set()
        self._ignore_names: set[str] = set()
        for d in (ignore_dirs or []):
            p = Path(d).expanduser()
            if p.is_absolute() or os.sep in d:
                self._ignore_resolved.add(p.resolve())
            else:
                self._ignore_names.add(d)

        # Build the effective skip set from DEFAULT_SKIP_DIRS minus any
        # directories the user explicitly asked to include.
        self._skip_dirs: set[str] = set(DEFAULT_SKIP_DIRS.keys())
        for d in (include_dirs or []):
            self._skip_dirs.discard(d)

        self._progress_callback = progress_callback
        self._result = ScanResult(root=str(self.root))
        self._size_index: dict[int, list[Path]] = defaultdict(list)
        self._seen_inodes: set[int] = set()
        self.scanned_files: list[tuple[str, str, int, float]] = []  # (path, name, size, mtime)
        self.cancelled = False

    def _emit(self, phase: str, message: str) -> None:
        """Emit progress via stdout (CLI) and/or callback (web)."""
        if self.progress:
            print(Colour.cyan(f"▸ {message}"))
        if self._progress_callback:
            self._progress_callback(
                phase, message,
                self._result.total_scanned, self._result.total_size,
            )

    def _should_skip(self, path: Path) -> bool:
        """Skip things that will waste time or cause problems."""
        name = path.name

        if name in self._ignore_names:
            return True
        try:
            if path.resolve() in self._ignore_resolved:
                return True
        except (OSError, PermissionError):
            pass

        if name.startswith("."):
            if name not in SCANNABLE_HIDDEN_DIRS:
                if path.is_dir():
                    return True
        if name in self._skip_dirs:
            return True
        return False

    def _walk(self, top: Path) -> Iterator[tuple[Path, os.stat_result]]:
        """Walk the tree yielding (path, stat) — handles permission errors."""
        if self.cancelled:
            return
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

                    if stat.S_ISLNK(st.st_mode):
                        continue

                    # On Windows st_ino may be 0; skip dedup in that case
                    if st.st_ino != 0:
                        if st.st_ino in self._seen_inodes:
                            continue
                        self._seen_inodes.add(st.st_ino)

                    if stat.S_ISDIR(st.st_mode):
                        if not self._should_skip(p):
                            dirs.append(p)
                    elif stat.S_ISREG(st.st_mode):
                        self._result.total_scanned += 1
                        self._result.total_size += st.st_size
                        self.scanned_files.append((
                            str(p), p.name, st.st_size,
                            max(st.st_atime, st.st_mtime),
                        ))
                        yield p, st

                for d in dirs:
                    yield from self._walk(d)
        except OSError:
            self._result.errors += 1

    def _check_junk_dirs(self) -> None:
        """Check well-known junk/cache directories — sized in parallel.

        Only checks directories that fall within the scan root.
        """
        home = Path.home()
        root = self.root

        def _size_one(rel: str, reason: str) -> Recommendation | None:
            target = home / rel
            # Only include junk dirs that are within the scan root
            try:
                target.resolve().relative_to(root)
            except ValueError:
                return None
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
        parts = path.parts
        for part in parts:
            if part in ARTIFACT_DIR_NAMES:
                idx = parts.index(part)
                artifact_dir = Path(*parts[: idx + 1])
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
                break

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
        """Specifically flag old items in ~/Downloads.

        Only runs when ~/Downloads is within the scan root.
        """
        dl = Path.home() / "Downloads"
        if not dl.exists():
            return
        try:
            dl.resolve().relative_to(self.root)
        except ValueError:
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
        candidates = {sz: paths for sz, paths in self._size_index.items()
                      if len(paths) > 1 and sz > ONE_MB}

        to_hash: list[tuple[int, Path]] = [
            (sz, p)
            for sz, paths in candidates.items()
            for p in paths
        ]

        if not to_hash:
            return

        hash_groups: dict[str, list[Path]] = defaultdict(list)

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
            self._result.duplicates.append([str(p) for p in paths])
            sz = int(key.split(":")[0])
            all_paths = [str(p) for p in paths]
            num_copies = len(paths) - 1
            wasted = num_copies * sz
            copies_label = (f"{num_copies} {'copy' if num_copies == 1 else 'copies'}, "
                            f"{human_size(sz)} each, {human_size(wasted)} wasted")
            for i, p in enumerate(paths[1:]):
                others = [ap for j, ap in enumerate(all_paths) if j != i + 1]
                reason = (f"Duplicate ({copies_label}): "
                          + ", ".join(others))
                self._result.recommendations.append(
                    Recommendation(
                        path=str(p),
                        size=sz,
                        category=Category.DUPLICATE,
                        reason=reason,
                    )
                )

    def scan(self) -> ScanResult:
        t0 = time.monotonic()

        self._emit("junk_dirs", f"Checking known cache/junk directories ({self.workers} threads)...")
        self._check_junk_dirs()

        self._emit("downloads", "Scanning ~/Downloads for old files...")
        self._check_downloads()

        self._emit("walk", f"Walking {self.root} (this may take a moment)...")

        count = 0
        for path, st in self._walk(self.root):
            if self.cancelled:
                break
            count += 1
            if count % 5000 == 0:
                msg = f"Scanned {count:,} files ({human_size(self._result.total_size)})…"
                if self.progress:
                    print(f"  …{msg}", end="\r", flush=True)
                if self._progress_callback:
                    self._progress_callback(
                        "walk", msg,
                        self._result.total_scanned, self._result.total_size,
                    )

            self._check_large_file(path, st)
            self._check_stale_file(path, st)
            self._check_artifacts(path, st)

            if self.find_duplicates:
                self._size_index[st.st_size].append(path)

        if self.progress:
            print()

        if self.find_duplicates and not self.cancelled:
            self._emit("duplicates", f"Detecting duplicates ({self.workers} threads hashing)...")
            self._detect_duplicates()

        self._result.scan_seconds = time.monotonic() - t0

        seen: set[str] = set()
        unique: list[Recommendation] = []
        for r in sorted(self._result.recommendations,
                        key=lambda r: r.priority_score, reverse=True):
            if r.path not in seen:
                seen.add(r.path)
                unique.append(r)
        self._result.recommendations = unique

        return self._result
