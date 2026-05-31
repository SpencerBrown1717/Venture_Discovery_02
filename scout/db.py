"""SQLite storage layer.

A single-file database keeps the project zero-dependency and trivially portable,
while still giving us indexed queries, upserts, and a real schema. Swapping this
for Postgres later only requires reimplementing this module's interface.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .models import Company

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_id       TEXT,
    jurisdiction    TEXT,
    formation_date  TEXT,
    discovered_date TEXT,
    website         TEXT,
    website_verified INTEGER DEFAULT 0,
    verified_real   INTEGER DEFAULT 0,
    verification    TEXT,
    description     TEXT,
    ai_score        REAL DEFAULT 0,
    is_ai           INTEGER DEFAULT 0,
    ai_signals      TEXT,
    ai_category     TEXT,
    memo            TEXT,
    founders        TEXT,
    scores          TEXT,
    competitive     TEXT,
    recommendation  TEXT,
    raw             TEXT,
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_companies_score ON companies(ai_score);
CREATE INDEX IF NOT EXISTS idx_companies_formation ON companies(formation_date);
CREATE INDEX IF NOT EXISTS idx_companies_source ON companies(source);
"""


class Database:
    def __init__(self, path: str | Path = "scout.db") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add columns introduced after a DB was first created (idempotent)."""
        existing = {r["name"] for r in self._conn.execute("PRAGMA table_info(companies)")}
        int_cols = {"website_verified", "verified_real"}
        for col in ("memo", "founders", "scores", "competitive", "recommendation",
                    "website_verified", "verified_real", "verification"):
            if col not in existing:
                typ = "INTEGER DEFAULT 0" if col in int_cols else "TEXT"
                self._conn.execute(f"ALTER TABLE companies ADD COLUMN {col} {typ}")

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def upsert(self, company: Company) -> bool:
        """Insert or update a company. Returns True if it was newly inserted."""
        row = company.to_row()
        existing = self._conn.execute(
            "SELECT id FROM companies WHERE id = ?", (company.id,)
        ).fetchone()
        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")
        sql = (
            f"INSERT INTO companies ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}, updated_at=datetime('now')"
        )
        with self._tx() as conn:
            conn.execute(sql, [row[c] for c in cols])
        return existing is None

    def upsert_many(self, companies: Iterable[Company]) -> tuple[int, int]:
        inserted = updated = 0
        for c in companies:
            if self.upsert(c):
                inserted += 1
            else:
                updated += 1
        return inserted, updated

    def get(self, company_id: str) -> Optional[Company]:
        row = self._conn.execute(
            "SELECT * FROM companies WHERE id = ?", (company_id,)
        ).fetchone()
        return Company.from_row(dict(row)) if row else None

    def all(self, min_score: float = 0.0, ai_only: bool = False) -> list[Company]:
        sql = "SELECT * FROM companies WHERE ai_score >= ?"
        params: list = [min_score]
        if ai_only:
            sql += " AND is_ai = 1"
        sql += " ORDER BY ai_score DESC, formation_date DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [Company.from_row(dict(r)) for r in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]

    def stats(self) -> dict:
        cur = self._conn.execute(
            "SELECT COUNT(*) total, "
            "SUM(is_ai) ai_total, "
            "AVG(ai_score) avg_score "
            "FROM companies"
        ).fetchone()
        return {
            "total": cur["total"] or 0,
            "ai_total": cur["ai_total"] or 0,
            "avg_score": round(cur["avg_score"] or 0.0, 3),
        }
