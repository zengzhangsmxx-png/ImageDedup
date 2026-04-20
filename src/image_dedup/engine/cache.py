"""SQLite hash cache — avoids recomputing hashes for unchanged files."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..logging_setup import get_logger

logger = get_logger("cache")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hash_cache (
    file_path   TEXT NOT NULL,
    file_size   INTEGER NOT NULL,
    mtime       REAL NOT NULL,
    md5         TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    phash       TEXT NOT NULL,
    dhash       TEXT NOT NULL,
    ahash       TEXT NOT NULL,
    phash_top   TEXT NOT NULL DEFAULT '',
    width       INTEGER,
    height      INTEGER,
    computed_at REAL NOT NULL,
    PRIMARY KEY (file_path, file_size, mtime)
);
CREATE INDEX IF NOT EXISTS idx_md5 ON hash_cache(md5);
CREATE INDEX IF NOT EXISTS idx_phash ON hash_cache(phash);
"""

_SCAN_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_history (
    scan_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   REAL NOT NULL,
    finished_at  REAL,
    source_paths TEXT NOT NULL,
    total_files  INTEGER DEFAULT 0,
    total_groups INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_files (
    scan_id    INTEGER NOT NULL,
    file_path  TEXT NOT NULL,
    file_size  INTEGER NOT NULL,
    mtime      REAL NOT NULL,
    PRIMARY KEY (scan_id, file_path)
);
CREATE INDEX IF NOT EXISTS idx_scan_files_path ON scan_files(file_path);

CREATE TABLE IF NOT EXISTS scan_progress (
    progress_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    source_paths  TEXT NOT NULL,
    started_at    REAL NOT NULL,
    last_file_idx INTEGER NOT NULL DEFAULT 0,
    total_files   INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'running'
);
"""


class HashCache:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            cache_dir = Path.home() / ".cache" / "image_dedup"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = cache_dir / "cache.db"
        self._db_path = str(db_path)
        self._local = threading.local()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn = conn
        return conn

    def _init_db(self):
        conn = self._conn()
        conn.executescript(_SCHEMA)
        # Migrate: add phash_top column if missing (old databases)
        try:
            conn.execute("SELECT phash_top FROM hash_cache LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE hash_cache ADD COLUMN phash_top TEXT NOT NULL DEFAULT ''")
        # Migrate: add scan_history tables if missing
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scan_history'"
        ).fetchone()
        if tables is None:
            conn.executescript(_SCAN_HISTORY_SCHEMA)
        # Migrate: add scan_progress table if missing
        progress_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scan_progress'"
        ).fetchone()
        if progress_table is None:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS scan_progress ("
                "    progress_id   INTEGER PRIMARY KEY AUTOINCREMENT,"
                "    source_paths  TEXT NOT NULL,"
                "    started_at    REAL NOT NULL,"
                "    last_file_idx INTEGER NOT NULL DEFAULT 0,"
                "    total_files   INTEGER NOT NULL DEFAULT 0,"
                "    status        TEXT NOT NULL DEFAULT 'running'"
                ")"
            )
        conn.commit()
        # Cleanup old scans on startup
        self._cleanup_old_scans()

    def get(self, file_path: str, file_size: int, mtime: float) -> dict | None:
        row = self._conn().execute(
            "SELECT md5, sha256, phash, dhash, ahash, phash_top, width, height, computed_at "
            "FROM hash_cache WHERE file_path=? AND file_size=? AND mtime=?",
            (file_path, file_size, mtime),
        ).fetchone()
        if row is None:
            return None
        return dict(
            md5=row[0], sha256=row[1], phash=row[2], dhash=row[3],
            ahash=row[4], phash_top=row[5], width=row[6], height=row[7], computed_at=row[8],
        )

    def put(self, file_path: str, file_size: int, mtime: float, hashes: dict):
        self._conn().execute(
            "INSERT OR REPLACE INTO hash_cache "
            "(file_path, file_size, mtime, md5, sha256, phash, dhash, ahash, phash_top, width, height, computed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (file_path, file_size, mtime,
             hashes["md5"], hashes["sha256"], hashes["phash"],
             hashes["dhash"], hashes["ahash"], hashes.get("phash_top", ""),
             hashes["width"], hashes["height"], hashes["computed_at"]),
        )
        self._conn().commit()

    def put_batch(self, items: list[tuple[str, int, float, dict]]):
        conn = self._conn()
        conn.executemany(
            "INSERT OR REPLACE INTO hash_cache "
            "(file_path, file_size, mtime, md5, sha256, phash, dhash, ahash, phash_top, width, height, computed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (fp, fs, mt, h["md5"], h["sha256"], h["phash"],
                 h["dhash"], h["ahash"], h.get("phash_top", ""),
                 h["width"], h["height"], h["computed_at"])
                for fp, fs, mt, h in items
            ],
        )
        conn.commit()

    def get_batch(self, keys: list[tuple[str, int, float]]) -> dict[str, dict]:
        if not keys:
            return {}
        conn = self._conn()
        results = {}
        chunk_size = 300
        for i in range(0, len(keys), chunk_size):
            chunk = keys[i:i + chunk_size]
            placeholders = ",".join(["(?,?,?)"] * len(chunk))
            params: list = []
            for fp, fs, mt in chunk:
                params.extend([fp, fs, mt])
            rows = conn.execute(
                "SELECT file_path, md5, sha256, phash, dhash, ahash, phash_top, width, height, computed_at "
                f"FROM hash_cache WHERE (file_path, file_size, mtime) IN ({placeholders})",
                params,
            ).fetchall()
            for row in rows:
                results[row[0]] = dict(
                    md5=row[1], sha256=row[2], phash=row[3], dhash=row[4],
                    ahash=row[5], phash_top=row[6], width=row[7], height=row[8], computed_at=row[9],
                )
        return results

    def clear(self):
        self._conn().execute("DELETE FROM hash_cache")
        self._conn().commit()

    def count(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM hash_cache").fetchone()[0]

    # --- Scan history ---

    def start_scan(self, source_paths: list[str]) -> int:
        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO scan_history (started_at, source_paths) VALUES (?, ?)",
            (time.time(), json.dumps(source_paths, ensure_ascii=False)),
        )
        conn.commit()
        return cur.lastrowid

    def record_scan_files_batch(self, scan_id: int, files: list[tuple[str, int, float]]) -> None:
        conn = self._conn()
        conn.executemany(
            "INSERT OR REPLACE INTO scan_files (scan_id, file_path, file_size, mtime) VALUES (?,?,?,?)",
            [(scan_id, fp, fs, mt) for fp, fs, mt in files],
        )
        conn.commit()

    def finish_scan(self, scan_id: int, total_files: int, total_groups: int) -> None:
        conn = self._conn()
        conn.execute(
            "UPDATE scan_history SET finished_at=?, total_files=?, total_groups=? WHERE scan_id=?",
            (time.time(), total_files, total_groups, scan_id),
        )
        conn.commit()

    def get_last_scan(self, source_paths: list[str]) -> dict | None:
        key = json.dumps(source_paths, ensure_ascii=False)
        row = self._conn().execute(
            "SELECT scan_id, started_at, finished_at, total_files, total_groups "
            "FROM scan_history WHERE source_paths=? AND finished_at IS NOT NULL "
            "ORDER BY scan_id DESC LIMIT 1",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return dict(scan_id=row[0], started_at=row[1], finished_at=row[2],
                    total_files=row[3], total_groups=row[4])

    def get_scan_delta(self, scan_id: int, current_files: list[tuple[str, int, float]]) -> tuple[list, list, list]:
        """Compare current file list against previous scan.
        Returns (new_files, modified_files, deleted_files)."""
        prev = {}
        for row in self._conn().execute(
            "SELECT file_path, file_size, mtime FROM scan_files WHERE scan_id=?", (scan_id,),
        ).fetchall():
            prev[row[0]] = (row[1], row[2])

        new_files = []
        modified_files = []
        current_paths = set()
        for fp, fs, mt in current_files:
            current_paths.add(fp)
            if fp not in prev:
                new_files.append(fp)
            elif prev[fp] != (fs, mt):
                modified_files.append(fp)

        deleted_files = [fp for fp in prev if fp not in current_paths]
        return new_files, modified_files, deleted_files

    def _cleanup_old_scans(self, days: int = 30) -> None:
        try:
            cutoff = time.time() - days * 86400
            conn = self._conn()
            old_ids = [r[0] for r in conn.execute(
                "SELECT scan_id FROM scan_history WHERE started_at < ?", (cutoff,),
            ).fetchall()]
            if old_ids:
                placeholders = ",".join("?" * len(old_ids))
                conn.execute(f"DELETE FROM scan_files WHERE scan_id IN ({placeholders})", old_ids)
                conn.execute(f"DELETE FROM scan_history WHERE scan_id IN ({placeholders})", old_ids)
                conn.commit()
                logger.info("Cleaned up %d old scan records", len(old_ids))
        except Exception as e:
            logger.debug("Scan cleanup: %s", e)

    # --- Scan progress (resume support) ---

    def save_scan_progress(self, source_paths: list[str], file_idx: int, total: int) -> None:
        """Upsert progress for given source paths. Creates a new row if none
        exists with status='running', otherwise updates the existing one."""
        key = json.dumps(source_paths, ensure_ascii=False)
        conn = self._conn()
        row = conn.execute(
            "SELECT progress_id FROM scan_progress "
            "WHERE source_paths=? AND status='running' "
            "ORDER BY progress_id DESC LIMIT 1",
            (key,),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE scan_progress SET last_file_idx=?, total_files=? "
                "WHERE progress_id=?",
                (file_idx, total, row[0]),
            )
        else:
            conn.execute(
                "INSERT INTO scan_progress (source_paths, started_at, last_file_idx, total_files, status) "
                "VALUES (?, ?, ?, ?, 'running')",
                (key, time.time(), file_idx, total),
            )
        conn.commit()

    def get_interrupted_scan(self, source_paths: list[str]) -> dict | None:
        """Return the last interrupted (status='running') progress record
        for the given source paths, or None if there is no interrupted scan."""
        key = json.dumps(source_paths, ensure_ascii=False)
        row = self._conn().execute(
            "SELECT progress_id, started_at, last_file_idx, total_files "
            "FROM scan_progress "
            "WHERE source_paths=? AND status='running' "
            "ORDER BY progress_id DESC LIMIT 1",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return dict(
            progress_id=row[0], started_at=row[1],
            last_file_idx=row[2], total_files=row[3],
        )

    def clear_scan_progress(self, source_paths: list[str]) -> None:
        """Mark the running progress record for the given source paths as
        completed. If no running record exists this is a no-op."""
        key = json.dumps(source_paths, ensure_ascii=False)
        conn = self._conn()
        conn.execute(
            "UPDATE scan_progress SET status='completed' "
            "WHERE source_paths=? AND status='running'",
            (key,),
        )
        conn.commit()
