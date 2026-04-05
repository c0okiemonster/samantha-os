# Reminders, Schedules & Lists — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Samantha reminders, schedule events (including simple recurring), and user-named lists, plus the background scheduler + overlay-card UI that surfaces them.

**Architecture:** New `TasksIntegration` under `services/orchestrator/integrations/tasks/` with pure `store.py` (SQLite CRUD), `parser.py` (time + recurrence), `scheduler.py` (asyncio loop), and a thin `__init__.py` adapter implementing the existing `BaseIntegration` contract. Scheduler broadcasts `overlay_card` WebSocket events; the visual shell renders a translucent right-side card with a soft chime served by the orchestrator. Legacy reminder code in `NotesIntegration` is removed cleanly.

**Tech Stack:** Python 3 + FastAPI (existing), `sqlite3` stdlib, `dateparser` (new dep), `freezegun` (new test dep), `pytest` (new test dep), stdlib `wave` + numpy for chime synthesis, vanilla JS + Web Audio API on the visual shell.

**Spec:** `docs/superpowers/specs/2026-04-05-reminders-schedules-lists-design.md`

**Spec adjustment during planning:** WebSocket dispatch key is `event`, not `type`, to match existing broadcast format in `services/orchestrator/main.py`. Visual shell dispatch lives in `handleEvt(d)` on `d.event`. All envelopes in this plan use `event: "overlay_card"`.

---

## Conventions

- **Test runner:** `pytest` from `services/orchestrator/` with `PYTHONPATH=.` so imports match how `main.py` runs (`from integrations import ...`, `from integrations.tasks.store import ...`).
- **Every test file lives at** `services/orchestrator/tests/<area>/test_<thing>.py`.
- **All timestamps in storage are UTC** (`datetime.now(timezone.utc)`). Display formatting applies local tz only when rendering.
- **Timezone for tests:** `TZ=UTC` env var in the test command. Parser default stays `Europe/Stockholm` in production (from `TZ` env var with that fallback).
- **Commits:** Conventional prefixes — `feat:`, `fix:`, `test:`, `chore:`. Commit after every passing test cycle.

---

## File Structure

**Create:**

```
services/orchestrator/integrations/tasks/__init__.py        TasksIntegration adapter
services/orchestrator/integrations/tasks/store.py           SQLite CRUD (reminders, schedule, lists)
services/orchestrator/integrations/tasks/parser.py          dateparser + recurrence grammar
services/orchestrator/integrations/tasks/scheduler.py       async loop
services/orchestrator/integrations/tasks/chime.py           WAV synth
services/orchestrator/integrations/tasks/models.py          dataclasses: Reminder, ScheduleEvent, ListItem, Recurrence, OverlayPayload, TaskActionResult, ParseError
services/orchestrator/static/.gitkeep                        directory for generated chime
services/orchestrator/tests/__init__.py
services/orchestrator/tests/conftest.py
services/orchestrator/tests/tasks/__init__.py
services/orchestrator/tests/tasks/test_store_reminders.py
services/orchestrator/tests/tasks/test_store_schedule.py
services/orchestrator/tests/tasks/test_store_lists.py
services/orchestrator/tests/tasks/test_parser_time.py
services/orchestrator/tests/tasks/test_parser_recurrence.py
services/orchestrator/tests/tasks/test_scheduler.py
services/orchestrator/tests/tasks/test_integration.py
services/orchestrator/tests/tasks/test_chime.py
services/orchestrator/tests/tasks/test_smoke_e2e.py
```

**Modify:**

```
services/orchestrator/requirements.txt                      +dateparser, +pytest, +freezegun, +pytest-asyncio
services/orchestrator/integrations/notes_integration.py     remove reminder code
services/orchestrator/memory/__init__.py                    drop legacy reminders, create new 3 tables
services/orchestrator/intents/__init__.py                   (no changes — Tasks uses existing keyword/example mechanism via IntegrationAction registration)
services/orchestrator/main.py                               register TasksIntegration, mount /static, launch scheduler, extend /reset-all
services/visual-shell/index.html                            header polish + overlay card component + chime + WS handler
```

---

## Task 0: Bootstrap pytest harness

**Files:**
- Create: `services/orchestrator/tests/__init__.py`
- Create: `services/orchestrator/tests/conftest.py`
- Create: `services/orchestrator/tests/tasks/__init__.py`
- Modify: `services/orchestrator/requirements.txt`

No production code lives without a testable harness. This task exists because there is no pytest setup yet.

- [ ] **Step 1: Add test dependencies**

Edit `services/orchestrator/requirements.txt`, append:

```
dateparser==1.2.0
pytest==8.3.4
pytest-asyncio==0.25.0
freezegun==1.5.1
```

- [ ] **Step 2: Install deps**

Run: `cd services/orchestrator && pip install -r requirements.txt`
Expected: all four packages install cleanly.

- [ ] **Step 3: Create empty test package markers**

Create `services/orchestrator/tests/__init__.py` with content: (empty file)
Create `services/orchestrator/tests/tasks/__init__.py` with content: (empty file)

- [ ] **Step 4: Create conftest**

Create `services/orchestrator/tests/conftest.py`:

```python
"""Shared pytest fixtures for orchestrator tests."""
import os
import sqlite3
import pytest

# Force UTC for deterministic time tests.
os.environ.setdefault("TZ", "UTC")


@pytest.fixture
def memory_db():
    """In-memory sqlite connection with row factory, for store tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF")
    yield conn
    conn.close()
```

- [ ] **Step 5: Create a sanity test**

Create `services/orchestrator/tests/tasks/test_sanity.py`:

```python
def test_pytest_runs():
    assert 1 + 1 == 2
```

- [ ] **Step 6: Run it**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_sanity.py -v`
Expected: `1 passed`.

- [ ] **Step 7: Commit**

```bash
git add services/orchestrator/requirements.txt \
        services/orchestrator/tests/__init__.py \
        services/orchestrator/tests/conftest.py \
        services/orchestrator/tests/tasks/__init__.py \
        services/orchestrator/tests/tasks/test_sanity.py
git commit -m "chore: add pytest harness for orchestrator tests"
```

---

## Task 1: Models (dataclasses)

**Files:**
- Create: `services/orchestrator/integrations/tasks/__init__.py` (empty package marker for now)
- Create: `services/orchestrator/integrations/tasks/models.py`
- Create: `services/orchestrator/tests/tasks/test_models.py`

Defined up front so every later file imports a single source of truth.

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_models.py`:

```python
from datetime import datetime, timezone

from integrations.tasks.models import (
    Reminder,
    ScheduleEvent,
    ListItem,
    Recurrence,
    OverlayPayload,
    TaskActionResult,
    ParseError,
)


def test_reminder_defaults():
    r = Reminder(id=None, text="call mom", trigger_at=datetime(2026, 4, 5, 17, 0, tzinfo=timezone.utc))
    assert r.text == "call mom"
    assert r.fired_at is None
    assert r.cancelled_at is None
    assert r.entity_id is None


def test_schedule_event_recurrence_optional():
    e = ScheduleEvent(id=None, title="Meeting", start_at=datetime(2026, 4, 10, 15, 0, tzinfo=timezone.utc))
    assert e.recurrence is None
    assert e.duration_min is None


def test_recurrence_parse():
    assert Recurrence("daily").kind == "daily"
    assert Recurrence("weekly:mon").kind == "weekly:mon"


def test_overlay_payload_defaults():
    p = OverlayPayload(kind="reminder", title="Call mom", chime=True)
    assert p.duration_ms == 25000
    assert p.items is None


def test_task_action_result_holds_both():
    p = OverlayPayload(kind="reminder", title="X", chime=True)
    r = TaskActionResult(spoken="ok", overlay=p)
    assert r.spoken == "ok"
    assert r.overlay is p


def test_parse_error_is_exception():
    assert issubclass(ParseError, Exception)
```

