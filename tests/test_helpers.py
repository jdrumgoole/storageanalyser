"""Tests for helper utilities."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

from storageanalyser.helpers import Colour, file_age_days, human_size, sha256_head


class TestHumanSize:
    def test_bytes(self) -> None:
        assert human_size(500) == "500 B"

    def test_kilobytes(self) -> None:
        assert human_size(1024) == "1.0 KB"
        assert human_size(1536) == "1.5 KB"

    def test_megabytes(self) -> None:
        assert human_size(1024 * 1024) == "1.0 MB"
        assert human_size(10 * 1024 * 1024) == "10.0 MB"

    def test_gigabytes(self) -> None:
        assert human_size(1024 * 1024 * 1024) == "1.0 GB"
        assert human_size(2.5 * 1024 * 1024 * 1024) == "2.5 GB"

    def test_zero(self) -> None:
        assert human_size(0) == "0 B"


class TestSha256Head:
    def test_hashes_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        result = sha256_head(f)
        assert result is not None
        assert len(result) == 64  # SHA-256 hex digest length

    def test_same_content_same_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        content = b"identical content"
        f1.write_bytes(content)
        f2.write_bytes(content)
        assert sha256_head(f1) == sha256_head(f2)

    def test_different_content_different_hash(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"content a")
        f2.write_bytes(b"content b")
        assert sha256_head(f1) != sha256_head(f2)

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        result = sha256_head(tmp_path / "nonexistent")
        assert result is None


class TestFileAgeDays:
    def test_returns_int(self) -> None:
        st = os.stat(__file__)
        result = file_age_days(st)
        assert isinstance(result, int)
        assert result >= 0


class TestColour:
    def test_bold_with_color_disabled(self) -> None:
        Colour.enabled = False
        assert Colour.bold("test") == "test"

    def test_bold_with_color_enabled(self) -> None:
        Colour.enabled = True
        result = Colour.bold("test")
        assert "test" in result
        assert "\033[" in result

    def test_all_color_methods(self) -> None:
        Colour.enabled = True
        for method in [Colour.bold, Colour.red, Colour.yellow,
                       Colour.green, Colour.cyan, Colour.dim]:
            result = method("text")
            assert "text" in result
            assert "\033[" in result
