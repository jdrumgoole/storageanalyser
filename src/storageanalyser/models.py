"""Data models for disk analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from storageanalyser.constants import ONE_MB, STALE_THRESHOLD_DAYS


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
    def priority_score(self) -> int:
        """Higher = better candidate for deletion."""
        score = self.size / ONE_MB  # base: size in MB
        if self.category in (Category.JUNK_DIR, Category.ARTIFACT):
            score *= 3  # almost always safe
        if self.category == Category.DUPLICATE:
            score *= 2
        if self.age_days and self.age_days > STALE_THRESHOLD_DAYS:
            score *= 1.5
        return int(score)


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