- [ ] **Step 2: Run it — expect import failure**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_models.py -v`
Expected: collection error, `ModuleNotFoundError: No module named 'integrations.tasks'`.

- [ ] **Step 3: Create empty package marker**

Create `services/orchestrator/integrations/tasks/__init__.py` with content: (empty file)

- [ ] **Step 4: Write the models**

Create `services/orchestrator/integrations/tasks/models.py`:

```python
"""Dataclasses used across the tasks integration. Pure data, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


class ParseError(Exception):
    """Raised when parser.py cannot extract a time or content."""


RecurrenceKind = Literal[
    "daily",
    "weekdays",
    "weekly:mon", "weekly:tue", "weekly:wed", "weekly:thu",
    "weekly:fri", "weekly:sat", "weekly:sun",
]


@dataclass(frozen=True)
class Recurrence:
    kind: RecurrenceKind


@dataclass
class Reminder:
    id: Optional[int]
    text: str
    trigger_at: datetime                 # UTC
    created_at: Optional[datetime] = None
    fired_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    entity_id: Optional[int] = None
    source_text: Optional[str] = None


@dataclass
class ScheduleEvent:
    id: Optional[int]
    title: str
    start_at: datetime                   # UTC; next occurrence for recurring
    duration_min: Optional[int] = None
    recurrence: Optional[Recurrence] = None
    notes: Optional[str] = None
    entity_id: Optional[int] = None
    created_at: Optional[datetime] = None
    heads_up_fired_at: Optional[datetime] = None
    fired_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None


@dataclass
class ListItem:
    id: Optional[int]
    list_name: str
    text: str
    added_at: Optional[datetime] = None
    done_at: Optional[datetime] = None
    position: int = 0


@dataclass
class OverlayPayload:
    kind: Literal["reminder", "schedule", "schedule_heads_up", "list"]
    title: str
    chime: bool
    when: Optional[str] = None
    items: Optional[list[str]] = None
    highlight_index: Optional[int] = None
    list_name: Optional[str] = None
    duration_ms: int = 25000

    def to_envelope(self) -> dict:
        """Convert to the dict broadcast over the WebSocket."""
        return {
            "event": "overlay_card",
            "kind": self.kind,
            "title": self.title,
            "chime": self.chime,
            "when": self.when,
            "items": self.items,
            "highlight_index": self.highlight_index,
            "list_name": self.list_name,
            "duration_ms": self.duration_ms,
        }


@dataclass
class TaskActionResult:
    spoken: str
    overlay: Optional[OverlayPayload]
```

- [ ] **Step 5: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_models.py -v`
Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/integrations/tasks/__init__.py \
        services/orchestrator/integrations/tasks/models.py \
        services/orchestrator/tests/tasks/test_models.py
git commit -m "feat(tasks): add models for reminders, schedule, lists, and overlay payload"
```

---

## Task 2: Schema migration (legacy drop + new tables)

**Files:**
- Modify: `services/orchestrator/memory/__init__.py`
- Create: `services/orchestrator/tests/tasks/test_schema.py`

Drops legacy NotesIntegration `reminders` table, creates the three new tables.

- [ ] **Step 1: Inspect current schema creation**

Run: `grep -n "CREATE TABLE\|_create_tables\|def __init__\|executescript" services/orchestrator/memory/__init__.py | head -30`
Expected: find where memory tables are created (likely a `_create_tables` method or similar).

- [ ] **Step 2: Write the failing test**

Create `services/orchestrator/tests/tasks/test_schema.py`:

```python
"""Verify the memory module creates the new tasks tables and drops the legacy one."""
import sqlite3

from memory import Memory  # existing class


def _connect(tmp_path):
    db = tmp_path / "m.db"
    m = Memory(db_path=str(db))
    return m.conn


def test_new_tables_exist(tmp_path):
    conn = _connect(tmp_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "reminders" in names
    assert "schedule_events" in names
    assert "list_items" in names


def test_reminders_has_new_columns(tmp_path):
    conn = _connect(tmp_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reminders)").fetchall()}
    # New schema columns (not the legacy content/remind_at/completed):
    assert "text" in cols
    assert "trigger_at" in cols
    assert "fired_at" in cols
    assert "cancelled_at" in cols
    assert "entity_id" in cols
    assert "source_text" in cols
    # Legacy columns must be gone:
    assert "content" not in cols
    assert "remind_at" not in cols
    assert "completed" not in cols


def test_schedule_events_columns(tmp_path):
    conn = _connect(tmp_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(schedule_events)").fetchall()}
    for expected in [
        "id", "title", "start_at", "duration_min", "recurrence", "notes",
        "entity_id", "created_at", "heads_up_fired_at", "fired_at", "cancelled_at",
    ]:
        assert expected in cols, f"missing column: {expected}"


def test_list_items_columns(tmp_path):
    conn = _connect(tmp_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(list_items)").fetchall()}
    for expected in ["id", "list_name", "text", "added_at", "done_at", "position"]:
        assert expected in cols


def test_legacy_reminders_table_is_dropped_if_old_schema_exists(tmp_path):
    """Simulate an existing DB that had the legacy schema. Memory init should
    drop it and recreate with the new one."""
    db = tmp_path / "m.db"
    pre = sqlite3.connect(str(db))
    pre.executescript("""
        CREATE TABLE reminders (
            id INTEGER PRIMARY KEY,
            content TEXT,
            remind_at TIMESTAMP,
            completed INTEGER DEFAULT 0,
            created_at TIMESTAMP
        );
        INSERT INTO reminders (content, remind_at) VALUES ('legacy', '2024-01-01');
    """)
    pre.commit()
    pre.close()

    m = Memory(db_path=str(db))
    cols = {r[1] for r in m.conn.execute("PRAGMA table_info(reminders)").fetchall()}
    assert "text" in cols
    assert "trigger_at" in cols
    # Legacy data does NOT survive (spec §4.0: no production data to preserve).
    count = m.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
    assert count == 0
```

- [ ] **Step 3: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_schema.py -v`
Expected: failures — `reminders` exists but with old columns; `schedule_events` and `list_items` missing.

- [ ] **Step 4: Apply the migration**

Find the `_create_tables` or equivalent in `services/orchestrator/memory/__init__.py` and add the following block **before** any existing `CREATE TABLE IF NOT EXISTS reminders`:

```python
# ── Legacy cleanup: drop old NotesIntegration reminders table if it has
# the old schema. Safe no-op if table doesn't exist or is already new.
cols = {
    r[1]
    for r in self.conn.execute("PRAGMA table_info(reminders)").fetchall()
}
if cols and "content" in cols and "trigger_at" not in cols:
    self.conn.execute("DROP TABLE IF EXISTS reminders")
    self.conn.execute("DROP INDEX IF EXISTS idx_reminders_pending")
```

Then append/replace the reminders table and add the two new tables in the same schema-creation block:

```sql
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
```

Commit the existing connection after the migration runs.

- [ ] **Step 5: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_schema.py -v`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/memory/__init__.py services/orchestrator/tests/tasks/test_schema.py
git commit -m "feat(memory): drop legacy reminders, add tasks schema (reminders, schedule_events, list_items)"
```

---

## Task 3: Remove legacy reminder code from NotesIntegration

**Files:**
- Modify: `services/orchestrator/integrations/notes_integration.py`
- Create: `services/orchestrator/tests/tasks/test_notes_cleanup.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_notes_cleanup.py`:

```python
from integrations.notes_integration import NotesIntegration


def test_no_reminder_actions_remain():
    n = NotesIntegration()
    action_names = {a.name for a in n.get_actions()}
    assert "set_reminder" not in action_names
    assert "check_reminders" not in action_names
    # Kept actions:
    assert "save_note" in action_names
    assert "search_notes" in action_names
    assert "remember" in action_names
    assert "recall" in action_names


def test_no_proactive_reminders_method():
    # The legacy get_proactive_updates polled the old reminders table.
    # It should be removed entirely; BaseIntegration provides a default
    # implementation that returns None.
    import inspect
    from integrations import BaseIntegration
    # The override must not exist on NotesIntegration itself.
    assert "get_proactive_updates" not in NotesIntegration.__dict__
    # Base class still provides default:
    assert hasattr(BaseIntegration, "get_proactive_updates")
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_notes_cleanup.py -v`
Expected: both tests fail — `set_reminder` still in actions; `get_proactive_updates` still overridden.

- [ ] **Step 3: Remove reminder actions and helpers**

Edit `services/orchestrator/integrations/notes_integration.py`:

1. In `get_actions()`, delete the two `IntegrationAction(name="set_reminder", ...)` and `IntegrationAction(name="check_reminders", ...)` entries.
2. In `execute()`, delete `"set_reminder": self._set_reminder,` and `"check_reminders": self._check_reminders,` from the `handlers` dict.
3. Delete the `_set_reminder` and `_check_reminders` methods in their entirety.
4. Delete the `get_proactive_updates` method in its entirety.
5. In `_create_tables`, do **not** remove the `CREATE TABLE IF NOT EXISTS reminders` block — it's dead code now that `memory/__init__.py` owns the schema, but leaving it here would recreate the legacy table. **Delete** that one `CREATE TABLE IF NOT EXISTS reminders (...)` statement from `NotesIntegration._create_tables` and delete the `CREATE INDEX IF NOT EXISTS idx_reminders_pending ...` line along with it.

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_notes_cleanup.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/ -v`
Expected: all tests from previous tasks still pass.

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/integrations/notes_integration.py \
        services/orchestrator/tests/tasks/test_notes_cleanup.py
git commit -m "refactor(notes): remove legacy reminder actions; TasksIntegration will replace them"
```

---

## Task 4: Store — reminders CRUD

**Files:**
- Create: `services/orchestrator/integrations/tasks/store.py`
- Create: `services/orchestrator/tests/tasks/test_store_reminders.py`

Pure sqlite3 layer. No async. Tests use the `memory_db` fixture from `conftest.py` and hand-roll the schema inline (isolates store tests from `memory/__init__.py`).

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_store_reminders.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from integrations.tasks.store import TasksStore, SCHEMA_SQL

UTC = timezone.utc


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return TasksStore(memory_db)


def test_create_and_fetch_reminder(store):
    when = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    r = store.create_reminder(text="call mom", trigger_at=when, source_text="remind me to call mom at 5")
    assert r.id is not None
    assert r.text == "call mom"
    assert r.trigger_at == when
    assert r.fired_at is None
    assert r.source_text == "remind me to call mom at 5"


def test_reminders_due_returns_only_past_pending(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    past = store.create_reminder(text="past", trigger_at=now - timedelta(minutes=5))
    future = store.create_reminder(text="future", trigger_at=now + timedelta(minutes=5))
    due = store.reminders_due(now)
    ids = [r.id for r in due]
    assert past.id in ids
    assert future.id not in ids


def test_reminders_due_excludes_fired(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    r = store.create_reminder(text="x", trigger_at=now - timedelta(minutes=1))
    store.mark_reminder_fired(r.id, now)
    assert store.reminders_due(now) == []


def test_reminders_due_excludes_cancelled(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    r = store.create_reminder(text="x", trigger_at=now - timedelta(minutes=1))
    store.cancel_reminder(r.id, now)
    assert store.reminders_due(now) == []


def test_cancel_last_pending_reminder(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    r1 = store.create_reminder(text="first", trigger_at=now + timedelta(hours=1))
    r2 = store.create_reminder(text="second", trigger_at=now + timedelta(hours=2))
    cancelled = store.cancel_last_reminder(now)
    assert cancelled is not None
    assert cancelled.id == r2.id
    # And the first one is still pending:
    pending = store.list_pending_reminders()
    assert {r.id for r in pending} == {r1.id}


def test_cancel_last_when_none_pending_returns_none(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    assert store.cancel_last_reminder(now) is None
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_store_reminders.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.tasks.store'`.

- [ ] **Step 3: Create `store.py` with SCHEMA_SQL and reminder methods**

Create `services/orchestrator/integrations/tasks/store.py`:

```python
"""SQLite data layer for the tasks integration. Pure, sync, no HTTP."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
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
    # sqlite returns strings; datetime.fromisoformat handles "YYYY-MM-DDTHH:MM:SS+00:00"
    # and default "YYYY-MM-DD HH:MM:SS" (from CURRENT_TIMESTAMP)
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
        # return the reminder with cancelled_at set
        updated = self.conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (row["id"],)
        ).fetchone()
        return _row_to_reminder(updated)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_store_reminders.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/store.py \
        services/orchestrator/tests/tasks/test_store_reminders.py
git commit -m "feat(tasks): add store.py with reminders CRUD"
```

---

## Task 5: Store — schedule events CRUD + recurrence advance

**Files:**
- Modify: `services/orchestrator/integrations/tasks/store.py`
- Create: `services/orchestrator/tests/tasks/test_store_schedule.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_store_schedule.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from integrations.tasks.models import Recurrence
from integrations.tasks.store import TasksStore, SCHEMA_SQL

UTC = timezone.utc


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return TasksStore(memory_db)


def test_create_one_shot_schedule(store):
    when = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    e = store.create_schedule_event(title="Meeting with Jussi", start_at=when)
    assert e.id is not None
    assert e.recurrence is None
    assert e.fired_at is None
    assert e.heads_up_fired_at is None


def test_create_recurring_schedule(store):
    when = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)  # Monday
    e = store.create_schedule_event(
        title="Vitamins",
        start_at=when,
        recurrence=Recurrence("weekdays"),
    )
    assert e.recurrence == Recurrence("weekdays")


def test_schedule_due_at_start(store):
    now = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    e = store.create_schedule_event(title="Meeting", start_at=now)
    due = store.schedule_due(now)
    assert len(due) == 1
    assert due[0].id == e.id


def test_schedule_due_excludes_future(store):
    now = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    store.create_schedule_event(title="Later", start_at=now + timedelta(minutes=5))
    assert store.schedule_due(now) == []


def test_schedule_heads_up_window(store):
    now = datetime(2026, 4, 10, 14, 55, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Meeting", start_at=now + timedelta(minutes=5)  # 15:00, 5 min away
    )
    due = store.schedule_heads_up_due(now, window_min=10)
    assert len(due) == 1
    assert due[0].id == e.id


def test_schedule_heads_up_excludes_already_fired(store):
    now = datetime(2026, 4, 10, 14, 55, tzinfo=UTC)
    e = store.create_schedule_event(title="Meeting", start_at=now + timedelta(minutes=5))
    store.mark_heads_up_fired(e.id, now)
    assert store.schedule_heads_up_due(now, window_min=10) == []


def test_schedule_heads_up_outside_window(store):
    now = datetime(2026, 4, 10, 14, 0, tzinfo=UTC)
    store.create_schedule_event(title="Meeting", start_at=now + timedelta(minutes=30))
    # 30 min away, window is 10 → not yet
    assert store.schedule_heads_up_due(now, window_min=10) == []


def test_mark_schedule_fired(store):
    now = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    e = store.create_schedule_event(title="Meeting", start_at=now)
    store.mark_schedule_fired(e.id, now)
    assert store.schedule_due(now) == []


def test_advance_recurrence_daily(store):
    start = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Vitamins", start_at=start, recurrence=Recurrence("daily")
    )
    # Fire at start time, then advance
    store.advance_recurrence(e.id, now=start)
    refetched = store.get_schedule_event(e.id)
    assert refetched.start_at == datetime(2026, 4, 7, 8, 0, tzinfo=UTC)
    assert refetched.heads_up_fired_at is None  # reset for next cycle
    assert refetched.fired_at is None           # reset


def test_advance_recurrence_weekdays_skips_weekend(store):
    # Friday 8:00
    friday = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Vitamins", start_at=friday, recurrence=Recurrence("weekdays")
    )
    store.advance_recurrence(e.id, now=friday)
    refetched = store.get_schedule_event(e.id)
    # Friday + weekend → Monday
    assert refetched.start_at == datetime(2026, 4, 13, 8, 0, tzinfo=UTC)


def test_advance_recurrence_weekly_specific_day(store):
    # Monday at 8:00
    mon = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Planning", start_at=mon, recurrence=Recurrence("weekly:mon")
    )
    store.advance_recurrence(e.id, now=mon)
    refetched = store.get_schedule_event(e.id)
    assert refetched.start_at == datetime(2026, 4, 13, 8, 0, tzinfo=UTC)


