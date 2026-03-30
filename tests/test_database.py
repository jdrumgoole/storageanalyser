"""Tests for the scan database."""

from __future__ import annotations

from pathlib import Path

from storageanalyser.database import ScanDatabase, md5_file


class TestMd5File:
    def test_hashes_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        result = md5_file(str(f))
        assert result is not None
        assert len(result) == 32

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"identical")
        f2.write_bytes(b"identical")
        assert md5_file(str(f1)) == md5_file(str(f2))

    def test_different_content(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"aaa")
        f2.write_bytes(b"bbb")
        assert md5_file(str(f1)) != md5_file(str(f2))

    def test_nonexistent(self, tmp_path: Path) -> None:
        assert md5_file(str(tmp_path / "nope")) is None


class TestScanDatabase:
    def _make_db(self, tmp_path: Path) -> ScanDatabase:
        return ScanDatabase(db_path=tmp_path / "test.db")

    def test_create_and_list_scan(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        scan_id = db.create_scan("local", "/home/user")
        scans = db.list_scans()
        assert len(scans) == 1
        assert scans[0]["id"] == scan_id
        assert scans[0]["source"] == "local"
        db.close()

    def test_add_files(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        scan_id = db.create_scan("local", "/tmp")
        db.add_files(scan_id, [
            {"source": "local", "path": "/tmp/a.txt", "name": "a.txt",
             "size": 100, "md5": "abc123"},
            {"source": "local", "path": "/tmp/b.txt", "name": "b.txt",
             "size": 200, "md5": "def456"},
        ])
        stats = db.get_stats()
        assert stats["file_count"] == 2
        db.close()

    def test_delete_scan_cascades(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        scan_id = db.create_scan("local", "/tmp")
        db.add_files(scan_id, [
            {"source": "local", "path": "/tmp/x", "name": "x", "size": 50},
        ])
        db.delete_scan(scan_id)
        assert db.get_stats()["file_count"] == 0
        assert len(db.list_scans()) == 0
        db.close()

    def test_find_duplicates_by_md5(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        s1 = db.create_scan("local", "/disk")
        s2 = db.create_scan("gdrive", "Google Drive")
        db.add_files(s1, [
            {"source": "local", "path": "/disk/photo.jpg", "name": "photo.jpg",
             "size": 5000, "md5": "samehash"},
        ])
        db.add_files(s2, [
            {"source": "gdrive", "path": "gdrive://123", "name": "photo.jpg",
             "size": 5000, "md5": "samehash"},
        ])
        result = db.find_duplicates(min_size=1)
        assert result["group_count"] == 1
        group = result["groups"][0]
        assert group["cross_source"] is True
        assert group["count"] == 2
        assert group["md5"] == "samehash"
        db.close()

    def test_no_duplicates_different_md5(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        scan_id = db.create_scan("local", "/tmp")
        db.add_files(scan_id, [
            {"source": "local", "path": "/a", "name": "a", "size": 100, "md5": "aaa"},
            {"source": "local", "path": "/b", "name": "b", "size": 100, "md5": "bbb"},
        ])
        result = db.find_duplicates(min_size=1)
        assert result["group_count"] == 0
        db.close()

    def test_within_source_duplicates(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        scan_id = db.create_scan("local", "/disk")
        db.add_files(scan_id, [
            {"source": "local", "path": "/disk/a/file.txt", "name": "file.txt",
             "size": 2000, "md5": "xxx"},
            {"source": "local", "path": "/disk/b/file.txt", "name": "file.txt",
             "size": 2000, "md5": "xxx"},
        ])
        result = db.find_duplicates(min_size=1)
        assert result["group_count"] == 1
        assert result["groups"][0]["cross_source"] is False
        db.close()

    def test_savings_calculation(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        scan_id = db.create_scan("local", "/disk")
        db.add_files(scan_id, [
            {"source": "local", "path": "/a", "name": "a", "size": 1000, "md5": "dup"},
            {"source": "local", "path": "/b", "name": "b", "size": 1000, "md5": "dup"},
            {"source": "local", "path": "/c", "name": "c", "size": 1000, "md5": "dup"},
        ])
        result = db.find_duplicates(min_size=1)
        # 3 copies, keep 1 = save 2 * 1000
        assert result["total_savings"] == 2000
        db.close()

    def test_delete_scans_for_source(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        db.create_scan("local", "/home")
        db.create_scan("local", "/home")
        assert len(db.list_scans()) == 2
        db.delete_scans_for_source("local", "/home")
        assert len(db.list_scans()) == 0
        db.close()

    def test_compute_missing_checksums(self, tmp_path: Path) -> None:
        # Create real files with same size
        f1 = tmp_path / "file1.bin"
        f2 = tmp_path / "file2.bin"
        f1.write_bytes(b"same content here")
        f2.write_bytes(b"same content here")

        db = ScanDatabase(db_path=tmp_path / "test.db")
        scan_id = db.create_scan("local", str(tmp_path))
        db.add_files(scan_id, [
            {"source": "local", "path": str(f1), "name": "file1.bin",
             "size": 17, "md5": None},
            {"source": "local", "path": str(f2), "name": "file2.bin",
             "size": 17, "md5": None},
        ])

        count = db.compute_missing_checksums()
        assert count == 2

        result = db.find_duplicates(min_size=1)
        assert result["group_count"] == 1
        db.close()

    def test_checksum_cache_carry_forward(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        # First scan with checksums
        s1 = db.create_scan("local", "/disk")
        db.add_files(s1, [
            {"source": "local", "path": "/disk/a.txt", "name": "a.txt",
             "size": 100, "md5": "abc123", "modified_time": "2026-01-01T00:00:00"},
            {"source": "local", "path": "/disk/b.txt", "name": "b.txt",
             "size": 200, "md5": "def456", "modified_time": "2026-01-01T00:00:00"},
        ])

        # Get cache before deleting
        cache = db.get_checksum_cache("local", "/disk")
        assert len(cache) == 2
        assert cache[("/disk/a.txt", 100, "2026-01-01T00:00:00")] == "abc123"
        assert cache[("/disk/b.txt", 200, "2026-01-01T00:00:00")] == "def456"

        # Simulate rescan: delete old, create new, use cache
        db.delete_scans_for_source("local", "/disk")
        s2 = db.create_scan("local", "/disk")
        # a.txt unchanged, b.txt modified (different mtime)
        md5_a = cache.get(("/disk/a.txt", 100, "2026-01-01T00:00:00"))
        md5_b = cache.get(("/disk/b.txt", 200, "2026-06-01T00:00:00"))  # changed
        db.add_files(s2, [
            {"source": "local", "path": "/disk/a.txt", "name": "a.txt",
             "size": 100, "md5": md5_a, "modified_time": "2026-01-01T00:00:00"},
            {"source": "local", "path": "/disk/b.txt", "name": "b.txt",
             "size": 200, "md5": md5_b, "modified_time": "2026-06-01T00:00:00"},
        ])

        stats = db.get_stats()
        assert stats["checksummed"] == 1  # only a.txt carried forward
        db.close()

    def test_checksum_cache_empty_for_unknown(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        cache = db.get_checksum_cache("local", "/unknown")
        assert cache == {}
        db.close()

    def test_get_stats(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        scan_id = db.create_scan("gdrive", "Google Drive")
        db.add_files(scan_id, [
            {"source": "gdrive", "path": "g://1", "name": "x", "size": 500, "md5": "h1"},
        ])
        stats = db.get_stats()
        assert stats["scan_count"] == 1
        assert stats["file_count"] == 1
        assert stats["checksummed"] == 1
        assert stats["total_size"] == 500
        assert "gdrive" in stats["sources"]
        db.close()
