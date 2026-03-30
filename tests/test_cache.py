"""Tests for scan cache."""

from __future__ import annotations

from pathlib import Path

from storageanalyser.cache import IgnoreDirsCache, ScanCache


class TestScanCache:
    def test_get_returns_none_for_unknown(self, tmp_path: Path) -> None:
        cache = ScanCache(cache_file=tmp_path / "cache.json")
        assert cache.get_expected_files("/some/path") is None

    def test_update_and_get(self, tmp_path: Path) -> None:
        cache = ScanCache(cache_file=tmp_path / "cache.json")
        cache.update("/Users/test", 42000)
        assert cache.get_expected_files("/Users/test") == 42000

    def test_persists_to_disk(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache.json"
        cache1 = ScanCache(cache_file=cache_file)
        cache1.update("/home/user", 10000)

        cache2 = ScanCache(cache_file=cache_file)
        assert cache2.get_expected_files("/home/user") == 10000

    def test_update_overwrites(self, tmp_path: Path) -> None:
        cache = ScanCache(cache_file=tmp_path / "cache.json")
        cache.update("/path", 100)
        cache.update("/path", 200)
        assert cache.get_expected_files("/path") == 200

    def test_handles_corrupt_file(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("not json {{{")
        cache = ScanCache(cache_file=cache_file)
        assert cache.get_expected_files("/any") is None

    def test_handles_missing_directory(self, tmp_path: Path) -> None:
        cache = ScanCache(cache_file=tmp_path / "subdir" / "deep" / "cache.json")
        cache.update("/path", 500)
        assert cache.get_expected_files("/path") == 500


class TestIgnoreDirsCache:
    def test_get_returns_empty_for_unknown(self, tmp_path: Path) -> None:
        cache = IgnoreDirsCache(cache_file=tmp_path / "ignore.json")
        assert cache.get("/some/path") == []

    def test_update_and_get(self, tmp_path: Path) -> None:
        cache = IgnoreDirsCache(cache_file=tmp_path / "ignore.json")
        cache.update("/Users/test", ["node_modules", ".git"])
        assert cache.get("/Users/test") == ["node_modules", ".git"]

    def test_persists_to_disk(self, tmp_path: Path) -> None:
        f = tmp_path / "ignore.json"
        cache1 = IgnoreDirsCache(cache_file=f)
        cache1.update("/home/user", ["build", "dist"])

        cache2 = IgnoreDirsCache(cache_file=f)
        assert cache2.get("/home/user") == ["build", "dist"]

    def test_empty_list_removes_entry(self, tmp_path: Path) -> None:
        cache = IgnoreDirsCache(cache_file=tmp_path / "ignore.json")
        cache.update("/path", ["node_modules"])
        cache.update("/path", [])
        assert cache.get("/path") == []

    def test_multiple_paths(self, tmp_path: Path) -> None:
        cache = IgnoreDirsCache(cache_file=tmp_path / "ignore.json")
        cache.update("/path1", ["a"])
        cache.update("/path2", ["b", "c"])
        assert cache.get("/path1") == ["a"]
        assert cache.get("/path2") == ["b", "c"]