def test_advance_recurrence_skips_past_downtime(store):
    """If we've been offline for days, advance past all missed days
    and surface only the most recent missed occurrence."""
    start = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)  # Monday
    e = store.create_schedule_event(
        title="Vitamins", start_at=start, recurrence=Recurrence("daily")
    )
    # Pretend we're 5 days late:
    five_days_later = start + timedelta(days=5)
    store.advance_recurrence(e.id, now=five_days_later)
    refetched = store.get_schedule_event(e.id)
    # Next occurrence must be strictly after `now`
    assert refetched.start_at > five_days_later
    # And should be exactly one day after five_days_later
    assert refetched.start_at == datetime(2026, 4, 12, 8, 0, tzinfo=UTC)
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_store_schedule.py -v`
Expected: 12 failures / errors — methods don't exist yet.

- [ ] **Step 3: Add schedule methods to `store.py`**

Append to `services/orchestrator/integrations/tasks/store.py`:

```python
# ─── Schedule events ────────────────────────────────────────────────────

from datetime import timedelta  # add at top if not already imported


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
```

Then add methods to the `TasksStore` class (below the reminder methods, still inside `class TasksStore`):

```python
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
```

And add this module-level helper at the bottom of `store.py`:

```python
# Weekday names → Python weekday() int (Mon=0..Sun=6)
_WEEKLY_DAYS = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}


def _next_occurrence(current: datetime, recurrence: Recurrence, now: datetime) -> datetime:
    """Advance `current` forward by recurrence rules until strictly > now."""
    candidate = current
    # Step once first (we're advancing FROM current, not staying at it).
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
        # same weekday next week
        return dt + timedelta(days=7)
    raise ValueError(f"Unknown recurrence kind: {kind}")
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_store_schedule.py -v`
Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/store.py \
        services/orchestrator/tests/tasks/test_store_schedule.py
git commit -m "feat(tasks): add schedule events CRUD and recurrence advance"
```

---

## Task 6: Store — list items CRUD

**Files:**
- Modify: `services/orchestrator/integrations/tasks/store.py`
- Create: `services/orchestrator/tests/tasks/test_store_lists.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_store_lists.py`:

```python
import pytest

from integrations.tasks.store import TasksStore, SCHEMA_SQL


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return TasksStore(memory_db)


def test_add_item_to_new_list(store):
    item = store.add_list_item("shopping", "milk")
    assert item.id is not None
    assert item.list_name == "shopping"
    assert item.text == "milk"
    assert item.done_at is None


def test_get_list_returns_items_in_position_order(store):
    store.add_list_item("shopping", "milk")
    store.add_list_item("shopping", "bread")
    store.add_list_item("shopping", "eggs")
    items = store.get_list("shopping")
    assert [i.text for i in items] == ["milk", "bread", "eggs"]


def test_get_list_excludes_other_lists(store):
    store.add_list_item("shopping", "milk")
    store.add_list_item("todo", "code review")
    assert [i.text for i in store.get_list("shopping")] == ["milk"]
    assert [i.text for i in store.get_list("todo")] == ["code review"]


def test_get_list_excludes_done(store):
    a = store.add_list_item("shopping", "milk")
    store.add_list_item("shopping", "bread")
    store.mark_list_item_done(a.id)
    items = store.get_list("shopping")
    assert [i.text for i in items] == ["bread"]


def test_is_duplicate_detects_existing(store):
    store.add_list_item("shopping", "Milk")
    assert store.is_duplicate("shopping", "milk") is True  # case-insensitive
    assert store.is_duplicate("shopping", "bread") is False


def test_is_duplicate_ignores_completed(store):
    a = store.add_list_item("shopping", "milk")
    store.mark_list_item_done(a.id)
    # Done items don't count as duplicates:
    assert store.is_duplicate("shopping", "milk") is False


def test_add_item_assigns_incrementing_position(store):
    a = store.add_list_item("shopping", "milk")
    b = store.add_list_item("shopping", "bread")
    c = store.add_list_item("shopping", "eggs")
    assert a.position < b.position < c.position
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_store_lists.py -v`
Expected: 7 failures — methods don't exist.

- [ ] **Step 3: Add list methods to `store.py`**

Add to `store.py` (module-level helper first):

```python
def _row_to_list_item(row: sqlite3.Row) -> ListItem:
    return ListItem(
        id=row["id"],
        list_name=row["list_name"],
        text=row["text"],
        added_at=_parse(row["added_at"]),
        done_at=_parse(row["done_at"]),
        position=row["position"] or 0,
    )
```

Then inside `class TasksStore`:

```python
    # ─── Lists ──────────────────────────────────────────────────────────

    def add_list_item(self, list_name: str, text: str) -> ListItem:
        # Next position = max(position) + 1 for active items in this list
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_store_lists.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/store.py \
        services/orchestrator/tests/tasks/test_store_lists.py
git commit -m "feat(tasks): add list items CRUD with duplicate detection"
```

---

## Task 7: Parser — recurrence grammar

**Files:**
- Create: `services/orchestrator/integrations/tasks/parser.py`
- Create: `services/orchestrator/tests/tasks/test_parser_recurrence.py`

Small closed-vocabulary regex pass. Runs *before* dateparser so the `every …` phrase is stripped.

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_parser_recurrence.py`:

```python
from integrations.tasks.models import Recurrence
from integrations.tasks.parser import parse_recurrence


def test_no_recurrence():
    rec, stripped = parse_recurrence("remind me to call mom at 5")
    assert rec is None
    assert stripped == "remind me to call mom at 5"


def test_every_day():
    rec, stripped = parse_recurrence("every day at 8 remind me to take vitamins")
    assert rec == Recurrence("daily")
    assert "every day" not in stripped.lower()
    assert "at 8" in stripped


def test_every_morning_is_daily():
    rec, _ = parse_recurrence("every morning at 7 stretch")
    assert rec == Recurrence("daily")


def test_every_evening_is_daily():
    rec, _ = parse_recurrence("every evening at 9 journal")
    assert rec == Recurrence("daily")


def test_every_weekday():
    rec, stripped = parse_recurrence("every weekday at 8 vitamins")
    assert rec == Recurrence("weekdays")
    assert "weekday" not in stripped.lower()


def test_every_monday():
    rec, _ = parse_recurrence("every monday at 9 planning")
    assert rec == Recurrence("weekly:mon")


def test_every_sunday():
    rec, _ = parse_recurrence("every sunday evening reflect")
    assert rec == Recurrence("weekly:sun")
    # morning/evening should survive in stripped for dateparser to read
    # but in this test we only care that the recurrence is detected.


def test_every_abbreviated_day():
    rec, _ = parse_recurrence("every fri afternoon")
    assert rec == Recurrence("weekly:fri")
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_parser_recurrence.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.tasks.parser'`.

- [ ] **Step 3: Create parser.py with recurrence only (time comes in next task)**

Create `services/orchestrator/integrations/tasks/parser.py`:

```python
"""Time + recurrence parsing for the tasks integration.
Pure functions, no I/O."""
from __future__ import annotations

import re
from typing import Optional

from .models import ParseError, Recurrence  # noqa: F401 (ParseError used later)


# ─── Recurrence ────────────────────────────────────────────────────────

_DAY_ALIASES = {
    "mon": "mon", "monday": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue",
    "wed": "wed", "wednesday": "wed",
    "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu",
    "fri": "fri", "friday": "fri",
    "sat": "sat", "saturday": "sat",
    "sun": "sun", "sunday": "sun",
}

# Build a day-name alternation for the regex, longest-first so "monday" matches
# before "mon":
_DAY_PATTERN = "|".join(sorted(_DAY_ALIASES.keys(), key=len, reverse=True))

# Precompiled patterns, checked in order.
_RE_EVERY_WEEKDAY = re.compile(r"\bevery\s+weekdays?\b", re.IGNORECASE)
_RE_EVERY_DAY = re.compile(r"\bevery\s+(day|morning|evening|night)\b", re.IGNORECASE)
_RE_EVERY_DOW = re.compile(rf"\bevery\s+({_DAY_PATTERN})\b", re.IGNORECASE)


def parse_recurrence(text: str) -> tuple[Optional[Recurrence], str]:
    """Detect a recurrence phrase. Return (Recurrence | None, stripped_text).
    The stripped text has the 'every ...' phrase removed so dateparser can
    handle the remaining time component cleanly."""

    m = _RE_EVERY_WEEKDAY.search(text)
    if m:
        stripped = (text[: m.start()] + text[m.end():]).strip()
        return Recurrence("weekdays"), _collapse_spaces(stripped)

    m = _RE_EVERY_DAY.search(text)
    if m:
        stripped = (text[: m.start()] + text[m.end():]).strip()
        return Recurrence("daily"), _collapse_spaces(stripped)

    m = _RE_EVERY_DOW.search(text)
    if m:
        day_word = m.group(1).lower()
        day_key = _DAY_ALIASES[day_word]
        stripped = (text[: m.start()] + text[m.end():]).strip()
        return Recurrence(f"weekly:{day_key}"), _collapse_spaces(stripped)

    return None, text


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_parser_recurrence.py -v`
Expected: `8 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/parser.py \
        services/orchestrator/tests/tasks/test_parser_recurrence.py
git commit -m "feat(tasks): parse recurrence grammar (daily, weekdays, weekly:<dow>)"
```

---

## Task 8: Parser — time parsing (dateparser wrapper)

**Files:**
- Modify: `services/orchestrator/integrations/tasks/parser.py`
- Create: `services/orchestrator/tests/tasks/test_parser_time.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_parser_time.py`:

```python
from datetime import datetime, timezone

import pytest
from freezegun import freeze_time

from integrations.tasks.models import ParseError
from integrations.tasks.parser import parse_when

UTC = timezone.utc


@freeze_time("2026-04-05 12:00:00")  # Sunday noon UTC
def test_in_twenty_minutes():
    dt = parse_when("in 20 minutes", tz="UTC")
    assert dt == datetime(2026, 4, 5, 12, 20, tzinfo=UTC)


@freeze_time("2026-04-05 12:00:00")
def test_at_5pm_today():
    dt = parse_when("at 5pm", tz="UTC")
    assert dt == datetime(2026, 4, 5, 17, 0, tzinfo=UTC)


@freeze_time("2026-04-05 20:00:00")  # 8pm — 5pm is already past
def test_at_5pm_rolls_to_tomorrow_when_past():
    dt = parse_when("at 5pm", tz="UTC")
    # dateparser with PREFER_DATES_FROM=future should roll to next day
    assert dt.date() == datetime(2026, 4, 6).date()
    assert dt.hour == 17


@freeze_time("2026-04-05 12:00:00")
def test_tomorrow_at_3():
    dt = parse_when("tomorrow at 3pm", tz="UTC")
    assert dt == datetime(2026, 4, 6, 15, 0, tzinfo=UTC)


@freeze_time("2026-04-05 12:00:00")  # Sunday
def test_friday():
    dt = parse_when("friday", tz="UTC")
    assert dt.weekday() == 4  # Friday
    assert dt > datetime(2026, 4, 5, 12, 0, tzinfo=UTC)


@freeze_time("2026-04-05 12:00:00")
def test_empty_string_raises():
    with pytest.raises(ParseError):
        parse_when("", tz="UTC")


@freeze_time("2026-04-05 12:00:00")
def test_unparseable_raises():
    with pytest.raises(ParseError):
        parse_when("glorp wibble", tz="UTC")


@freeze_time("2026-04-05 12:00:00")
def test_result_is_always_utc():
    dt = parse_when("at 5pm", tz="Europe/Stockholm")
    # 5pm Europe/Stockholm in April = 15:00 UTC (CEST = UTC+2)
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 15
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_parser_time.py -v`
Expected: `ImportError: cannot import name 'parse_when'`.

- [ ] **Step 3: Add `parse_when` to parser.py**

Append to `services/orchestrator/integrations/tasks/parser.py`:

```python
# ─── Time parsing ──────────────────────────────────────────────────────

from datetime import datetime, timezone  # add at top if not already imported

import dateparser


def parse_when(text: str, tz: str = "Europe/Stockholm") -> datetime:
    """Parse a natural-language time phrase into a UTC datetime.
    Raises ParseError if text is empty or unparseable."""
    if not text or not text.strip():
        raise ParseError("empty time phrase")

    dt = dateparser.parse(
        text,
        settings={
            "TIMEZONE": tz,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(),
        },
    )
    if dt is None:
        raise ParseError(f"could not parse time from: {text!r}")

    # Normalize to UTC
    if dt.tzinfo is None:
        # Shouldn't happen with RETURN_AS_TIMEZONE_AWARE, but defend anyway.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_parser_time.py -v`
