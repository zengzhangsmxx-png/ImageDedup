"""SQLite hash cache — avoids recomputing hashes for unchanged files."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

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
        conn.commit()

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
