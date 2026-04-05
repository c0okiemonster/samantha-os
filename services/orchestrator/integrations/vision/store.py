"""SQLite data layer for vision observations. Pure, sync, no HTTP."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .models import Observation


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_description TEXT NOT NULL,
    spoken_text     TEXT NOT NULL,
    user_trigger    TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_observations_time
    ON observations(created_at DESC) WHERE deleted_at IS NULL;
"""


def _parse(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(s.replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_observation(row: sqlite3.Row) -> Observation:
    return Observation(
        id=row["id"],
        raw_description=row["raw_description"],
        spoken_text=row["spoken_text"],
        user_trigger=row["user_trigger"],
        created_at=_parse(row["created_at"]),
        deleted_at=_parse(row["deleted_at"]),
    )


class VisionStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def create_observation(
        self,
        raw_description: str,
        spoken_text: str,
        user_trigger: Optional[str],
    ) -> Observation:
        cur = self.conn.execute(
            "INSERT INTO observations (raw_description, spoken_text, user_trigger) "
            "VALUES (?, ?, ?)",
            (raw_description, spoken_text, user_trigger),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM observations WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_observation(row)

    def list_recent(self, limit: int = 10) -> list[Observation]:
        rows = self.conn.execute(
            "SELECT * FROM observations "
            "WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_observation(r) for r in rows]

    def search_by_text(self, query: str) -> Optional[Observation]:
        """Find the most recent observation whose raw_description contains `query`.
        If query is empty, return the most recent observation regardless."""
        q = (query or "").strip().lower()
        if q:
            row = self.conn.execute(
                "SELECT * FROM observations "
                "WHERE deleted_at IS NULL "
                "AND LOWER(raw_description) LIKE ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (f"%{q}%",),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM observations "
                "WHERE deleted_at IS NULL "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return _row_to_observation(row) if row else None

    def soft_delete(self, observation_id: int) -> None:
        self.conn.execute(
            "UPDATE observations SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (observation_id,),
        )
        self.conn.commit()