Expected: `8 passed`. If `test_at_5pm_rolls_to_tomorrow_when_past` fails because dateparser returns the same day instead of rolling forward, add `RELATIVE_BASE=datetime.now()` (already included) and verify `freezegun` is patching `datetime.now()` correctly. If it still fails, accept that dateparser's roll-forward behavior requires `PREFER_DATES_FROM="future"` with a strictly-future comparison in our code:

```python
    # defensive: if dateparser returned a past moment, roll forward by one day
    now = datetime.now(timezone.utc) if datetime.now().tzinfo else datetime.now().replace(tzinfo=timezone.utc)
    if dt.astimezone(timezone.utc) < now:
        from datetime import timedelta
        dt = dt + timedelta(days=1)
```

Apply this fallback only if the test fails after the initial implementation.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/parser.py \
        services/orchestrator/tests/tasks/test_parser_time.py
git commit -m "feat(tasks): parse natural-language times via dateparser"
```

---

## Task 9: Chime synthesis

**Files:**
- Create: `services/orchestrator/integrations/tasks/chime.py`
- Create: `services/orchestrator/tests/tasks/test_chime.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_chime.py`:

```python
import os
import wave

from integrations.tasks.chime import ensure_chime_exists


def test_creates_file_if_missing(tmp_path):
    path = tmp_path / "chime.wav"
    assert not path.exists()
    ensure_chime_exists(str(path))
    assert path.exists()
    assert path.stat().st_size > 0


def test_idempotent(tmp_path):
    path = tmp_path / "chime.wav"
    ensure_chime_exists(str(path))
    first_mtime = path.stat().st_mtime
    ensure_chime_exists(str(path))
    # File was not rewritten
    assert path.stat().st_mtime == first_mtime


def test_wav_is_valid_24khz_mono_pcm16(tmp_path):
    path = tmp_path / "chime.wav"
    ensure_chime_exists(str(path))
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 24000
        assert w.getsampwidth() == 2  # 16-bit


def test_duration_roughly_800ms(tmp_path):
    path = tmp_path / "chime.wav"
    ensure_chime_exists(str(path))
    with wave.open(str(path), "rb") as w:
        duration_s = w.getnframes() / w.getframerate()
    assert 0.75 <= duration_s <= 0.85


def test_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "chime.wav"
    ensure_chime_exists(str(path))
    assert path.exists()
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_chime.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.tasks.chime'`.

- [ ] **Step 3: Implement `chime.py`**

Create `services/orchestrator/integrations/tasks/chime.py`:

```python
"""Generate a soft chime WAV file for overlay-card notifications.
Called once on orchestrator startup. Idempotent."""
from __future__ import annotations

import os
import wave

import numpy as np


SAMPLE_RATE = 24000
DURATION_S = 0.8
PEAK_DBFS = -18.0


def ensure_chime_exists(path: str) -> None:
    """Write chime.wav at `path` if it does not already exist."""
    if os.path.exists(path):
        return

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    t = np.linspace(0, DURATION_S, int(SAMPLE_RATE * DURATION_S), endpoint=False)

    # Two partials: C5 (523.25 Hz) and E5 (659.25 Hz), 3:1 amplitude
    fundamental = np.sin(2 * np.pi * 523.25 * t)
    third = np.sin(2 * np.pi * 659.25 * t)
    tone = 0.75 * fundamental + 0.25 * third

    # Exponential decay envelope
    decay = np.exp(-3.5 * t / DURATION_S)
    # Soft 5ms attack
    attack_samples = int(0.005 * SAMPLE_RATE)
    attack = np.ones_like(t)
    attack[:attack_samples] = np.linspace(0, 1, attack_samples)

    signal = tone * decay * attack

    # Normalize to peak, then apply -18 dBFS
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak
    target_amplitude = 10 ** (PEAK_DBFS / 20.0)
    signal = signal * target_amplitude

    pcm16 = np.int16(signal * 32767)

    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm16.tobytes())
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_chime.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/chime.py \
        services/orchestrator/tests/tasks/test_chime.py
git commit -m "feat(tasks): synthesize soft chime WAV on startup"
```

---

## Task 10: Scheduler async loop

**Files:**
- Create: `services/orchestrator/integrations/tasks/scheduler.py`
- Create: `services/orchestrator/tests/tasks/test_scheduler.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_scheduler.py`:

```python
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from integrations.tasks.models import Recurrence
from integrations.tasks.scheduler import run_tick
from integrations.tasks.store import SCHEMA_SQL, TasksStore

UTC = timezone.utc


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return TasksStore(memory_db)


@pytest.mark.asyncio
async def test_due_reminder_fires_exactly_once(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    store.create_reminder(text="call mom", trigger_at=now - timedelta(seconds=1))

    emit = AsyncMock()
    await run_tick(store, emit, now=now, heads_up_window_min=10)
    assert emit.await_count == 1
    # envelope arg kind
    args = emit.await_args.args[0]
    assert args["event"] == "overlay_card"
    assert args["kind"] == "reminder"
    assert args["chime"] is True

    # Second tick at same time fires nothing
    emit.reset_mock()
    await run_tick(store, emit, now=now, heads_up_window_min=10)
    assert emit.await_count == 0


@pytest.mark.asyncio
async def test_schedule_heads_up_then_start_fire_separately(store):
    start = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    store.create_schedule_event(title="Meeting", start_at=start)

    emit = AsyncMock()

    # 10 min before: heads-up only
    heads_up_time = start - timedelta(minutes=10)
    await run_tick(store, emit, now=heads_up_time, heads_up_window_min=10)
    assert emit.await_count == 1
    assert emit.await_args.args[0]["kind"] == "schedule_heads_up"

    # Between heads-up and start: nothing new
    emit.reset_mock()
    await run_tick(store, emit, now=start - timedelta(minutes=5), heads_up_window_min=10)
    assert emit.await_count == 0

    # At start: schedule fires
    emit.reset_mock()
    await run_tick(store, emit, now=start, heads_up_window_min=10)
    assert emit.await_count == 1
    assert emit.await_args.args[0]["kind"] == "schedule"


@pytest.mark.asyncio
async def test_recurring_event_advances_and_fires_next_cycle(store):
    mon_8am = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Vitamins", start_at=mon_8am, recurrence=Recurrence("daily")
    )

    emit = AsyncMock()
    await run_tick(store, emit, now=mon_8am, heads_up_window_min=10)
    assert emit.await_count == 1  # fired once

    refetched = store.get_schedule_event(e.id)
    # advanced to Tuesday
    assert refetched.start_at == datetime(2026, 4, 7, 8, 0, tzinfo=UTC)
    assert refetched.fired_at is None  # reset for next cycle


@pytest.mark.asyncio
async def test_exception_in_tick_does_not_raise(store, monkeypatch):
    emit = AsyncMock()

    # Force reminders_due to raise
    def boom(self, now):
        raise RuntimeError("boom")

    monkeypatch.setattr(TasksStore, "reminders_due", boom)
    # Must not raise — scheduler catches exceptions per tick
    await run_tick(store, emit, now=datetime.now(UTC), heads_up_window_min=10)
    # no cards emitted, no crash
    assert emit.await_count == 0


@pytest.mark.asyncio
async def test_list_cards_do_not_come_from_scheduler(store):
    """Scheduler never emits list cards — lists are on-demand only."""
    store.add_list_item("shopping", "milk")
    emit = AsyncMock()
    await run_tick(store, emit, now=datetime.now(UTC), heads_up_window_min=10)
    assert emit.await_count == 0
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_scheduler.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.tasks.scheduler'`.

- [ ] **Step 3: Implement scheduler.py**

Create `services/orchestrator/integrations/tasks/scheduler.py`:

```python
"""Background scheduler that surfaces due reminders and schedule events."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from .models import OverlayPayload
from .store import TasksStore

logger = logging.getLogger("samantha.tasks.scheduler")

EmitOverlay = Callable[[dict], Awaitable[None]]


def _format_time_local(dt: datetime, tz: str) -> str:
    """HH:MM in local timezone."""
    try:
        from zoneinfo import ZoneInfo
        local = dt.astimezone(ZoneInfo(tz))
    except Exception:
        local = dt
    return local.strftime("%H:%M")


def _reminder_envelope(reminder, tz: str) -> dict:
    when_str = f"now · {_format_time_local(reminder.trigger_at, tz)}"
    return OverlayPayload(
        kind="reminder",
        title=reminder.text,
        chime=True,
        when=when_str,
    ).to_envelope()


def _schedule_envelope(event, tz: str) -> dict:
    when_str = _format_time_local(event.start_at, tz)
    return OverlayPayload(
        kind="schedule",
        title=event.title,
        chime=True,
        when=f"now · {when_str}",
    ).to_envelope()


def _schedule_heads_up_envelope(event, now: datetime, tz: str) -> dict:
    delta_min = max(0, int((event.start_at - now).total_seconds() // 60))
    when_str = f"in {delta_min} min · {_format_time_local(event.start_at, tz)}"
    return OverlayPayload(
        kind="schedule_heads_up",
        title=event.title,
        chime=True,
        when=when_str,
    ).to_envelope()


async def run_tick(
    store: TasksStore,
    emit: EmitOverlay,
    now: datetime,
    heads_up_window_min: int = 10,
    tz: str = "Europe/Stockholm",
) -> None:
    """Process one scheduler tick. Exceptions are logged, not raised."""
    try:
        for r in store.reminders_due(now):
            await emit(_reminder_envelope(r, tz))
            store.mark_reminder_fired(r.id, now)

        for e in store.schedule_heads_up_due(now, window_min=heads_up_window_min):
            await emit(_schedule_heads_up_envelope(e, now, tz))
            store.mark_heads_up_fired(e.id, now)

        for e in store.schedule_due(now):
            await emit(_schedule_envelope(e, tz))
            if e.recurrence:
                store.advance_recurrence(e.id, now)
            else:
                store.mark_schedule_fired(e.id, now)
    except Exception:
        logger.exception("scheduler tick failed")


async def run(
    store: TasksStore,
    emit: EmitOverlay,
    poll_interval_s: int = 15,
    heads_up_window_min: int = 10,
    tz: str = "Europe/Stockholm",
) -> None:
    """Long-running scheduler loop. Runs forever; cancel externally."""
    logger.info("tasks scheduler started")
    while True:
        await run_tick(
            store,
            emit,
            now=datetime.now(timezone.utc),
            heads_up_window_min=heads_up_window_min,
            tz=tz,
        )
        await asyncio.sleep(poll_interval_s)
```

- [ ] **Step 4: Configure pytest-asyncio mode**

Create `services/orchestrator/pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 5: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_scheduler.py -v`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/integrations/tasks/scheduler.py \
        services/orchestrator/tests/tasks/test_scheduler.py \
        services/orchestrator/pytest.ini
git commit -m "feat(tasks): add async scheduler loop with heads-up and recurrence"
```

---

## Task 11: TasksIntegration — adapter + reminder actions

**Files:**
- Modify: `services/orchestrator/integrations/tasks/__init__.py`
- Create: `services/orchestrator/tests/tasks/test_integration_reminders.py`

Implements `BaseIntegration` contract. For each action we care about both the spoken confirmation and the overlay payload. `execute()` returns a dict for backward compatibility with `IntegrationRegistry`, but we expose a richer method `handle_action(action_name, text) -> TaskActionResult` that the orchestrator calls directly.

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_integration_reminders.py`:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from integrations.tasks import TasksIntegration
from integrations.tasks.store import SCHEMA_SQL, TasksStore


@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    store = TasksStore(memory_db)
    integ = TasksIntegration()
    integ.store = store  # inject for tests; in prod, initialize() wires it
    return integ


@freeze_time("2026-04-05 12:00:00")
async def test_add_reminder_happy_path(integration):
    result = await integration.handle_action("add_reminder", "remind me to call mom at 5pm")
    assert "call mom" in result.spoken.lower()
    assert result.overlay is not None
    assert result.overlay.kind == "reminder"
    assert result.overlay.chime is False  # creation, not fire
    # store now has one pending reminder
    pending = integration.store.list_pending_reminders()
    assert len(pending) == 1
    assert pending[0].text == "call mom"


