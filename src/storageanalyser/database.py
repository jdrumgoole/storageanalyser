"""SQLite database for caching scan results and cross-environment dedup."""

from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from storageanalyser.helpers import human_size

DEFAULT_DB_PATH = Path.home() / ".cache" / "storageanalyser" / "scans.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    root TEXT NOT NULL,
    timestamp REAL NOT NULL,
    total_files INTEGER DEFAULT 0,
    total_size INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER NOT NULL,
    md5 TEXT,
    modified_time TEXT,
    mime_type TEXT,
    web_link TEXT,
    UNIQUE(scan_id, path)
);

CREATE INDEX IF NOT EXISTS idx_files_size ON files(size);
CREATE INDEX IF NOT EXISTS idx_files_md5 ON files(md5);
CREATE INDEX IF NOT EXISTS idx_files_scan_id ON files(scan_id);
"""


def md5_file(path: str) -> str | None:
    """Compute full MD5 of a file. Returns hex digest or None on error."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


class ScanDatabase:
    """SQLite-backed cache of scan results for deduplication."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self._db_path), check_same_thread=False, timeout=30,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def create_scan(self, source: str, root: str) -> str:
        """Create a new scan record and return its ID."""
        scan_id = uuid.uuid4().hex[:12]
        self._conn.execute(
            "INSERT INTO scans (id, source, root, timestamp) VALUES (?, ?, ?, ?)",
            (scan_id, source, root, time.time()),
        )
        self._conn.commit()
        return scan_id

    def finish_scan(self, scan_id: str, total_files: int, total_size: int) -> None:
        """Update scan metadata after completion."""
        self._conn.execute(
            "UPDATE scans SET total_files=?, total_size=? WHERE id=?",
            (total_files, total_size, scan_id),
        )
        self._conn.commit()

    def add_files(self, scan_id: str, files: list[dict]) -> None:
        """Bulk insert files for a scan.

        Each dict: source, path, name, size, md5, modified_time, mime_type, web_link
        """
        self._conn.executemany(
            """INSERT OR REPLACE INTO files
               (scan_id, source, path, name, size, md5,
                modified_time, mime_type, web_link)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    scan_id,
                    f.get("source", ""),
                    f.get("path", ""),
                    f.get("name", ""),
                    f.get("size", 0),
                    f.get("md5"),
                    f.get("modified_time"),
                    f.get("mime_type"),
                    f.get("web_link"),
                )
                for f in files
            ],
        )
        self._conn.commit()

    def delete_scan(self, scan_id: str) -> None:
        """Delete a scan and all its files."""
        self._conn.execute("DELETE FROM files WHERE scan_id=?", (scan_id,))
        self._conn.execute("DELETE FROM scans WHERE id=?", (scan_id,))
        self._conn.commit()

    def get_checksum_cache(self, source: str, root: str) -> dict[tuple[str, int, str], str]:
        """Return a mapping of (path, size, modified_time) -> md5 for existing scans.

        Used to carry forward checksums for unchanged files across rescans.
        """
        rows = self._conn.execute(
            """SELECT f.path, f.size, f.modified_time, f.md5
               FROM files f
               JOIN scans s ON f.scan_id = s.id
               WHERE s.source = ? AND s.root = ? AND f.md5 IS NOT NULL""",
            (source, root),
        ).fetchall()
        return {
            (r["path"], r["size"], r["modified_time"] or ""): r["md5"]
            for r in rows
        }

    def delete_scans_for_source(self, source: str, root: str) -> None:
        """Delete previous scans for the same source+root."""
        rows = self._conn.execute(
            "SELECT id FROM scans WHERE source=? AND root=?",
            (source, root),
        ).fetchall()
        for row in rows:
            self.delete_scan(row["id"])

    def list_scans(self) -> list[dict]:
        """List all scans."""
        rows = self._conn.execute(
            "SELECT * FROM scans ORDER BY timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def compute_missing_checksums(
        self,
        *,
        workers: int = 8,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Compute MD5 for local files that are dedup candidates but lack checksums.

        Only hashes files whose size matches at least one other file in the DB.
        Returns the number of files checksummed.
        """
        # Find sizes that appear more than once across all files
        candidate_rows = self._conn.execute(
            """SELECT DISTINCT f1.id, f1.path
               FROM files f1
               WHERE f1.md5 IS NULL
                 AND f1.source = 'local'
                 AND f1.size IN (
                     SELECT size FROM files
                     GROUP BY size HAVING COUNT(*) > 1
                 )"""
        ).fetchall()

        if not candidate_rows:
            return 0

        total = len(candidate_rows)
        done = 0

        def _hash_one(file_id: int, path: str) -> tuple[int, str | None]:
            return file_id, md5_file(path)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_hash_one, row["id"], row["path"]): row["id"]
                for row in candidate_rows
            }
            for fut in as_completed(futures):
                file_id, md5 = fut.result()
                if md5:
                    self._conn.execute(
                        "UPDATE files SET md5=? WHERE id=?", (md5, file_id)
                    )
                done += 1
                if progress_callback and done % 100 == 0:
                    progress_callback(done, total)

        self._conn.commit()
        if progress_callback:
            progress_callback(done, total)
        return done

    def find_duplicates(self, min_size: int = 1024) -> dict:
        """Find all duplicates across all sources using MD5.

        Groups files that share the same MD5 checksum regardless of source.
        Returns groups sorted by size descending, plus summary stats.
        """
        rows = self._conn.execute(
            """SELECT md5, size, GROUP_CONCAT(id) as file_ids, COUNT(*) as cnt
               FROM files
               WHERE md5 IS NOT NULL AND size >= ?
               GROUP BY md5
               HAVING COUNT(*) > 1
               ORDER BY size DESC
               LIMIT 200""",
            (min_size,),
        ).fetchall()

        groups = []
        total_savings = 0
        for row in rows:
            file_ids = row["file_ids"].split(",")
            file_rows = self._conn.execute(
                f"SELECT * FROM files WHERE id IN ({','.join('?' * len(file_ids))})",
                file_ids,
            ).fetchall()

            sources = set()
            file_list = []
            for fr in file_rows:
                d = dict(fr)
                d["size_human"] = human_size(d["size"])
                sources.add(d["source"])
                file_list.append(d)

            savings = row["size"] * (len(file_list) - 1)
            total_savings += savings

            groups.append({
                "md5": row["md5"],
                "size": row["size"],
                "size_human": human_size(row["size"]),
                "count": len(file_list),
                "cross_source": len(sources) > 1,
                "sources": sorted(sources),
                "savings": savings,
                "savings_human": human_size(savings),
                "files": file_list,
            })

        scans = self.list_scans()

        return {
            "scans": scans,
            "groups": groups,
            "group_count": len(groups),
            "total_savings": total_savings,
            "total_savings_human": human_size(total_savings),
        }

    def get_stats(self) -> dict:
        """Get summary statistics about cached data."""
        scan_count = self._conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
        file_count = self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        checksummed = self._conn.execute(
            "SELECT COUNT(*) FROM files WHERE md5 IS NOT NULL"
        ).fetchone()[0]
        total_size = self._conn.execute(
            "SELECT COALESCE(SUM(size), 0) FROM files"
        ).fetchone()[0]
        sources = self._conn.execute(
            "SELECT DISTINCT source FROM scans"
        ).fetchall()
        return {
            "scan_count": scan_count,
            "file_count": file_count,
            "checksummed": checksummed,
            "total_size": total_size,
            "total_size_human": human_size(total_size),
            "sources": [r["source"] for r in sources],
        }
