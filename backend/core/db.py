"""SQLite (WAL) и миграции."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.RLock()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn().execute(sql, tuple(params))

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        row = self.execute(sql, params).fetchone()
        return dict(row) if row else None

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        return [dict(r) for r in self.execute(sql, params).fetchall()]

    def insert(self, table: str, values: dict) -> int:
        cols = ",".join(values)
        qs = ",".join("?" for _ in values)
        cur = self.execute(f"INSERT INTO {table} ({cols}) VALUES ({qs})", list(values.values()))
        return int(cur.lastrowid)

    def transaction(self):
        return _Tx(self)

    def journal_mode(self) -> str:
        return self.execute("PRAGMA journal_mode").fetchone()[0]

    def migrate(self) -> list[str]:
        applied: list[str] = []
        with self._lock:
            c = self.conn()
            c.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
            )
            done = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
            for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if f.stem in done:
                    continue
                c.execute("BEGIN")
                try:
                    for stmt in _split_sql(f.read_text(encoding="utf-8")):
                        c.execute(stmt)
                    c.execute("INSERT INTO schema_migrations(version) VALUES (?)", (f.stem,))
                    c.execute("COMMIT")
                except Exception:
                    c.execute("ROLLBACK")
                    raise
                applied.append(f.stem)
        return applied

    def backup(self, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest))
        with self._lock:
            self.conn().backup(target)
        target.close()
        verify_backup(dest)
        return dest


def verify_backup(path: Path) -> None:
    c = sqlite3.connect(str(path))
    try:
        res = c.execute("PRAGMA integrity_check").fetchone()[0]
        if res != "ok":
            raise RuntimeError(f"Резервная копия повреждена: {res}")
        c.execute("SELECT count(*) FROM schema_migrations").fetchone()
    finally:
        c.close()


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db.conn().execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db.conn().execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()
        return False


def _split_sql(text: str) -> list[str]:
    return [s.strip() for s in text.split(";\n") if s.strip() and not all(
        l.strip().startswith("--") or not l.strip() for l in s.strip().splitlines())]


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, sort_keys=True)


def loads(v: str | None, default: Any = None) -> Any:
    if not v:
        return default
    return json.loads(v)