@freeze_time("2026-04-05 12:00:00")
async def test_add_reminder_missing_time_asks_clarification(integration):
    result = await integration.handle_action("add_reminder", "remind me to call mom")
    # no trigger_at parseable → clarification
    assert "when" in result.spoken.lower()
    assert result.overlay is None
    assert integration.store.list_pending_reminders() == []


@freeze_time("2026-04-05 12:00:00")
async def test_add_reminder_empty_text_asks_clarification(integration):
    result = await integration.handle_action("add_reminder", "remind me at 5pm")
    # no subject after stripping "remind me at 5pm" → clarification
    assert result.overlay is None or "what" in result.spoken.lower()


async def test_cancel_last_with_nothing_pending(integration):
    result = await integration.handle_action("cancel_last_reminder", "forget that")
    assert "nothing" in result.spoken.lower()
    assert result.overlay is None


@freeze_time("2026-04-05 12:00:00")
async def test_cancel_last_cancels_most_recent(integration):
    await integration.handle_action("add_reminder", "remind me to X at 3pm")
    await integration.handle_action("add_reminder", "remind me to Y at 4pm")
    result = await integration.handle_action("cancel_last_reminder", "cancel that")
    assert "Y" in result.spoken or "y" in result.spoken.lower()
    # one still pending
    assert len(integration.store.list_pending_reminders()) == 1
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_integration_reminders.py -v`
Expected: `ImportError: cannot import name 'TasksIntegration'`.

- [ ] **Step 3: Implement `TasksIntegration` (reminders only for this task)**

Replace the empty `services/orchestrator/integrations/tasks/__init__.py` with:

```python
"""Tasks integration — reminders, schedule events, lists."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from integrations import BaseIntegration, IntegrationAction

from .models import OverlayPayload, ParseError, TaskActionResult
from .parser import parse_recurrence, parse_when
from .store import SCHEMA_SQL, TasksStore

logger = logging.getLogger("samantha.tasks")


DEFAULT_TZ = os.environ.get("TZ", "Europe/Stockholm")


def _strip_reminder_lead(text: str) -> str:
    """Remove the 'remind me (to|about)' prefix so what's left is the subject + time."""
    return re.sub(r"^\s*remind me( to| about)?\s*", "", text, flags=re.IGNORECASE).strip()


