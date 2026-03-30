"""Tests for the disk analyzer engine."""

from __future__ import annotations

import errno
from pathlib import Path
from unittest.mock import patch

from storageanalyser.analyzer import DiskAnalyzer
from storageanalyser.constants import ONE_MB
from storageanalyser.models import Category


class TestDiskAnalyzer:
    def test_scan_empty_dir(self, tmp_path: Path) -> None:
        analyzer = DiskAnalyzer(tmp_path, progress=False)
        result = analyzer.scan()
        assert result.total_scanned == 0
        assert result.errors == 0

    def test_scan_finds_large_file(self, tmp_path: Path) -> None:
        large_file = tmp_path / "big.bin"
        large_file.write_bytes(b"\x00" * (101 * ONE_MB))
        analyzer = DiskAnalyzer(tmp_path, progress=False)
        result = analyzer.scan()
        large_recs = [r for r in result.recommendations if r.category == Category.LARGE_FILE]
        assert len(large_recs) == 1
        assert "big.bin" in large_recs[0].path

    def test_threshold_respected(self, tmp_path: Path) -> None:
        f = tmp_path / "medium.bin"
        f.write_bytes(b"\x00" * (50 * ONE_MB))
        analyzer = DiskAnalyzer(tmp_path, large_threshold=100 * ONE_MB, progress=False)
        result = analyzer.scan()
        large_recs = [r for r in result.recommendations if r.category == Category.LARGE_FILE]
        assert len(large_recs) == 0

    def test_ignore_dir_by_name(self, tmp_path: Path) -> None:
        skip_dir = tmp_path / "skipme"
        skip_dir.mkdir()
        (skip_dir / "file.txt").write_text("data")
        analyzer = DiskAnalyzer(tmp_path, progress=False, ignore_dirs=["skipme"])
        result = analyzer.scan()
        scanned_paths = [r.path for r in result.recommendations]
        assert not any("skipme" in p for p in scanned_paths)

    def test_scan_counts_files(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"file{i}.txt").write_text(f"content {i}")
        analyzer = DiskAnalyzer(tmp_path, progress=False)
        result = analyzer.scan()
        assert result.total_scanned == 5

    def test_should_skip_hidden_dirs(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".hidden_dir"
        hidden.mkdir()
        (hidden / "secret.txt").write_text("secret")
        analyzer = DiskAnalyzer(tmp_path, progress=False)
        result = analyzer.scan()
        assert result.total_scanned == 0

    def test_should_skip_cloud_storage(self, tmp_path: Path) -> None:
        """CloudStorage dirs (e.g. Google Drive) should be skipped by default."""
        cloud = tmp_path / "CloudStorage"
        cloud.mkdir()
        (cloud / "big.bin").write_bytes(b"\x00" * (101 * ONE_MB))
        analyzer = DiskAnalyzer(tmp_path, progress=False)
        result = analyzer.scan()
        assert result.total_scanned == 0

    def test_include_dirs_overrides_skip(self, tmp_path: Path) -> None:
        """include_dirs should override default-skipped directories."""
        cloud = tmp_path / "CloudStorage"
        cloud.mkdir()
        (cloud / "file.txt").write_text("hello")
        # Without include_dirs — skipped
        result1 = DiskAnalyzer(tmp_path, progress=False).scan()
        assert result1.total_scanned == 0
        # With include_dirs — scanned
        result2 = DiskAnalyzer(tmp_path, progress=False, include_dirs=["CloudStorage"]).scan()
        assert result2.total_scanned == 1

    def test_walk_handles_interrupted_syscall(self, tmp_path: Path) -> None:
        """Regression: EINTR from scandir should be counted as error, not crash."""
        (tmp_path / "good.txt").write_text("ok")
        subdir = tmp_path / "baddir"
        subdir.mkdir()

        real_scandir = DiskAnalyzer._walk

        def patched_walk(self_inner: DiskAnalyzer, top: Path):  # type: ignore[override]
            if top == subdir:
                raise OSError(errno.EINTR, "Interrupted system call", str(subdir))
            yield from real_scandir(self_inner, top)

        with patch.object(DiskAnalyzer, "_walk", patched_walk):
            analyzer = DiskAnalyzer(tmp_path, progress=False)
            result = analyzer.scan()

        assert result.errors >= 1
        assert result.total_scanned >= 1

    def test_cancel_stops_scan_early(self, tmp_path: Path) -> None:
        """Cancelling mid-scan should stop the walk and return partial results."""
        for i in range(20):
            (tmp_path / f"file{i}.txt").write_text(f"content {i}")
        analyzer = DiskAnalyzer(tmp_path, progress=False)
        # Cancel immediately — the scan should still return without error
        analyzer.cancelled = True
        result = analyzer.scan()
        # Walk was skipped so no files should be scanned
        assert result.total_scanned == 0

    def test_junk_dirs_scoped_to_scan_root(self, tmp_path: Path) -> None:
        """Regression: junk dirs outside scan root should not appear in results."""
        (tmp_path / "file.txt").write_text("data")
        analyzer = DiskAnalyzer(tmp_path, progress=False)
        result = analyzer.scan()
        # tmp_path is not under ~, so no junk dirs or downloads should appear
        junk_recs = [r for r in result.recommendations
                     if r.category == Category.JUNK_DIR]
        download_recs = [r for r in result.recommendations
                         if r.category == Category.DOWNLOAD]
        assert len(junk_recs) == 0
        assert len(download_recs) == 0
