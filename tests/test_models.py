"""Tests for data models."""

from __future__ import annotations

from storageanalyser.constants import ONE_MB
from storageanalyser.models import Category, Recommendation, ScanResult


class TestRecommendation:
    def test_priority_score_scales_with_size(self) -> None:
        small = Recommendation(path="/a", size=10 * ONE_MB, category=Category.LARGE_FILE, reason="test")
        large = Recommendation(path="/b", size=100 * ONE_MB, category=Category.LARGE_FILE, reason="test")
        assert large.priority_score > small.priority_score

    def test_junk_dir_gets_bonus(self) -> None:
        junk = Recommendation(path="/a", size=50 * ONE_MB, category=Category.JUNK_DIR, reason="test")
        large = Recommendation(path="/b", size=50 * ONE_MB, category=Category.LARGE_FILE, reason="test")
        assert junk.priority_score > large.priority_score

    def test_stale_gets_bonus(self) -> None:
        stale = Recommendation(path="/a", size=50 * ONE_MB, category=Category.STALE_FILE,
                               reason="test", age_days=400)
        fresh = Recommendation(path="/b", size=50 * ONE_MB, category=Category.STALE_FILE,
                               reason="test", age_days=100)
        assert stale.priority_score > fresh.priority_score

    def test_duplicate_gets_bonus(self) -> None:
        dup = Recommendation(path="/a", size=50 * ONE_MB, category=Category.DUPLICATE, reason="test")
        large = Recommendation(path="/b", size=50 * ONE_MB, category=Category.LARGE_FILE, reason="test")
        assert dup.priority_score > large.priority_score


class TestScanResult:
    def test_reclaimable_deduplicates(self) -> None:
        result = ScanResult(root="/")
        result.recommendations = [
            Recommendation(path="/same", size=100, category=Category.LARGE_FILE, reason="test"),
            Recommendation(path="/same", size=100, category=Category.STALE_FILE, reason="test"),
            Recommendation(path="/other", size=200, category=Category.LARGE_FILE, reason="test"),
        ]
        assert result.reclaimable == 300  # /same counted once + /other

    def test_empty_result(self) -> None:
        result = ScanResult(root="/")
        assert result.reclaimable == 0
        assert result.total_scanned == 0