def _split_subject_and_time(text: str) -> tuple[str, str]:
    """Heuristic: split on the first ' at ', ' in ', ' tomorrow', ' tonight', ' on <day>'.
    Returns (subject, time_phrase). Either may be empty."""
    patterns = [
        r"\s+(at\s+.+)$",
        r"\s+(in\s+\d.+)$",
        r"\s+(tomorrow.*)$",
        r"\s+(tonight.*)$",
        r"\s+(this\s+(?:morning|afternoon|evening|night).*)$",
        r"\s+(next\s+.+)$",
        r"\s+(on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday).*)$",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            subject = text[: m.start()].strip()
            time_phrase = m.group(1).strip()
            return subject, time_phrase
    return text.strip(), ""


class TasksIntegration(BaseIntegration):
    name = "tasks"
    display_name = "Reminders, Schedules & Lists"
    description = "Hold reminders, schedule events, and lists for the user"
    icon = "🗓️"
    requires_auth = False

    def __init__(self):
        super().__init__()
        self.db_path: str = "config/samantha_memory.db"
        self.conn: Optional[sqlite3.Connection] = None
        self.store: Optional[TasksStore] = None
        self.tz: str = DEFAULT_TZ

    async def initialize(self, config: dict) -> bool:
        self.db_path = config.get("db_path", self.db_path)
        self.tz = config.get("tz", DEFAULT_TZ)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.store = TasksStore(self.conn)
        logger.info(f"Tasks store ready at {self.db_path} (tz={self.tz})")
        return True

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="add_reminder",
                description="Create a one-shot reminder for a specific time",
                keywords=["remind me", "remind me to", "remind me about"],
                parameters=["text"],
                examples=["Remind me to call mom at 5pm", "Remind me in 20 minutes to check the oven"],
            ),
            IntegrationAction(
                name="cancel_last_reminder",
                description="Cancel the most recent pending reminder",
                keywords=["cancel that", "forget that", "cancel the last reminder", "remove that reminder"],
                parameters=[],
                examples=["Cancel that", "Forget the last reminder"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        """Back-compat dict interface for IntegrationRegistry. Prefer handle_action()."""
        text = params.get("text") or params.get("content") or ""
        result = await self.handle_action(action_name, text)
        return {
            "spoken": result.spoken,
            "overlay": result.overlay.to_envelope() if result.overlay else None,
        }

    async def handle_action(self, action_name: str, text: str) -> TaskActionResult:
        handlers = {
            "add_reminder": self._add_reminder,
            "cancel_last_reminder": self._cancel_last_reminder,
        }
        handler = handlers.get(action_name)
        if not handler:
            return TaskActionResult(spoken=f"I don't know how to {action_name}.", overlay=None)
        return await handler(text)

    # ─── Handlers ───────────────────────────────────────────────────────

    async def _add_reminder(self, text: str) -> TaskActionResult:
        stripped = _strip_reminder_lead(text)
        subject, time_phrase = _split_subject_and_time(stripped)

        if not time_phrase:
            return TaskActionResult(
                spoken="When should I remind you?",
                overlay=None,
            )
        if not subject:
            return TaskActionResult(
                spoken="What should I remind you about?",
                overlay=None,
            )

        try:
            trigger_at = parse_when(time_phrase, tz=self.tz)
        except ParseError:
            return TaskActionResult(
                spoken="I couldn't figure out the time — can you rephrase it?",
                overlay=None,
            )

        reminder = self.store.create_reminder(
            text=subject,
            trigger_at=trigger_at,
            source_text=text,
        )

        local_str = self._format_local(trigger_at)
        spoken = f"Got it — I'll remind you to {subject} at {local_str}."
        overlay = OverlayPayload(
            kind="reminder",
            title=subject,
            chime=False,
            when=f"at {local_str}",
        )
        return TaskActionResult(spoken=spoken, overlay=overlay)

    async def _cancel_last_reminder(self, text: str) -> TaskActionResult:
        now = datetime.now(timezone.utc)
        cancelled = self.store.cancel_last_reminder(now)
        if cancelled is None:
            return TaskActionResult(
                spoken="There's nothing pending to cancel.",
                overlay=None,
            )
        return TaskActionResult(
            spoken=f"Cancelled — I won't remind you to {cancelled.text}.",
            overlay=None,
        )

    # ─── Helpers ────────────────────────────────────────────────────────

    def _format_local(self, dt: datetime) -> str:
        try:
            from zoneinfo import ZoneInfo
            return dt.astimezone(ZoneInfo(self.tz)).strftime("%H:%M")
        except Exception:
            return dt.strftime("%H:%M")

    async def shutdown(self):
        if self.conn:
            self.conn.close()
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_integration_reminders.py -v`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/__init__.py \
        services/orchestrator/tests/tasks/test_integration_reminders.py
git commit -m "feat(tasks): TasksIntegration with add_reminder and cancel_last_reminder"
```

---

## Task 12: TasksIntegration — schedule actions

**Files:**
- Modify: `services/orchestrator/integrations/tasks/__init__.py`
- Create: `services/orchestrator/tests/tasks/test_integration_schedule.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_integration_schedule.py`:

```python
from datetime import datetime, timezone

import pytest
from freezegun import freeze_time

from integrations.tasks import TasksIntegration
from integrations.tasks.models import Recurrence
from integrations.tasks.store import SCHEMA_SQL, TasksStore


@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    integ = TasksIntegration()
    integ.store = TasksStore(memory_db)
    integ.tz = "UTC"
    return integ


@freeze_time("2026-04-05 12:00:00")
async def test_add_one_shot_schedule(integration):
    result = await integration.handle_action(
        "add_schedule", "meeting with Jussi friday at 3pm"
    )
    assert result.overlay is not None
    assert result.overlay.kind == "schedule"
    events = integration.store.conn.execute(
        "SELECT title, start_at, recurrence FROM schedule_events"
    ).fetchall()
    assert len(events) == 1
    assert "jussi" in events[0]["title"].lower()
    assert events[0]["recurrence"] is None


@freeze_time("2026-04-05 12:00:00")  # Sunday
async def test_add_recurring_weekdays(integration):
    result = await integration.handle_action(
        "add_schedule", "every weekday at 8 vitamins"
    )
    assert result.overlay is not None
    events = integration.store.conn.execute(
        "SELECT title, recurrence FROM schedule_events"
    ).fetchall()
    assert len(events) == 1
    assert events[0]["recurrence"] == "weekdays"


@freeze_time("2026-04-05 12:00:00")
async def test_add_recurring_weekly_monday(integration):
    await integration.handle_action(
        "add_schedule", "every monday at 9 planning session"
    )
    row = integration.store.conn.execute(
        "SELECT recurrence FROM schedule_events"
    ).fetchone()
    assert row["recurrence"] == "weekly:mon"


@freeze_time("2026-04-05 12:00:00")
async def test_show_schedule_returns_upcoming(integration):
    await integration.handle_action("add_schedule", "dentist tuesday at 10am")
    result = await integration.handle_action("show_schedule", "what's next")
    assert result.overlay is not None
    assert result.overlay.kind == "schedule"
    assert "dentist" in result.overlay.title.lower()


async def test_show_schedule_empty(integration):
    result = await integration.handle_action("show_schedule", "what's on my schedule")
    assert "nothing" in result.spoken.lower() or "no " in result.spoken.lower()
    assert result.overlay is None


@freeze_time("2026-04-05 12:00:00")
async def test_add_schedule_unparseable_time(integration):
    result = await integration.handle_action("add_schedule", "meeting glorp")
    # No parseable time → clarification
    assert result.overlay is None
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_integration_schedule.py -v`
Expected: `KeyError` or similar — `add_schedule`/`show_schedule` not in handlers.

- [ ] **Step 3: Add schedule handlers to TasksIntegration**

In `services/orchestrator/integrations/tasks/__init__.py`:

1. Extend `get_actions()` — append:

```python
            IntegrationAction(
                name="add_schedule",
                description="Add a calendar event or recurring routine",
                keywords=["meeting with", "appointment", "dentist", "call with",
                          "every morning", "every weekday", "every monday",
                          "every tuesday", "every wednesday", "every thursday",
                          "every friday", "every saturday", "every sunday", "every day"],
                parameters=["text"],
                examples=["Meeting with Jussi Friday at 3pm", "Every weekday at 8 remind me to take vitamins"],
            ),
            IntegrationAction(
                name="show_schedule",
                description="Show upcoming schedule events",
                keywords=["what's next", "what's on my schedule", "what's today",
                          "what's this week", "show my schedule"],
                parameters=[],
                examples=["What's next?", "What's on my schedule today?"],
            ),
```

2. Extend the `handlers` dict in `handle_action`:

```python
        handlers = {
            "add_reminder": self._add_reminder,
            "cancel_last_reminder": self._cancel_last_reminder,
            "add_schedule": self._add_schedule,
            "show_schedule": self._show_schedule,
        }
```

3. Add these handler methods to the class:

```python
    async def _add_schedule(self, text: str) -> TaskActionResult:
        # Strip any leading "schedule " / "add " / etc.
        body = re.sub(r"^\s*(schedule|add|create)\s+", "", text, flags=re.IGNORECASE).strip()

        # Detect recurrence first; then parse time on the stripped remainder.
        recurrence, stripped = parse_recurrence(body)

        # Split title vs time phrase
        title, time_phrase = _split_subject_and_time(stripped)

        # For recurring events without an explicit time phrase, check if the stripped
        # body still starts with a time ("at 8 vitamins" → time="at 8", title="vitamins")
        if not time_phrase:
            m = re.match(r"^(at\s+\S+|in\s+\d+\s+\w+)\s+(.+)$", stripped, re.IGNORECASE)
            if m:
                time_phrase = m.group(1)
                title = m.group(2)

        if not title:
            return TaskActionResult(
                spoken="What's the event?",
                overlay=None,
            )
        if not time_phrase:
            return TaskActionResult(
                spoken="When should this be?",
                overlay=None,
            )

        try:
            start_at = parse_when(time_phrase, tz=self.tz)
        except ParseError:
            return TaskActionResult(
                spoken="I couldn't figure out the time — can you rephrase it?",
                overlay=None,
            )

        event = self.store.create_schedule_event(
            title=title,
            start_at=start_at,
            recurrence=recurrence,
        )

        local_str = self._format_local(start_at)
        if recurrence:
            spoken = f"Added — {title}, {self._recurrence_phrase(recurrence)} at {local_str}."
            when_display = f"{self._recurrence_phrase(recurrence)} at {local_str}"
        else:
            spoken = f"Added — {title} at {local_str}."
            when_display = f"at {local_str}"

        overlay = OverlayPayload(
            kind="schedule",
            title=title,
            chime=False,
            when=when_display,
        )
        return TaskActionResult(spoken=spoken, overlay=overlay)

    async def _show_schedule(self, text: str) -> TaskActionResult:
        now = datetime.now(timezone.utc)
        # Find the next upcoming event, pending or not-yet-heads-up.
        row = self.store.conn.execute(
            "SELECT * FROM schedule_events "
            "WHERE start_at > ? AND cancelled_at IS NULL "
            "ORDER BY start_at ASC LIMIT 1",
            (now.astimezone(timezone.utc).isoformat(),),
        ).fetchone()
        if row is None:
            return TaskActionResult(
                spoken="There's nothing on your schedule.",
                overlay=None,
            )
        from .store import _row_to_schedule_event
        event = _row_to_schedule_event(row)
        local_str = self._format_local(event.start_at)
        overlay = OverlayPayload(
            kind="schedule",
            title=event.title,
            chime=False,
            when=f"at {local_str}",
        )
        return TaskActionResult(
            spoken=f"Next up: {event.title} at {local_str}.",
            overlay=overlay,
        )

    def _recurrence_phrase(self, rec) -> str:
        kind = rec.kind
        if kind == "daily":
            return "every day"
        if kind == "weekdays":
            return "every weekday"
        if kind.startswith("weekly:"):
            day_abbr = kind.split(":", 1)[1]
            names = {
                "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
                "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
            }
            return f"every {names.get(day_abbr, day_abbr)}"
        return kind
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_integration_schedule.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/__init__.py \
        services/orchestrator/tests/tasks/test_integration_schedule.py
git commit -m "feat(tasks): TasksIntegration schedule actions (add, show, recurrence)"
```

---

## Task 13: TasksIntegration — list actions

**Files:**
- Modify: `services/orchestrator/integrations/tasks/__init__.py`
- Create: `services/orchestrator/tests/tasks/test_integration_lists.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/tasks/test_integration_lists.py`:

```python
import pytest

from integrations.tasks import TasksIntegration
from integrations.tasks.store import SCHEMA_SQL, TasksStore


@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    integ = TasksIntegration()
    integ.store = TasksStore(memory_db)
    integ.tz = "UTC"
    return integ


async def test_add_to_shopping_list(integration):
    result = await integration.handle_action(
        "add_to_list", "add milk to the shopping list"
    )
    assert result.overlay is not None
    assert result.overlay.kind == "list"
    assert result.overlay.list_name == "shopping"
    assert "milk" in result.overlay.items
    assert result.overlay.highlight_index == 0
    assert result.overlay.chime is False


async def test_add_to_named_list(integration):
    result = await integration.handle_action(
        "add_to_list", "add The Shining to the movies list"
    )
    assert result.overlay.list_name == "movies"
    assert any("shining" in i.lower() for i in result.overlay.items)


async def test_add_to_todo_list_via_phrasing(integration):
    result = await integration.handle_action(
        "add_to_list", "I should refactor the memory schema"
    )
    assert result.overlay.list_name == "todo"


async def test_add_shopping_via_buy_phrasing(integration):
    result = await integration.handle_action(
        "add_to_list", "remind me to buy bread"
    )
    assert result.overlay.list_name == "shopping"
    assert any("bread" in i.lower() for i in result.overlay.items)


async def test_duplicate_is_flagged_in_kicker(integration):
    await integration.handle_action("add_to_list", "add milk to the shopping list")
    result = await integration.handle_action("add_to_list", "add Milk to shopping")
    # Second add still succeeds but spoken mentions duplicate
    assert "already" in result.spoken.lower()


async def test_show_list(integration):
    await integration.handle_action("add_to_list", "add milk to shopping")
    await integration.handle_action("add_to_list", "add bread to shopping")
    result = await integration.handle_action("show_list", "what's on my shopping list")
    assert result.overlay is not None
    assert result.overlay.list_name == "shopping"
    assert result.overlay.highlight_index is None
    assert "milk" in result.overlay.items
    assert "bread" in result.overlay.items


async def test_show_empty_list(integration):
    result = await integration.handle_action("show_list", "what's on my shopping list")
    assert "empty" in result.spoken.lower() or "nothing" in result.spoken.lower()
```

- [ ] **Step 2: Run it — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_integration_lists.py -v`
Expected: failures — list handlers don't exist.

- [ ] **Step 3: Add list handlers**

In `services/orchestrator/integrations/tasks/__init__.py`:

1. Append to `get_actions()`:

```python
            IntegrationAction(
                name="add_to_list",
                description="Add an item to a named list (shopping, todo, or any name you pick)",
                keywords=["add to", "put on", "shopping list", "todo", "grocery",
                          "remind me to buy", "need to buy", "I should", "I need to"],
                parameters=["text"],
                examples=["Add milk to the shopping list", "I should call the bank"],
            ),
            IntegrationAction(
                name="show_list",
                description="Show items on a named list",
                keywords=["show my list", "what's on my", "shopping list", "todo list"],
                parameters=["text"],
                examples=["What's on my shopping list?", "Show me my todo"],
            ),
```

2. Extend the `handlers` dict:

```python
        handlers = {
            "add_reminder": self._add_reminder,
            "cancel_last_reminder": self._cancel_last_reminder,
            "add_schedule": self._add_schedule,
            "show_schedule": self._show_schedule,
            "add_to_list": self._add_to_list,
            "show_list": self._show_list,
        }
```

3. Add these methods to the class:

```python
    def _detect_list_and_item(self, text: str) -> tuple[str, str]:
        """Determine (list_name, item) from a natural-language instruction.
        Returns ("", "") if neither can be extracted."""
        t = text.strip()

        # "add X to the Y list" / "add X to Y list" / "put X on Y list"
        m = re.search(
            r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?:the\s+)?(?:my\s+)?(\w+)(?:\s+list)?$",
            t, re.IGNORECASE,
        )
        if m:
            item = m.group(1).strip()
            list_name = m.group(2).lower()
            # Normalize "shopping" synonyms
            if list_name in ("groceries", "grocery"):
                list_name = "shopping"
            return list_name, item

        # "remind me to buy X" / "need to buy X" / "pick up X"
        m = re.search(
            r"^(?:remind me to buy|need to buy|pick up|get|buy)\s+(.+)$",
            t, re.IGNORECASE,
        )
        if m:
            return "shopping", m.group(1).strip()

        # "I should X" / "I need to X" / "todo: X"
        m = re.search(
            r"^(?:i should|i need to|todo:?)\s+(.+)$",
            t, re.IGNORECASE,
        )
        if m:
            return "todo", m.group(1).strip()

        return "", ""

    def _detect_list_to_show(self, text: str) -> str:
        """Extract the list name from a 'show me X list' style query."""
        m = re.search(
            r"(?:show me|what(?:'s| is) on|show)\s+(?:my\s+|the\s+)?(\w+)(?:\s+list)?",
            text, re.IGNORECASE,
        )
        if m:
            name = m.group(1).lower()
            if name in ("groceries", "grocery"):
                return "shopping"
            if name in ("list", "my"):  # caught stopword
                return ""
            return name
        return ""

    async def _add_to_list(self, text: str) -> TaskActionResult:
        list_name, item = self._detect_list_and_item(text)
        if not list_name or not item:
            return TaskActionResult(
                spoken="What should I add, and to which list?",
                overlay=None,
            )

        duplicate = self.store.is_duplicate(list_name, item)
        self.store.add_list_item(list_name, item)
        all_items = self.store.get_list(list_name)
        texts = [i.text for i in all_items]
        # Find the index of the just-added item (last matching, case-insensitive)
        highlight = None
        for idx in range(len(texts) - 1, -1, -1):
            if texts[idx].lower() == item.lower():
                highlight = idx
                break

        if duplicate:
            spoken = f"{item} was already on your {list_name} list — added again."
        else:
            spoken = f"Added {item} to your {list_name} list."

        overlay = OverlayPayload(
            kind="list",
            title=f"{list_name.capitalize()} list",
            chime=False,
            items=texts,
            highlight_index=highlight,
            list_name=list_name,
        )
        return TaskActionResult(spoken=spoken, overlay=overlay)

    async def _show_list(self, text: str) -> TaskActionResult:
        list_name = self._detect_list_to_show(text)
        if not list_name:
            return TaskActionResult(
                spoken="Which list?",
                overlay=None,
            )
        items = self.store.get_list(list_name)
        if not items:
            return TaskActionResult(
                spoken=f"Your {list_name} list is empty.",
                overlay=None,
            )
        overlay = OverlayPayload(
            kind="list",
            title=f"{list_name.capitalize()} list",
            chime=False,
            items=[i.text for i in items],
            highlight_index=None,
            list_name=list_name,
        )
        return TaskActionResult(
            spoken=f"Here's your {list_name} list.",
            overlay=overlay,
        )
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_integration_lists.py -v`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/tasks/__init__.py \
        services/orchestrator/tests/tasks/test_integration_lists.py
git commit -m "feat(tasks): TasksIntegration list actions (add_to_list, show_list)"
```

---

## Task 14: Wire TasksIntegration + scheduler + chime HTTP into main.py

**Files:**
- Modify: `services/orchestrator/main.py`

This is mostly glue; no new tests — the end-to-end smoke test in Task 18 covers this path.

- [ ] **Step 1: Import and register TasksIntegration**

Near the top of `services/orchestrator/main.py` with the other integration imports, add:

```python
from integrations.tasks import TasksIntegration
from integrations.tasks.chime import ensure_chime_exists
from integrations.tasks.scheduler import run as run_tasks_scheduler
```

In the method that initializes integrations (search for `init_integrations` or wherever `NotesIntegration()` is currently instantiated around line 127), add after the existing registrations:

```python
        tasks = TasksIntegration()
        self.registry.register(tasks)
        await self.registry.enable("tasks", {"db_path": "config/samantha_memory.db"})
        self.tasks_integration = tasks
```

And add `self.tasks_integration: TasksIntegration | None = None` to `SamanthaState.__init__`.

- [ ] **Step 2: Mount /static for the chime**

Right after `app = FastAPI(...)` and the CORS middleware (around line 288), add:

```python
from fastapi.staticfiles import StaticFiles
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
```

- [ ] **Step 3: Generate chime + launch scheduler in lifespan startup**

Inside the `lifespan` async context manager (around line 254), after `await state.init_integrations()` and before `yield`, add:

```python
    # Generate chime if missing
    chime_path = os.path.join(STATIC_DIR, "chime.wav")
    ensure_chime_exists(chime_path)

    # Launch the tasks scheduler
    async def _emit_overlay(envelope: dict):
        await state.broadcast(envelope)

    tasks_scheduler_task = None
    if state.tasks_integration and state.tasks_integration.store:
        tasks_scheduler_task = asyncio.create_task(
            run_tasks_scheduler(
                store=state.tasks_integration.store,
                emit=_emit_overlay,
                poll_interval_s=15,
                heads_up_window_min=10,
                tz=os.environ.get("TZ", "Europe/Stockholm"),
            )
        )
```

And in the shutdown portion (after `yield`), add:

```python
    if tasks_scheduler_task is not None:
        tasks_scheduler_task.cancel()
```

- [ ] **Step 4: Wire the chat pipeline to broadcast overlays and short-circuit LLM re-summarization**

The existing `process_message` in `services/orchestrator/main.py` (lines 427–463) already routes intents through `intg.execute(action_name, parameters)` on line 441 and then asks the LLM to reformat the result. For tasks, we want:

1. The spoken string returned by `TasksIntegration.execute()` to be used **directly** (skip LLM reformatting — `handle_action` already returns user-ready prose).
2. The overlay envelope to be broadcast over WebSocket.

Since `TasksIntegration.execute()` (Task 11) already returns `{"spoken": str, "overlay": envelope|None}`, the change in `main.py` is minimal. Insert this block immediately after line 441 (`result = await intg.execute(intent.action_name, intent.parameters)`), before line 443:

```python
            # Tasks integration returns a ready-made spoken string and optional overlay.
            # Short-circuit the LLM reformatting path used by other integrations.
            if intent.integration_name == "tasks" and isinstance(result, dict) and "spoken" in result:
                spoken_text = result["spoken"]
                overlay_envelope = result.get("overlay")
                state.add_message("user", user_text)
                state.add_message("assistant", spoken_text)
                state.personality.update_mood(analysis)
                if overlay_envelope:
                    await state.broadcast(overlay_envelope)
                return {
                    "text": spoken_text,
                    "tts_text": spoken_text,
                    "mood": state.personality.mood,
                    "action": intent.action_name,
                    "result": result,
                }
```

This preserves every existing caller of `process_message` — the returned dict has the same shape other integrations produce, so whatever downstream code calls TTS and broadcasts `samantha_speaking` still fires. The only added side effect is the `state.broadcast(overlay_envelope)` call.

Verify by re-reading the caller of `process_message` (search: `grep -n "process_message" services/orchestrator/main.py`). The caller handles `text`/`tts_text`/`mood` already; the overlay broadcast happens in the new block before `return`.

- [ ] **Step 5: Update `/reset-all` to wipe new tables**

Find the `/reset-all` handler (around line 602) and update its SQL script:

```python
        state.memory.conn.executescript("""
            DELETE FROM facts;
            DELETE FROM episodes;
            DELETE FROM mood_log;
            DELETE FROM memory_embeddings;
            DELETE FROM news_digests;
            DELETE FROM notes;
            DELETE FROM reminders;
            DELETE FROM schedule_events;
            DELETE FROM list_items;
            DELETE FROM memories;
            DELETE FROM episodes_fts;
            DELETE FROM facts_fts;
        """)
```

- [ ] **Step 6: Run full test suite**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/ -v`
Expected: all tests still pass (wiring changes are not covered by unit tests — the E2E smoke in Task 18 will cover this).

- [ ] **Step 7: Start the orchestrator and hit /health**

Run: `cd services/orchestrator && PYTHONPATH=. python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload`
In another terminal: `curl http://127.0.0.1:8000/health`
Expected: 200 OK, and in the server log: `tasks scheduler started` and `Tasks store ready at config/samantha_memory.db`.

Also verify: `curl -I http://127.0.0.1:8000/static/chime.wav`
Expected: 200 OK with `content-type: audio/wav` (or similar), non-zero `content-length`.

Kill the server with Ctrl+C.

- [ ] **Step 8: Commit**

```bash
git add services/orchestrator/main.py services/orchestrator/static/.gitkeep
git commit -m "feat(orchestrator): wire TasksIntegration, scheduler, and chime HTTP endpoint"
```

(Create `services/orchestrator/static/.gitkeep` as an empty file first if it doesn't exist.)

---

## Task 15: Visual shell — header polish (mockup B)

**Files:**
- Modify: `services/visual-shell/index.html`

No automated tests for the visual shell (no JS harness in repo). Verification is visual.

- [ ] **Step 1: Update the `#clock` and `#identity` CSS**

In `services/visual-shell/index.html`, replace the existing `#clock` block (around lines 183-194) with:

```css
    /* Clock — enlarged, darker (mockup B) */
    #clock {
      position: fixed; top: 2rem; left: 2rem; z-index: 18;
    }
    #clock .time {
      font-family: 'Outfit', sans-serif;
      font-size: 2.2rem; font-weight: 300;
      color: #3a0f1c; opacity: 0.92;
      letter-spacing: 0.02em; line-height: 1;
    }
    #clock .day {
      font-family: 'Outfit', sans-serif;
      font-size: 0.8rem; font-weight: 500;
      color: #3a0f1c; opacity: 0.85;
      letter-spacing: 0.22em; text-transform: uppercase;
      margin-top: 6px;
    }
    #clock .date {
      font-family: 'Outfit', sans-serif;
      font-size: 0.75rem; font-weight: 400;
      color: #5c2030; opacity: 0.75;
      letter-spacing: 0.15em; text-transform: uppercase;
      margin-top: 2px;
    }
```

Replace the `#identity` block (around lines 214-220) with:

```css
    /* Identity — nameplate, enlarged (mockup B) */
    #identity {
      position: fixed; top: 2rem; right: 2rem; z-index: 18;
      font-family: 'Cormorant Garamond', serif;
      font-size: 1.35rem; font-weight: 400;
      font-style: italic;
      color: #3a0f1c; opacity: 0.85;
      letter-spacing: 0.08em;
    }
```

- [ ] **Step 2: Add the `.day` element inside `#clock` markup**

Find (around line 334):

```html
  <div id="clock">
    <div class="time" id="clock-time"></div>
    <div class="date" id="clock-date"></div>
  </div>
```

Replace with:

```html
  <div id="clock">
    <div class="time" id="clock-time"></div>
    <div class="day" id="clock-day"></div>
    <div class="date" id="clock-date"></div>
  </div>
```

- [ ] **Step 3: Update `clockTick()` JS to populate the new element**

Find (around line 671):

```js
    function clockTick() {
      const n=new Date();
      $('clock-time').textContent=n.getHours().toString().padStart(2,'0')+':'+n.getMinutes().toString().padStart(2,'0');
      $('clock-date').textContent=n.toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric'});
    }
```

Replace with:

```js
    function clockTick() {
      const n=new Date();
      $('clock-time').textContent=n.getHours().toString().padStart(2,'0')+':'+n.getMinutes().toString().padStart(2,'0');
      $('clock-day').textContent=n.toLocaleDateString('en-US',{weekday:'long'});
      $('clock-date').textContent=n.toLocaleDateString('en-US',{day:'2-digit',month:'long',year:'numeric'});
    }
```

- [ ] **Step 4: Verify visually**

Run: `docker compose up visual-shell` (or whatever the existing dev command is for the visual shell).
Open the URL (typically `http://localhost:3333`).
Expected: top-left shows `14:32` large and dark, with `SUNDAY` in small caps below, then `05 APRIL 2026`. Top-right shows `Samantha` in italic serif, larger and darker than before. All legible from 2m away.

- [ ] **Step 5: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat(visual-shell): enlarge and darken header per design mockup B"
```

---

## Task 16: Visual shell — overlay card component + WS handler

**Files:**
- Modify: `services/visual-shell/index.html`

- [ ] **Step 1: Add overlay card CSS**

Inside the `<style>` block in `services/visual-shell/index.html`, append (before `</style>`):

```css
    /* ─── Overlay card ──────────────────────────────────────────────── */
    #overlay-card {
      position: fixed;
      top: 5.5rem;
      right: 1.6rem;
      width: 280px;
      padding: 1.2rem 1.4rem 1.1rem;
      background: rgba(254,245,237,0.58);
      backdrop-filter: blur(22px);
      -webkit-backdrop-filter: blur(22px);
      border: 1px solid rgba(92,32,48,0.08);
      border-radius: 18px;
      box-shadow: 0 20px 60px rgba(58,15,28,0.18);
      color: #3a0f1c;
      z-index: 40;
      opacity: 0;
      transform: translateY(12px);
      pointer-events: none;
      transition: opacity 0.7s cubic-bezier(0.16,1,0.3,1),
                  transform 0.7s cubic-bezier(0.16,1,0.3,1);
    }
    #overlay-card.visible {
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
    }
    #overlay-card .kicker {
      font-family: 'Outfit', sans-serif;
      font-size: 0.58rem; font-weight: 500;
      letter-spacing: 0.22em; text-transform: uppercase;
      color: #7a3a48;
      margin-bottom: 0.45rem;
    }
    #overlay-card .title {
      font-family: 'Cormorant Garamond', serif;
      font-size: 1.45rem; font-weight: 400;
      line-height: 1.25; color: #3a0f1c;
    }
    #overlay-card .when {
      margin-top: 0.5rem;
      font-family: 'Outfit', sans-serif;
      font-size: 0.72rem; font-weight: 400;
      color: #5c2030; opacity: 0.8;
      letter-spacing: 0.08em;
    }
    #overlay-card ul {
      list-style: none; margin-top: 0.6rem; padding: 0;
    }
    #overlay-card li {
      font-family: 'Cormorant Garamond', serif;
      font-size: 1.05rem;
      padding: 0.25rem 0;
      color: #3a0f1c;
      border-bottom: 1px solid rgba(92,32,48,0.08);
    }
    #overlay-card li.new {
      background: linear-gradient(90deg, rgba(255,220,180,0.5), transparent);
      padding-left: 0.5rem; border-radius: 4px;
      border-bottom-color: transparent;
      font-weight: 500;
    }
    #overlay-card li.new::before { content: '✦ '; color: #c45878; }
    #overlay-card .progress {
      height: 2px;
      background: rgba(92,32,48,0.15);
      border-radius: 2px;
      margin-top: 0.9rem;
      overflow: hidden;
    }
    #overlay-card .progress .bar {
      display: block;
      height: 100%;
      width: 100%;
      background: linear-gradient(90deg, #5c2030, #9a5a68);
      transform-origin: left;
      transform: scaleX(1);
    }
