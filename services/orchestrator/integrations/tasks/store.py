"""SQLite data layer for the tasks integration. Pure, sync, no HTTP."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import ListItem, Recurrence, Reminder, ScheduleEvent


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reminders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    text          TEXT NOT NULL,
    trigger_at    TIMESTAMP NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fired_at      TIMESTAMP,
    cancelled_at  TIMESTAMP,
    entity_id     INTEGER,
    source_text   TEXT
);
CREATE INDEX IF NOT EXISTS idx_reminders_due
    ON reminders(trigger_at) WHERE fired_at IS NULL AND cancelled_at IS NULL;

CREATE TABLE IF NOT EXISTS schedule_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT NOT NULL,
    start_at            TIMESTAMP NOT NULL,
    duration_min        INTEGER,
    recurrence          TEXT,
    notes               TEXT,
    entity_id           INTEGER,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    heads_up_fired_at   TIMESTAMP,
    fired_at            TIMESTAMP,
    cancelled_at        TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_schedule_due
    ON schedule_events(start_at) WHERE cancelled_at IS NULL;

CREATE TABLE IF NOT EXISTS list_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_name   TEXT NOT NULL,
    text        TEXT NOT NULL,
    added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    done_at     TIMESTAMP,
    position    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_list_active
    ON list_items(list_name, position) WHERE done_at IS NULL;
"""


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


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


def _row_to_reminder(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        text=row["text"],
        trigger_at=_parse(row["trigger_at"]),
        created_at=_parse(row["created_at"]),
        fired_at=_parse(row["fired_at"]),
        cancelled_at=_parse(row["cancelled_at"]),
        entity_id=row["entity_id"],
        source_text=row["source_text"],
    )


def _row_to_list_item(row: sqlite3.Row) -> ListItem:
    return ListItem(
        id=row["id"],
        list_name=row["list_name"],
        text=row["text"],
        added_at=_parse(row["added_at"]),
        done_at=_parse(row["done_at"]),
        position=row["position"] or 0,
    )


def _row_to_schedule_event(row: sqlite3.Row) -> ScheduleEvent:
    rec_str = row["recurrence"]
    recurrence = Recurrence(rec_str) if rec_str else None
    return ScheduleEvent(
        id=row["id"],
        title=row["title"],
        start_at=_parse(row["start_at"]),
        duration_min=row["duration_min"],
        recurrence=recurrence,
        notes=row["notes"],
        entity_id=row["entity_id"],
        created_at=_parse(row["created_at"]),
        heads_up_fired_at=_parse(row["heads_up_fired_at"]),
        fired_at=_parse(row["fired_at"]),
        cancelled_at=_parse(row["cancelled_at"]),
    )


class TasksStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    # ─── Reminders ──────────────────────────────────────────────────────

    def create_reminder(
        self,
        text: str,
        trigger_at: datetime,
        source_text: Optional[str] = None,
        entity_id: Optional[int] = None,
    ) -> Reminder:
        cur = self.conn.execute(
            "INSERT INTO reminders (text, trigger_at, source_text, entity_id) "
            "VALUES (?, ?, ?, ?)",
            (text, _iso(trigger_at), source_text, entity_id),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_reminder(row)

    def reminders_due(self, now: datetime) -> list[Reminder]:
        rows = self.conn.execute(
            "SELECT * FROM reminders "
            "WHERE trigger_at <= ? "
            "AND fired_at IS NULL "
            "AND cancelled_at IS NULL "
            "ORDER BY trigger_at ASC",
            (_iso(now),),
        ).fetchall()
        return [_row_to_reminder(r) for r in rows]

    def list_pending_reminders(self) -> list[Reminder]:
        rows = self.conn.execute(
            "SELECT * FROM reminders "
            "WHERE fired_at IS NULL AND cancelled_at IS NULL "
            "ORDER BY trigger_at ASC"
        ).fetchall()
        return [_row_to_reminder(r) for r in rows]

    def mark_reminder_fired(self, reminder_id: int, now: datetime) -> None:
        self.conn.execute(
            "UPDATE reminders SET fired_at = ? WHERE id = ?",
            (_iso(now), reminder_id),
        )
        self.conn.commit()

    def cancel_reminder(self, reminder_id: int, now: datetime) -> None:
        self.conn.execute(
            "UPDATE reminders SET cancelled_at = ? WHERE id = ?",
            (_iso(now), reminder_id),
        )
        self.conn.commit()

    def cancel_last_reminder(self, now: datetime) -> Optional[Reminder]:
        row = self.conn.execute(
            "SELECT * FROM reminders "
            "WHERE fired_at IS NULL AND cancelled_at IS NULL "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        self.conn.execute(
            "UPDATE reminders SET cancelled_at = ? WHERE id = ?",
            (_iso(now), row["id"]),
        )
        self.conn.commit()
        updated = self.conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (row["id"],)
        ).fetchone()
        return _row_to_reminder(updated)

    # ─── Schedule events ────────────────────────────────────────────────

    def create_schedule_event(
        self,
        title: str,
        start_at: datetime,
        duration_min: Optional[int] = None,
        recurrence: Optional[Recurrence] = None,
        notes: Optional[str] = None,
        entity_id: Optional[int] = None,
    ) -> ScheduleEvent:
        cur = self.conn.execute(
            "INSERT INTO schedule_events "
            "(title, start_at, duration_min, recurrence, notes, entity_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                title,
                _iso(start_at),
                duration_min,
                recurrence.kind if recurrence else None,
                notes,
                entity_id,
            ),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM schedule_events WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_schedule_event(row)

    def get_schedule_event(self, event_id: int) -> Optional[ScheduleEvent]:
        row = self.conn.execute(
            "SELECT * FROM schedule_events WHERE id = ?", (event_id,)
        ).fetchone()
        return _row_to_schedule_event(row) if row else None

    def schedule_due(self, now: datetime) -> list[ScheduleEvent]:
        rows = self.conn.execute(
            "SELECT * FROM schedule_events "
            "WHERE start_at <= ? "
            "AND fired_at IS NULL "
            "AND cancelled_at IS NULL "
            "ORDER BY start_at ASC",
            (_iso(now),),
        ).fetchall()
        return [_row_to_schedule_event(r) for r in rows]

    def schedule_heads_up_due(self, now: datetime, window_min: int) -> list[ScheduleEvent]:
        upper = now + timedelta(minutes=window_min)
        rows = self.conn.execute(
            "SELECT * FROM schedule_events "
            "WHERE start_at > ? "
            "AND start_at <= ? "
            "AND heads_up_fired_at IS NULL "
            "AND cancelled_at IS NULL "
            "ORDER BY start_at ASC",
            (_iso(now), _iso(upper)),
        ).fetchall()
        return [_row_to_schedule_event(r) for r in rows]

    def mark_heads_up_fired(self, event_id: int, now: datetime) -> None:
        self.conn.execute(
            "UPDATE schedule_events SET heads_up_fired_at = ? WHERE id = ?",
            (_iso(now), event_id),
        )
        self.conn.commit()

    def mark_schedule_fired(self, event_id: int, now: datetime) -> None:
        self.conn.execute(
            "UPDATE schedule_events SET fired_at = ? WHERE id = ?",
            (_iso(now), event_id),
        )
        self.conn.commit()

    # ─── Lists ──────────────────────────────────────────────────────────

    def add_list_item(self, list_name: str, text: str) -> ListItem:
        # Next position = max(position) + 1 among active items in this list
        row = self.conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next_pos "
            "FROM list_items WHERE list_name = ?",
            (list_name,),
        ).fetchone()
        next_pos = row["next_pos"]
        cur = self.conn.execute(
            "INSERT INTO list_items (list_name, text, position) VALUES (?, ?, ?)",
            (list_name, text, next_pos),
        )
        self.conn.commit()
        inserted = self.conn.execute(
            "SELECT * FROM list_items WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_list_item(inserted)

    def get_list(self, list_name: str) -> list[ListItem]:
        rows = self.conn.execute(
            "SELECT * FROM list_items "
            "WHERE list_name = ? AND done_at IS NULL "
            "ORDER BY position ASC, id ASC",
            (list_name,),
        ).fetchall()
        return [_row_to_list_item(r) for r in rows]

    def is_duplicate(self, list_name: str, text: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM list_items "
            "WHERE list_name = ? AND LOWER(text) = LOWER(?) AND done_at IS NULL "
            "LIMIT 1",
            (list_name, text),
        ).fetchone()
        return row is not None

    def mark_list_item_done(self, item_id: int) -> None:
        self.conn.execute(
            "UPDATE list_items SET done_at = CURRENT_TIMESTAMP WHERE id = ?",
            (item_id,),
        )
        self.conn.commit()

    def advance_recurrence(self, event_id: int, now: datetime) -> None:
        """Compute the next occurrence strictly after `now`, write it,
        and reset fired flags so the next cycle fires again."""
        row = self.conn.execute(
            "SELECT * FROM schedule_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return
        event = _row_to_schedule_event(row)
        if not event.recurrence:
            return
        next_start = _next_occurrence(event.start_at, event.recurrence, now)
        self.conn.execute(
            "UPDATE schedule_events "
            "SET start_at = ?, fired_at = NULL, heads_up_fired_at = NULL "
            "WHERE id = ?",
            (_iso(next_start), event_id),
        )
        self.conn.commit()


# Weekday names → Python weekday() int (Mon=0..Sun=6)
_WEEKLY_DAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


def _next_occurrence(current: datetime, recurrence: Recurrence, now: datetime) -> datetime:
    """Advance `current` forward by recurrence rules until strictly > now."""
    candidate = current
    while True:
        candidate = _step(candidate, recurrence)
        if candidate > now:
            return candidate


def _step(dt: datetime, recurrence: Recurrence) -> datetime:
    kind = recurrence.kind
    if kind == "daily":
        return dt + timedelta(days=1)
    if kind == "weekdays":
        nxt = dt + timedelta(days=1)
        while nxt.weekday() >= 5:  # Sat=5, Sun=6
            nxt += timedelta(days=1)
        return nxt
    if kind.startswith("weekly:"):
        return dt + timedelta(days=7)
    raise ValueError(f"Unknown recurrence kind: {kind}")