```

- [ ] **Step 2: Add the overlay container to the DOM**

Find the `<div id="cards-container"></div>` line (around line 345). Add immediately after it:

```html
  <div id="overlay-card" aria-live="polite">
    <div class="kicker"></div>
    <div class="title"></div>
    <div class="when"></div>
    <ul class="items"></ul>
    <div class="progress"><span class="bar"></span></div>
  </div>
```

- [ ] **Step 3: Add the overlay component JS module**

Inside the main `<script>` (around line 680, after the `connectWS` function but before `handleEvt`), add:

```js
    // ─── Overlay card component ──────────────────────────────────────
    const Overlay = (() => {
      const el = document.getElementById('overlay-card');
      const kickerEl = el.querySelector('.kicker');
      const titleEl = el.querySelector('.title');
      const whenEl = el.querySelector('.when');
      const listEl = el.querySelector('.items');
      const bar = el.querySelector('.progress .bar');

      let dismissTimer = null;
      let progressStart = 0;
      let progressDuration = 25000;
      let remainingOnPause = null;
      const queue = [];
      let busy = false;

      function kickerText(payload) {
        if (payload.kind === 'list' && payload.list_name) {
          return payload.list_name;
        }
        if (payload.kind === 'schedule_heads_up') return 'Up next';
        return payload.kind;
      }

      function render(payload) {
        kickerEl.textContent = kickerText(payload);
        titleEl.textContent = payload.title || '';
        whenEl.textContent = payload.when || '';
        whenEl.style.display = payload.when ? '' : 'none';

        // List items
        listEl.innerHTML = '';
        if (payload.items && Array.isArray(payload.items)) {
          payload.items.forEach((text, idx) => {
            const li = document.createElement('li');
            li.textContent = text;
            if (idx === payload.highlight_index) li.classList.add('new');
            listEl.appendChild(li);
          });
          listEl.style.display = '';
        } else {
          listEl.style.display = 'none';
        }

        // Progress bar reset
        bar.style.transition = 'none';
        bar.style.transform = 'scaleX(1)';
      }

      function startProgress(durationMs) {
        progressDuration = durationMs;
        progressStart = performance.now();
        // Force reflow so the transition kicks in
        void bar.offsetWidth;
        bar.style.transition = `transform ${durationMs}ms linear`;
        bar.style.transform = 'scaleX(0)';
      }

      function scheduleDismiss(ms) {
        clearTimeout(dismissTimer);
        dismissTimer = setTimeout(dismiss, ms);
      }

      function show(payload) {
        if (busy) {
          queue.push(payload);
          return;
        }
        busy = true;
        render(payload);
        el.classList.add('visible');

        if (payload.chime) playChime();

        const duration = payload.duration_ms || 25000;
        startProgress(duration);
        scheduleDismiss(duration);
      }

      function dismiss() {
        clearTimeout(dismissTimer);
        dismissTimer = null;
        el.classList.remove('visible');
        // After the CSS transition ends, allow the next queued payload
        setTimeout(() => {
          busy = false;
          const next = queue.shift();
          if (next) {
            setTimeout(() => show(next), 400);
          }
        }, 700);
      }

      // Hover pause / click dismiss
      el.addEventListener('mouseenter', () => {
        if (!dismissTimer) return;
        clearTimeout(dismissTimer);
        dismissTimer = null;
        const elapsed = performance.now() - progressStart;
        remainingOnPause = Math.max(0, progressDuration - elapsed);
        // Freeze the progress bar at current width
        const computed = getComputedStyle(bar).transform;
        bar.style.transition = 'none';
        bar.style.transform = computed;
      });
      el.addEventListener('mouseleave', () => {
        if (remainingOnPause == null) return;
        const extended = remainingOnPause + 5000;
        progressStart = performance.now();
        progressDuration = extended;
        void bar.offsetWidth;
        bar.style.transition = `transform ${extended}ms linear`;
        bar.style.transform = 'scaleX(0)';
        scheduleDismiss(extended);
        remainingOnPause = null;
      });
      el.addEventListener('click', dismiss);

      return { show };
    })();
```

- [ ] **Step 4: Dispatch `overlay_card` WS events to the component**

Find the `handleEvt` function (around line 686) and its switch/if block for `d.event`. Add a new case:

```js
      else if (d.event === 'overlay_card') {
        Overlay.show(d);
      }
```

Match the existing dispatch style (if the handler uses `switch`, add a `case 'overlay_card': Overlay.show(d); break;`).

- [ ] **Step 5: Add a placeholder `playChime` stub**

For this task, stub it; the next task fills it in. Above the `Overlay` IIFE, add:

```js
    function playChime() { /* filled in Task 17 */ }
```

- [ ] **Step 6: Visual verification**

Run the visual shell and orchestrator. In a terminal, manually emit a test overlay via the existing `/chat/text` endpoint: send `"add milk to the shopping list"`.
Expected: a translucent card slides in from the right top, shows "shopping" kicker, "Shopping list" title, a single item "milk" highlighted with ✦, progress bar draining, fades out after ~25s. Hover pauses; click dismisses.

- [ ] **Step 7: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat(visual-shell): add overlay card component and WS handler"
```

---

## Task 17: Visual shell — chime fetch + playback

**Files:**
- Modify: `services/visual-shell/index.html`

- [ ] **Step 1: Replace the `playChime` stub with a real implementation**

In `services/visual-shell/index.html`, remove the stub `function playChime() { }` line and add above the `Overlay` IIFE:

```js
    // ─── Chime ───────────────────────────────────────────────────────
    const Chime = (() => {
      let audioCtx = null;
      let buffer = null;

      async function load() {
        try {
          audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          const url = `http://${location.hostname}:8000/static/chime.wav`;
          const resp = await fetch(url);
          if (!resp.ok) throw new Error(`chime fetch: ${resp.status}`);
          const arr = await resp.arrayBuffer();
          buffer = await audioCtx.decodeAudioData(arr);
          console.log('🔔 chime loaded');
        } catch (e) {
          console.warn('chime load failed', e);
        }
      }

      function play() {
        if (!audioCtx || !buffer) return;
        // Resume context on first user-gesture-triggered play (autoplay policy).
        if (audioCtx.state === 'suspended') {
          audioCtx.resume().catch(() => {});
        }
        const src = audioCtx.createBufferSource();
        src.buffer = buffer;
        const gain = audioCtx.createGain();
        gain.gain.value = 0.6;
        src.connect(gain).connect(audioCtx.destination);
        src.start();
      }

      return { load, play };
    })();

    function playChime() { Chime.play(); }
```

- [ ] **Step 2: Load the chime on startup**

Find where the page initializes (search for `connectWS()` call at the bottom of the main script block) and add before it:

```js
    Chime.load();
```

- [ ] **Step 3: Verify in the browser**

Reload the visual shell.
Expected: console shows `🔔 chime loaded`.

Trigger a time-based fire: use `/chat/text` to say `remind me to test in 1 minute`, then wait. When the reminder fires, a chime should play and the overlay card should appear. (If you're impatient, manually insert a row into the DB with `trigger_at` in the past via sqlite3 and wait for the next scheduler tick.)

- [ ] **Step 4: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat(visual-shell): fetch and play chime.wav via Web Audio"
```

---

## Task 18: End-to-end smoke test

**Files:**
- Create: `services/orchestrator/tests/tasks/test_smoke_e2e.py`

Verifies the full happy path from integration → store → scheduler → emit envelope.

- [ ] **Step 1: Write the test**

Create `services/orchestrator/tests/tasks/test_smoke_e2e.py`:

```python
"""End-to-end smoke: create a reminder via the integration, advance the
clock, run one scheduler tick, and verify the envelope is emitted."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time

from integrations.tasks import TasksIntegration
from integrations.tasks.scheduler import run_tick
from integrations.tasks.store import SCHEMA_SQL, TasksStore


@pytest.fixture
def wired(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    store = TasksStore(memory_db)
    integ = TasksIntegration()
    integ.store = store
    integ.tz = "UTC"
    return integ, store


@freeze_time("2026-04-05 16:59:00")  # 1 min before 17:00
async def test_reminder_end_to_end(wired):
    integ, store = wired
    emit = AsyncMock()

    # User creates a reminder for 5pm
    result = await integ.handle_action("add_reminder", "remind me to call mom at 5pm")
    assert result.overlay is not None
    assert result.overlay.kind == "reminder"
    assert result.overlay.chime is False  # creation, not fire

    # DB has it
    pending = store.list_pending_reminders()
    assert len(pending) == 1

    # Advance the clock past 5pm and run a scheduler tick
    with freeze_time("2026-04-05 17:00:05"):
        await run_tick(store, emit, now=datetime(2026, 4, 5, 17, 0, 5, tzinfo=timezone.utc), heads_up_window_min=10, tz="UTC")

    assert emit.await_count == 1
    envelope = emit.await_args.args[0]
    assert envelope["event"] == "overlay_card"
    assert envelope["kind"] == "reminder"
    assert envelope["chime"] is True
    assert envelope["title"] == "call mom"

    # And the reminder is marked fired
    assert store.list_pending_reminders() == []


@freeze_time("2026-04-05 12:00:00")
async def test_list_add_and_show(wired):
    integ, store = wired

    await integ.handle_action("add_to_list", "add milk to shopping")
    await integ.handle_action("add_to_list", "add bread to shopping")

    result = await integ.handle_action("show_list", "what's on my shopping list")
    assert result.overlay is not None
    assert result.overlay.kind == "list"
    assert set(result.overlay.items) == {"milk", "bread"}
    assert result.overlay.highlight_index is None  # show_list does not highlight
```

- [ ] **Step 2: Run the test**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/tasks/test_smoke_e2e.py -v`
Expected: `2 passed`.

- [ ] **Step 3: Run the full suite**

Run: `cd services/orchestrator && PYTHONPATH=. pytest tests/ -v`
Expected: all tests pass (around 55+ total across all task files).

- [ ] **Step 4: Commit**

```bash
git add services/orchestrator/tests/tasks/test_smoke_e2e.py
git commit -m "test(tasks): end-to-end smoke covering create → tick → emit"
```

---

## Task 19: Manual smoke checklist + final polish

No test file — this is a manual pass against the spec's acceptance criteria (§10).

- [ ] **Step 1: Bring up the full stack**

Run: `docker compose up` (or the project's existing dev command).
Wait for orchestrator log: `tasks scheduler started`.
Open the visual shell in the browser.

- [ ] **Step 2: Header legibility check**

Expected: date/day/time top-left and Samantha nameplate top-right are both visibly darker and larger than before. Confirm from ~2m away.

- [ ] **Step 3: Reminder happy path**

Say/type: **"Remind me to test things in one minute."**
Expected:
- Samantha speaks a confirmation.
- A silent card slides in immediately ("Reminder", title "test things", "at HH:MM").
- Card auto-dismisses after ~25s.
- At the one-minute mark, a new card slides in accompanied by a soft chime.

- [ ] **Step 4: List with duplicate**

Say/type: **"Add milk to the shopping list."** → card shows milk highlighted.
Say/type: **"Add Milk to shopping."** → card shows "Milk was already on your shopping list — added again" (verbally) and card shows the list with the second Milk highlighted.
Say/type: **"What's on my shopping list?"** → silent card showing both milks, no highlight.

- [ ] **Step 5: Schedule event + heads-up**

Say/type: **"Meeting with Jussi in 12 minutes."**
Expected: confirmation + card.
Wait ~2 minutes → heads-up card fires with chime at the 10-minute window.
Wait to the start time → start card fires with chime.

- [ ] **Step 6: Recurring event**

Say/type: **"Every weekday at 8 remind me to take vitamins."**
Expected: confirmation + card.
Inspect DB: `sqlite3 config/samantha_memory.db "SELECT title, start_at, recurrence FROM schedule_events;"`
Expected: one row, recurrence = `weekdays`, next `start_at` is the next weekday at 08:00 UTC.

- [ ] **Step 7: Show schedule**

Say/type: **"What's next?"**
Expected: silent card with the nearest upcoming event.

- [ ] **Step 8: Cancel**

Say/type: **"Remind me to X at 9pm."**
Say/type: **"Cancel that."**
Expected: "Cancelled — I won't remind you to X."
Inspect DB: row has `cancelled_at` populated.

- [ ] **Step 9: Reset sanity**

Run: `curl -X POST http://127.0.0.1:8000/reset-all`
Inspect DB: `sqlite3 config/samantha_memory.db "SELECT COUNT(*) FROM reminders; SELECT COUNT(*) FROM schedule_events; SELECT COUNT(*) FROM list_items;"`
Expected: all zero.

- [ ] **Step 10: Restart persistence check**

Add a reminder for 10 minutes from now. Stop the orchestrator (Ctrl+C). Start it again. Wait for the 10-minute mark.
Expected: the reminder still fires exactly once.

- [ ] **Step 11: Final commit**

If any tweaks were needed during manual smoke (e.g., an off-by-one in formatting), commit them:

```bash
git add -A
git commit -m "fix(tasks): address issues found in manual smoke testing"
```

If no tweaks were needed, this step is a no-op.

---

## Spec coverage map

| Spec section | Implementing task(s) |
|---|---|
| §1 Goal | All |
| §2 Non-goals | Enforced by omission |
| §3.1 File layout | Tasks 1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 |
| §3.2 Module boundaries | Tasks 4 (store), 7–8 (parser), 10 (scheduler), 11–13 (integration) |
| §3.3 Data flow | Task 14 (wiring), Task 18 (E2E) |
| §4.0 Legacy migration | Tasks 2, 3 |
| §4.1 New tables | Task 2 |
| §5.1 Keyword triggers | Tasks 11, 12, 13 (registered via IntegrationAction keywords — uses existing IntentRouter scoring) |
| §5.2 LLM fallback classifier | Deferred — YAGNI for v1. Keyword layer via `IntegrationAction.keywords`/`examples` handles the happy path. If needed later, add as a new task; does not block shipping. |
| §5.3 Time parsing | Tasks 7, 8 |
| §5.4 Action contracts | Task 1 (models), 11–13 (handlers) |
| §6.1 Scheduler loop | Task 10 |
| §6.2 WS envelope | Task 1 (models) + Task 10 (scheduler emits) + Task 16 (visual shell dispatch) |
| §6.3 Overlay lifecycle | Task 16 |
| §6.4 Chime | Tasks 9 (synth), 14 (serve), 17 (fetch + play) |
| §7 Header polish | Task 15 |
| §8 Error handling | Tasks 11–13 (clarification paths), Task 10 (tick exception), Task 16 (WS drop tolerance) |
| §9 Testing strategy | Tasks 4–13, 18 (~55 tests total) |
| §10 Acceptance criteria | Task 19 (manual smoke) |

**Deviation from spec, documented:**
- Spec §5.2 LLM classifier → not implemented in v1. Reason: the existing `IntentRouter` keyword/example scoring at `services/orchestrator/intents/__init__.py` covers the trigger phrases listed in the spec once `TasksIntegration` registers rich `keywords` and `examples`. Adding a second LLM-based classifier doubles the latency budget and duplicates a mechanism that already works. If real-world use reveals ambiguous phrasings the keyword layer can't handle, add the LLM classifier as a follow-up task — it's additive and non-blocking.
- Spec §6.2 envelope field `type` → changed to `event` to match the existing visual shell dispatch convention in `services/visual-shell/index.html` (`d.event`). All other envelope fields are unchanged.
