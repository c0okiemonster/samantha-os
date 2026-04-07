# Memory Timeline UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-screen Memory Timeline overlay in the visual shell that renders six types of Samantha's stored knowledge (facts, observations, episodes, moods, entities, news) as a chronological stream with filter chips, day grouping, hover-to-delete with 5-second undo.

**Architecture:** New pure module `services/orchestrator/memory/timeline.py` with `build_timeline()`, `soft_delete_entry()`, and `restore_entry()` functions operating on an existing sqlite3 connection. Three new HTTP endpoints on `main.py`: `GET /memory/timeline`, `DELETE /memory/entry/{entry_type}/{entry_id}`, `POST /memory/entry/{entry_type}/{entry_id}/restore`. A one-shot `ALTER TABLE` migration adds `deleted_at` to five tables that don't already have it. Visual shell gains a `#timeline-toggle` button (inline-SVG matching the mic/text icon language), a `#timeline-panel` full-viewport overlay, and a `Timeline` IIFE module with fetch/render/delete/undo/keyboard-shortcut logic.

**Tech Stack:** Python 3 + FastAPI (existing), `sqlite3` stdlib, `pytest` + `fastapi.testclient.TestClient` (already available via httpx), vanilla JS + `localStorage` + `fetch` on the visual shell. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-05-memory-timeline-design.md`

---

## Conventions

- **Test runner:** `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest <args>`
- **Tests live at** `services/orchestrator/tests/memory/test_<thing>.py`
- **Branch:** all work lands on `feat/wake-word-and-timeline` (already checked out; timeline spec + vision icon fix already committed).
- **Commits:** conventional prefixes — `feat:`, `fix:`, `test:`, `chore:`, `docs:`.
- **Entry id format everywhere:** `"<type>:<numeric_id>"` as a string. Backend splits, frontend treats as opaque.

---

## File Structure

**Create:**

```
services/orchestrator/memory/timeline.py              pure functions: build, soft_delete, restore
services/orchestrator/tests/memory/__init__.py        (empty package marker)
services/orchestrator/tests/memory/test_timeline_migration.py
services/orchestrator/tests/memory/test_timeline_query.py
services/orchestrator/tests/memory/test_timeline_delete.py
services/orchestrator/tests/memory/test_timeline_restore.py
services/orchestrator/tests/memory/test_timeline_endpoints.py
```

**Modify:**

```
services/orchestrator/memory/__init__.py              + ALTER TABLE deleted_at on 5 tables
services/orchestrator/main.py                         + 3 HTTP endpoints
services/visual-shell/index.html                      + toggle button (SVG),
                                                        + panel markup + CSS,
                                                        + Timeline IIFE,
                                                        + keyboard shortcut
```

---

## Task 1: Migration — add `deleted_at` to five tables

**Files:**
- Modify: `services/orchestrator/memory/__init__.py`
- Create: `services/orchestrator/tests/memory/__init__.py` (empty)
- Create: `services/orchestrator/tests/memory/test_timeline_migration.py`

- [ ] **Step 1: Create empty package marker**

Create `services/orchestrator/tests/memory/__init__.py` with content: (empty file)

- [ ] **Step 2: Write the failing test**

Create `services/orchestrator/tests/memory/test_timeline_migration.py`:

```python
from memory import ConversationMemory


def _columns(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_deleted_at_on_all_timelined_tables(tmp_path):
    m = ConversationMemory(db_path=str(tmp_path / "m.db"))
    for table in ("facts", "entities", "episodes", "mood_log",
                  "news_digests", "observations"):
        cols = _columns(m.conn, table)
        assert "deleted_at" in cols, f"missing deleted_at on {table}"


def test_migration_is_idempotent(tmp_path):
    """Running _create_tables twice must not raise and must not lose the column."""
    db = tmp_path / "m.db"
    m1 = ConversationMemory(db_path=str(db))
    # Second construction runs _create_tables again
    m2 = ConversationMemory(db_path=str(db))
    cols = _columns(m2.conn, "facts")
    assert "deleted_at" in cols


def test_existing_data_preserved_after_migration(tmp_path):
    """An existing DB with rows must survive the ALTER TABLE additions."""
    import sqlite3
    db = tmp_path / "m.db"
    # Create a DB with only the old schema (no deleted_at)
    pre = sqlite3.connect(str(db))
    pre.executescript("""
        CREATE TABLE facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL DEFAULT 'user',
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 0.8,
            source TEXT DEFAULT 'conversation',
            learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_referenced TIMESTAMP,
            UNIQUE(subject, category, key)
        );
        INSERT INTO facts (category, key, value) VALUES ('personal', 'color', 'blue');
    """)
    pre.commit()
    pre.close()

    # Now run the real migration
    m = ConversationMemory(db_path=str(db))
    cols = {r[1] for r in m.conn.execute("PRAGMA table_info(facts)").fetchall()}
    assert "deleted_at" in cols
    # Data is still there
    row = m.conn.execute("SELECT category, key, value FROM facts").fetchone()
    assert row is not None
    assert row[2] == "blue"
```

- [ ] **Step 3: Run the tests — expect fails**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_migration.py -v`
Expected: 3 failures — `deleted_at` missing on facts/entities/episodes/mood_log/news_digests.

- [ ] **Step 4: Add the migration block to `_create_tables`**

Find `ConversationMemory._create_tables` in `services/orchestrator/memory/__init__.py`. It already has a migrations block (search for `# Migration: add subject column to facts` or similar). After the last existing migration try/except, append:

```python
        # Migration: add deleted_at to timelined tables for the Memory Timeline UI
        for _tbl in ("facts", "entities", "episodes", "mood_log", "news_digests"):
            try:
                self.conn.execute(f"ALTER TABLE {_tbl} ADD COLUMN deleted_at TIMESTAMP")
                self.conn.commit()
            except Exception:
                pass  # column already exists
```

(Note: `observations` already has `deleted_at` from the vision feature — do NOT re-add it.)

- [ ] **Step 5: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_migration.py -v`
Expected: `3 passed`.

Run the full suite to catch regressions:
`cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/ -v`
Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/memory/__init__.py \
        services/orchestrator/tests/memory/__init__.py \
        services/orchestrator/tests/memory/test_timeline_migration.py
git commit -m "feat(memory): add deleted_at to timelined tables for soft-delete"
```

---

## Task 2: `timeline.py` — `build_timeline` core

**Files:**
- Create: `services/orchestrator/memory/timeline.py`
- Create: `services/orchestrator/tests/memory/test_timeline_query.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/memory/test_timeline_query.py`:

```python
"""Tests for timeline.build_timeline against a fully-seeded in-memory DB."""
from datetime import datetime, timezone

import pytest

from memory.timeline import build_timeline, VALID_TYPES


FULL_SCHEMA = """
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL DEFAULT 'user',
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    source TEXT DEFAULT 'conversation',
    learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_referenced TIMESTAMP,
    deleted_at TIMESTAMP,
    UNIQUE(subject, category, key)
);
CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    relation TEXT,
    aliases TEXT DEFAULT '[]',
    first_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE TABLE episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    topics TEXT DEFAULT '[]',
    mood_arc TEXT DEFAULT 'neutral',
    message_count INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    ended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    unresolved_threads TEXT DEFAULT '[]',
    deleted_at TIMESTAMP
);
CREATE TABLE mood_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_mood TEXT,
    samantha_mood TEXT,
    trigger TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sentiment TEXT DEFAULT 'neutral',
    intensity REAL DEFAULT 0.5,
    note TEXT DEFAULT '',
    deleted_at TIMESTAMP
);
CREATE TABLE news_digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    sentiment TEXT DEFAULT 'neutral',
    notable_items TEXT DEFAULT '[]',
    reaction TEXT DEFAULT '',
    sources TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_description TEXT NOT NULL,
    spoken_text TEXT NOT NULL,
    user_trigger TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
"""


@pytest.fixture
def db(memory_db):
    memory_db.executescript(FULL_SCHEMA)
    return memory_db


def _seed_all(db):
    """Seed one row in each of the 6 tables at staggered timestamps."""
    db.execute(
        "INSERT INTO facts (subject, category, key, value, learned_at) "
        "VALUES ('user', 'personal', 'color', 'blue', '2026-04-05T10:00:00+00:00')"
    )
    db.execute(
        "INSERT INTO entities (name, type, relation, first_mentioned) "
        "VALUES ('Jussi', 'pet', 'cat', '2026-04-05T11:00:00+00:00')"
    )
    db.execute(
        "INSERT INTO episodes (summary, topics, ended_at) "
        "VALUES ('morning chat', '[\"coffee\"]', '2026-04-05T12:00:00+00:00')"
    )
    db.execute(
        "INSERT INTO mood_log (user_mood, samantha_mood, trigger, timestamp) "
        "VALUES ('curious', 'warm', 'asked about', '2026-04-05T13:00:00+00:00')"
    )
    db.execute(
        "INSERT INTO news_digests (summary, sentiment, created_at) "
        "VALUES ('Tech roundup', 'mixed', '2026-04-05T14:00:00+00:00')"
    )
    db.execute(
        "INSERT INTO observations (raw_description, spoken_text, user_trigger, created_at) "
        "VALUES ('a cup of coffee', 'I see coffee', 'what do you see?', '2026-04-05T15:00:00+00:00')"
    )
    db.commit()


def test_valid_types_constant():
    assert VALID_TYPES == {"fact", "entity", "observation", "episode", "mood", "news"}


def test_all_types_returned_in_desc_ts_order(db):
    _seed_all(db)
    result = build_timeline(db, types=VALID_TYPES, limit=100)
    assert len(result["entries"]) == 6
    timestamps = [e["ts"] for e in result["entries"]]
    assert timestamps == sorted(timestamps, reverse=True)
    # Types present
    types = {e["type"] for e in result["entries"]}
    assert types == VALID_TYPES
    assert result["has_more"] is False
    assert result["next_before"] is None


def test_type_filtering(db):
    _seed_all(db)
    result = build_timeline(db, types={"fact", "observation"}, limit=100)
    types = {e["type"] for e in result["entries"]}
    assert types == {"fact", "observation"}
    assert len(result["entries"]) == 2


def test_entry_id_format(db):
    _seed_all(db)
    result = build_timeline(db, types=VALID_TYPES, limit=100)
    for entry in result["entries"]:
        assert ":" in entry["id"]
        entry_type, _, num_id = entry["id"].partition(":")
        assert entry_type == entry["type"]
        assert num_id.isdigit()


def test_entry_shape(db):
    _seed_all(db)
    result = build_timeline(db, types={"observation"}, limit=100)
    entry = result["entries"][0]
    assert set(entry.keys()) >= {"id", "type", "ts", "title", "body", "meta"}
    assert entry["type"] == "observation"
    assert entry["body"] == "a cup of coffee"
    assert isinstance(entry["meta"], dict)
    assert entry["meta"]["spoken_text"] == "I see coffee"
    assert entry["meta"]["user_trigger"] == "what do you see?"


def test_fact_entry_projection(db):
    _seed_all(db)
    result = build_timeline(db, types={"fact"}, limit=100)
    entry = result["entries"][0]
    assert entry["body"] == "blue"
    assert "color" in entry["title"]
    assert entry["meta"]["subject"] == "user"
    assert entry["meta"]["category"] == "personal"


def test_deleted_rows_excluded(db):
    _seed_all(db)
    db.execute("UPDATE facts SET deleted_at = CURRENT_TIMESTAMP WHERE key = 'color'")
    db.commit()
    result = build_timeline(db, types={"fact"}, limit=100)
    assert result["entries"] == []


def test_limit_and_has_more(db):
    _seed_all(db)
    result = build_timeline(db, types=VALID_TYPES, limit=3)
    assert len(result["entries"]) == 3
    assert result["has_more"] is True
    assert result["next_before"] is not None


def test_pagination_via_before(db):
    _seed_all(db)
    page1 = build_timeline(db, types=VALID_TYPES, limit=3)
    assert len(page1["entries"]) == 3
    page2 = build_timeline(db, types=VALID_TYPES, limit=3, before=page1["next_before"])
    assert len(page2["entries"]) == 3
    # No overlap
    ids1 = {e["id"] for e in page1["entries"]}
    ids2 = {e["id"] for e in page2["entries"]}
    assert ids1.isdisjoint(ids2)
    # Second page exhausts
    assert page2["has_more"] is False


def test_empty_types_returns_empty_list(db):
    _seed_all(db)
    result = build_timeline(db, types=set(), limit=100)
    assert result["entries"] == []
    assert result["has_more"] is False


def test_invalid_type_raises(db):
    with pytest.raises(ValueError):
        build_timeline(db, types={"fact", "bogus"}, limit=100)
```

- [ ] **Step 2: Run the test — expect ModuleNotFoundError**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_query.py -v`
Expected: `ModuleNotFoundError: No module named 'memory.timeline'`

- [ ] **Step 3: Create `timeline.py` with `build_timeline`**

Create `services/orchestrator/memory/timeline.py`:

```python
"""Pure functions for the Memory Timeline UI.

Reads the existing memory tables and normalizes rows from six different
sources into a single unified entry shape. Supports soft-delete and
cursor pagination via an ISO 8601 `before` timestamp.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional


VALID_TYPES: frozenset[str] = frozenset({
    "fact", "entity", "observation", "episode", "mood", "news",
})


# ─── Per-type projections ───────────────────────────────────────────────
# Each projection is: (table, ts_col, row_to_entry_fn)

def _fact_to_entry(row: sqlite3.Row) -> dict:
    subj = row["subject"] or "user"
    cat = row["category"] or ""
    key = row["key"] or ""
    return {
        "id": f"fact:{row['id']}",
        "type": "fact",
        "ts": _iso(row["learned_at"]),
        "title": f"{subj} · {cat} · {key}".strip(" ·"),
        "body": row["value"] or "",
        "meta": {
            "subject": subj,
            "category": cat,
            "confidence": row["confidence"],
            "source": row["source"],
        },
    }


def _entity_to_entry(row: sqlite3.Row) -> dict:
    etype = row["type"] or ""
    relation = row["relation"] or ""
    title = etype + (" · " + relation if relation else "")
    try:
        aliases = json.loads(row["aliases"] or "[]")
    except Exception:
        aliases = []
    return {
        "id": f"entity:{row['id']}",
        "type": "entity",
        "ts": _iso(row["first_mentioned"]),
        "title": title or "entity",
        "body": row["name"] or "",
        "meta": {
            "aliases": aliases,
            "last_mentioned": _iso(row["last_mentioned"]),
        },
    }


def _observation_to_entry(row: sqlite3.Row) -> dict:
    return {
        "id": f"observation:{row['id']}",
        "type": "observation",
        "ts": _iso(row["created_at"]),
        "title": "What she saw",
        "body": row["raw_description"] or "",
        "meta": {
            "spoken_text": row["spoken_text"] or "",
            "user_trigger": row["user_trigger"] or "",
        },
    }


def _episode_to_entry(row: sqlite3.Row) -> dict:
    try:
        topics = json.loads(row["topics"] or "[]")
    except Exception:
        topics = []
    try:
        threads = json.loads(row["unresolved_threads"] or "[]")
    except Exception:
        threads = []
    title = ", ".join(topics[:3]) if topics else "Conversation"
    if len(topics) > 3:
        title += f" (+{len(topics) - 3})"
    return {
        "id": f"episode:{row['id']}",
        "type": "episode",
        "ts": _iso(row["ended_at"]),
        "title": title,
        "body": row["summary"] or "",
        "meta": {
            "mood_arc": row["mood_arc"],
            "message_count": row["message_count"],
            "unresolved_threads": threads,
        },
    }


def _mood_to_entry(row: sqlite3.Row) -> dict:
    user_m = row["user_mood"] or "?"
    sam_m = row["samantha_mood"] or "?"
    return {
        "id": f"mood:{row['id']}",
        "type": "mood",
        "ts": _iso(row["timestamp"]),
        "title": f"{user_m} → {sam_m}",
        "body": row["trigger"] or "",
        "meta": {
            "sentiment": row["sentiment"],
            "intensity": row["intensity"],
            "note": row["note"],
        },
    }


def _news_to_entry(row: sqlite3.Row) -> dict:
    try:
        sources = json.loads(row["sources"] or "[]")
    except Exception:
        sources = []
    return {
        "id": f"news:{row['id']}",
        "type": "news",
        "ts": _iso(row["created_at"]),
        "title": "News digest",
        "body": row["summary"] or "",
        "meta": {
            "sentiment": row["sentiment"],
            "reaction": row["reaction"],
            "sources": sources,
        },
    }


# ─── Query config per type ──────────────────────────────────────────────

# type → (table, ts_column, projection_fn, column_list_for_select)
_PROJECTIONS: dict[str, tuple[str, str, Any, str]] = {
    "fact": (
        "facts", "learned_at", _fact_to_entry,
        "id, subject, category, key, value, confidence, source, learned_at",
    ),
    "entity": (
        "entities", "first_mentioned", _entity_to_entry,
        "id, name, type, relation, aliases, first_mentioned, last_mentioned",
    ),
    "observation": (
        "observations", "created_at", _observation_to_entry,
        "id, raw_description, spoken_text, user_trigger, created_at",
    ),
    "episode": (
        "episodes", "ended_at", _episode_to_entry,
        "id, summary, topics, mood_arc, message_count, ended_at, unresolved_threads",
    ),
    "mood": (
        "mood_log", "timestamp", _mood_to_entry,
        "id, user_mood, samantha_mood, trigger, timestamp, sentiment, intensity, note",
    ),
    "news": (
        "news_digests", "created_at", _news_to_entry,
        "id, summary, sentiment, reaction, sources, created_at",
    ),
}


# ─── Helpers ────────────────────────────────────────────────────────────

def _iso(s: Optional[str]) -> Optional[str]:
    """Coerce a sqlite TIMESTAMP (string) into a canonical ISO 8601 UTC string."""
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace(" ", "T"))
    except ValueError:
        return str(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# ─── Public API ─────────────────────────────────────────────────────────

def build_timeline(
    conn: sqlite3.Connection,
    types: set[str] | frozenset[str],
    limit: int = 100,
    before: Optional[str] = None,
) -> dict:
    """Run N queries (one per requested type), merge-sort by timestamp DESC,
    return up to `limit` entries plus a pagination cursor.

    `before` is an ISO 8601 string; rows with ts strictly less than `before`
    are returned (used for "load older" pagination).

    Raises ValueError if `types` contains an unknown type name.
    """
    if not types:
        return {"entries": [], "has_more": False, "next_before": None}

    unknown = set(types) - VALID_TYPES
    if unknown:
        raise ValueError(f"Unknown entry types: {sorted(unknown)}")

    conn.row_factory = sqlite3.Row

    collected: list[dict] = []
    for type_name in types:
        table, ts_col, projection, col_list = _PROJECTIONS[type_name]
        sql = (
            f"SELECT {col_list} FROM {table} "
            f"WHERE deleted_at IS NULL "
            f"AND (? IS NULL OR {ts_col} < ?) "
            f"ORDER BY {ts_col} DESC "
            f"LIMIT ?"
        )
        rows = conn.execute(sql, (before, before, limit + 1)).fetchall()
        for row in rows:
            collected.append(projection(row))

    # Merge sort by ts desc. Some rows may have None ts — push them to the end.
    collected.sort(key=lambda e: e["ts"] or "", reverse=True)

    has_more = len(collected) > limit
    entries = collected[:limit]
    next_before: Optional[str] = None
    if has_more and entries:
        next_before = entries[-1]["ts"]

    return {
        "entries": entries,
        "has_more": has_more,
        "next_before": next_before,
    }
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_query.py -v`
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/memory/timeline.py \
        services/orchestrator/tests/memory/test_timeline_query.py
git commit -m "feat(memory): add timeline.py with build_timeline query layer"
```

---

## Task 3: `timeline.py` — `soft_delete_entry` and `restore_entry`

**Files:**
- Modify: `services/orchestrator/memory/timeline.py`
- Create: `services/orchestrator/tests/memory/test_timeline_delete.py`
- Create: `services/orchestrator/tests/memory/test_timeline_restore.py`

- [ ] **Step 1: Write delete tests**

Create `services/orchestrator/tests/memory/test_timeline_delete.py`:

```python
import pytest

from memory.timeline import VALID_TYPES, build_timeline, soft_delete_entry


FULL_SCHEMA = """
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL DEFAULT 'user',
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    source TEXT DEFAULT 'conversation',
    learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_referenced TIMESTAMP,
    deleted_at TIMESTAMP,
    UNIQUE(subject, category, key)
);
CREATE TABLE entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    relation TEXT,
    aliases TEXT DEFAULT '[]',
    first_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE TABLE episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    topics TEXT DEFAULT '[]',
    mood_arc TEXT DEFAULT 'neutral',
    message_count INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    ended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    unresolved_threads TEXT DEFAULT '[]',
    deleted_at TIMESTAMP
);
CREATE TABLE mood_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_mood TEXT,
    samantha_mood TEXT,
    trigger TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sentiment TEXT DEFAULT 'neutral',
    intensity REAL DEFAULT 0.5,
    note TEXT DEFAULT '',
    deleted_at TIMESTAMP
);
CREATE TABLE news_digests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    sentiment TEXT DEFAULT 'neutral',
    notable_items TEXT DEFAULT '[]',
    reaction TEXT DEFAULT '',
    sources TEXT DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
CREATE TABLE observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_description TEXT NOT NULL,
    spoken_text TEXT NOT NULL,
    user_trigger TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
);
"""


@pytest.fixture
def db(memory_db):
    memory_db.executescript(FULL_SCHEMA)
    return memory_db


def test_delete_fact(db):
    db.execute(
        "INSERT INTO facts (category, key, value) VALUES ('personal', 'color', 'blue')"
    )
    db.commit()
    assert soft_delete_entry(db, "fact", 1) is True
    assert build_timeline(db, types={"fact"}, limit=10)["entries"] == []


def test_delete_entity(db):
    db.execute("INSERT INTO entities (name, type) VALUES ('Jussi', 'pet')")
    db.commit()
    assert soft_delete_entry(db, "entity", 1) is True
    assert build_timeline(db, types={"entity"}, limit=10)["entries"] == []


def test_delete_observation(db):
    db.execute(
        "INSERT INTO observations (raw_description, spoken_text, user_trigger) "
        "VALUES ('a desk', 'I see', 'look?')"
    )
    db.commit()
    assert soft_delete_entry(db, "observation", 1) is True
    assert build_timeline(db, types={"observation"}, limit=10)["entries"] == []


def test_delete_episode(db):
    db.execute("INSERT INTO episodes (summary) VALUES ('chat')")
    db.commit()
    assert soft_delete_entry(db, "episode", 1) is True
    assert build_timeline(db, types={"episode"}, limit=10)["entries"] == []


def test_delete_mood(db):
    db.execute(
        "INSERT INTO mood_log (user_mood, samantha_mood) VALUES ('curious', 'warm')"
    )
    db.commit()
    assert soft_delete_entry(db, "mood", 1) is True
    assert build_timeline(db, types={"mood"}, limit=10)["entries"] == []


def test_delete_news(db):
    db.execute("INSERT INTO news_digests (summary) VALUES ('headlines')")
    db.commit()
    assert soft_delete_entry(db, "news", 1) is True
    assert build_timeline(db, types={"news"}, limit=10)["entries"] == []


def test_delete_invalid_type_raises(db):
    with pytest.raises(ValueError):
        soft_delete_entry(db, "bogus", 1)


def test_delete_missing_id_returns_false(db):
    # No row with id=999 exists
    assert soft_delete_entry(db, "fact", 999) is False


def test_delete_is_idempotent(db):
    db.execute("INSERT INTO facts (category, key, value) VALUES ('c', 'k', 'v')")
    db.commit()
    assert soft_delete_entry(db, "fact", 1) is True
    # Second delete: already soft-deleted, returns False (no row updated)
    assert soft_delete_entry(db, "fact", 1) is False
    # Still excluded from timeline
    assert build_timeline(db, types={"fact"}, limit=10)["entries"] == []
```

- [ ] **Step 2: Run — expect ImportError for `soft_delete_entry`**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_delete.py -v`

- [ ] **Step 3: Add `soft_delete_entry` and `restore_entry` to `timeline.py`**

Append to `services/orchestrator/memory/timeline.py` (at the bottom, after `build_timeline`):

```python
# ─── Soft delete / restore ──────────────────────────────────────────────

# type → table (for delete/restore; we don't need the projection here)
_TABLE_FOR_TYPE: dict[str, str] = {
    t: _PROJECTIONS[t][0] for t in VALID_TYPES
}


def _check_type(entry_type: str) -> str:
    if entry_type not in VALID_TYPES:
        raise ValueError(f"Unknown entry type: {entry_type!r}")
    return _TABLE_FOR_TYPE[entry_type]


def soft_delete_entry(
    conn: sqlite3.Connection,
    entry_type: str,
    entry_id: int,
) -> bool:
    """Set deleted_at on the target row. Returns True if a row was updated,
    False if the id did not exist OR was already soft-deleted. Raises
    ValueError for unknown type."""
    table = _check_type(entry_type)
    cur = conn.execute(
        f"UPDATE {table} SET deleted_at = CURRENT_TIMESTAMP "
        f"WHERE id = ? AND deleted_at IS NULL",
        (entry_id,),
    )
    conn.commit()
    return cur.rowcount > 0


def restore_entry(
    conn: sqlite3.Connection,
    entry_type: str,
    entry_id: int,
) -> bool:
    """Clear deleted_at on the target row. Returns True if a row was updated,
    False if the id did not exist OR was not soft-deleted. Raises ValueError
    for unknown type."""
    table = _check_type(entry_type)
    cur = conn.execute(
        f"UPDATE {table} SET deleted_at = NULL "
        f"WHERE id = ? AND deleted_at IS NOT NULL",
        (entry_id,),
    )
    conn.commit()
    return cur.rowcount > 0
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_delete.py -v`
Expected: `9 passed`.

- [ ] **Step 5: Write restore tests**

Create `services/orchestrator/tests/memory/test_timeline_restore.py`:

```python
import pytest

from memory.timeline import build_timeline, restore_entry, soft_delete_entry


SCHEMA = """
CREATE TABLE facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL DEFAULT 'user',
    category TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    source TEXT DEFAULT 'conversation',
    learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_referenced TIMESTAMP,
    deleted_at TIMESTAMP,
    UNIQUE(subject, category, key)
);
"""


@pytest.fixture
def db(memory_db):
    memory_db.executescript(SCHEMA)
    return memory_db


def test_restore_after_delete(db):
    db.execute("INSERT INTO facts (category, key, value) VALUES ('c', 'k', 'v')")
    db.commit()
    soft_delete_entry(db, "fact", 1)
    assert build_timeline(db, types={"fact"}, limit=10)["entries"] == []
    assert restore_entry(db, "fact", 1) is True
    assert len(build_timeline(db, types={"fact"}, limit=10)["entries"]) == 1


def test_restore_non_deleted_is_noop(db):
    db.execute("INSERT INTO facts (category, key, value) VALUES ('c', 'k', 'v')")
    db.commit()
    assert restore_entry(db, "fact", 1) is False


def test_restore_missing_id_is_noop(db):
    assert restore_entry(db, "fact", 999) is False


def test_restore_invalid_type_raises(db):
    with pytest.raises(ValueError):
        restore_entry(db, "bogus", 1)
```

- [ ] **Step 6: Run restore tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_restore.py -v`
Expected: `4 passed`.

- [ ] **Step 7: Run full suite**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/ -v`
Expected: all previous tests still pass.

- [ ] **Step 8: Commit**

```bash
git add services/orchestrator/memory/timeline.py \
        services/orchestrator/tests/memory/test_timeline_delete.py \
        services/orchestrator/tests/memory/test_timeline_restore.py
git commit -m "feat(memory): add soft_delete_entry and restore_entry to timeline.py"
```

---

## Task 4: HTTP endpoints on main.py

**Files:**
- Modify: `services/orchestrator/main.py`
- Create: `services/orchestrator/tests/memory/test_timeline_endpoints.py`

- [ ] **Step 1: Write endpoint tests using FastAPI TestClient**

Create `services/orchestrator/tests/memory/test_timeline_endpoints.py`:

```python
"""HTTP endpoint tests for /memory/timeline and /memory/entry/..."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient against the real app with a fresh on-disk memory DB."""
    # Ensure orchestrator uses an isolated DB for this test
    import os
    os.environ["SETTINGS_FILE"] = "/tmp/__nonexistent__.yml"  # forces defaults
    # Import AFTER env is set
    from main import app, state
    from memory import ConversationMemory
    # Point state.memory at a fresh tmp DB
    state.memory = ConversationMemory(db_path=str(tmp_path / "m.db"))
    yield TestClient(app)
    state.memory.close()
    state.memory = None


def _seed_fact(state_memory, key: str, value: str):
    state_memory.conn.execute(
        "INSERT INTO facts (subject, category, key, value) VALUES ('user', 'personal', ?, ?)",
        (key, value),
    )
    state_memory.conn.commit()


def test_timeline_get_happy_path(client):
    from main import state
    _seed_fact(state.memory, "color", "blue")
    _seed_fact(state.memory, "food", "sushi")

    r = client.get("/memory/timeline?types=fact&limit=10")
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    assert len(data["entries"]) == 2
    assert all(e["type"] == "fact" for e in data["entries"])


def test_timeline_get_invalid_type(client):
    r = client.get("/memory/timeline?types=bogus&limit=10")
    assert r.status_code == 400


def test_timeline_get_no_types(client):
    r = client.get("/memory/timeline?types=&limit=10")
    # Empty types string → empty result or 400 — the endpoint must handle it
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert r.json()["entries"] == []


def test_delete_fact_via_endpoint(client):
    from main import state
    _seed_fact(state.memory, "color", "blue")
    r = client.delete("/memory/entry/fact/1")
    assert r.status_code == 204
    # Not visible in timeline
    r2 = client.get("/memory/timeline?types=fact")
    assert r2.json()["entries"] == []


def test_delete_invalid_type_returns_400(client):
    r = client.delete("/memory/entry/bogus/1")
    assert r.status_code == 400


def test_delete_missing_id_is_idempotent(client):
    r = client.delete("/memory/entry/fact/999")
    assert r.status_code == 204


def test_restore_after_delete(client):
    from main import state
    _seed_fact(state.memory, "color", "blue")
    client.delete("/memory/entry/fact/1")
    r = client.post("/memory/entry/fact/1/restore")
    assert r.status_code == 204
    entries = client.get("/memory/timeline?types=fact").json()["entries"]
    assert len(entries) == 1


def test_restore_not_deleted_is_idempotent(client):
    from main import state
    _seed_fact(state.memory, "color", "blue")
    r = client.post("/memory/entry/fact/1/restore")
    assert r.status_code == 204
```

- [ ] **Step 2: Run — expect failures (endpoints don't exist yet)**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_endpoints.py -v`

- [ ] **Step 3: Add the three endpoints to main.py**

Find the existing `@app.get("/memory")` handler in `services/orchestrator/main.py` (around line 817). Immediately AFTER that handler (and the `/memory/search` handler right below it), add:

```python
@app.get("/memory/timeline")
async def get_memory_timeline(types: str = "", limit: int = 100, before: str | None = None):
    """Return a chronological timeline of Samantha's stored knowledge.

    Query params:
      types: comma-separated list of entry types (fact, entity, observation,
             episode, mood, news). Empty string returns empty list.
      limit: maximum number of entries to return (1-500, default 100).
      before: ISO 8601 timestamp cursor for pagination; returns entries with
              ts strictly less than this value.
    """
    if state.memory is None:
        return {"entries": [], "has_more": False, "next_before": None}

    from memory.timeline import build_timeline, VALID_TYPES
    from fastapi import HTTPException

    limit = max(1, min(500, int(limit)))

    type_set = {t.strip() for t in types.split(",") if t.strip()}
    unknown = type_set - VALID_TYPES
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown entry types: {sorted(unknown)}",
        )

    try:
        result = build_timeline(
            state.memory.conn,
            types=type_set,
            limit=limit,
            before=before,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@app.delete("/memory/entry/{entry_type}/{entry_id}", status_code=204)
async def delete_memory_entry(entry_type: str, entry_id: int):
    """Soft-delete a memory entry. Idempotent — missing row is a no-op 204."""
    if state.memory is None:
        return

    from memory.timeline import soft_delete_entry
    from fastapi import HTTPException

    try:
        soft_delete_entry(state.memory.conn, entry_type, entry_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/memory/entry/{entry_type}/{entry_id}/restore", status_code=204)
async def restore_memory_entry(entry_type: str, entry_id: int):
    """Restore a soft-deleted memory entry. Idempotent — non-deleted row is a no-op 204."""
    if state.memory is None:
        return

    from memory.timeline import restore_entry
    from fastapi import HTTPException

    try:
        restore_entry(state.memory.conn, entry_type, entry_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

FastAPI 204 responses use `status_code=204` on the decorator and simply return (no body).

- [ ] **Step 4: Run endpoint tests — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/memory/test_timeline_endpoints.py -v`
Expected: 8 passed.

- [ ] **Step 5: Run full suite**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/ -v`

- [ ] **Step 6: Live smoke test**

Build and start:

```bash
cd /Users/lenny/github/emplex/samantha-os
docker compose build orchestrator && docker compose up -d orchestrator
sleep 4
curl -s 'http://127.0.0.1:8000/memory/timeline?types=fact,observation,episode,mood&limit=5' | python3 -m json.tool | head -30
```

Expected: JSON with `entries`, `has_more`, `next_before` fields. Some entries may be present depending on your local DB state.

- [ ] **Step 7: Commit**

```bash
git add services/orchestrator/main.py \
        services/orchestrator/tests/memory/test_timeline_endpoints.py
git commit -m "feat(orchestrator): add /memory/timeline GET + DELETE/restore endpoints"
```

---

## Task 5: Visual shell — toggle button + panel CSS + DOM

**Files:**
- Modify: `services/visual-shell/index.html`

No automated tests. Purely visual/structural.

- [ ] **Step 1: Add toggle CSS (reuse the existing vision toggle styling pattern)**

In the `<style>` block, find the existing `#vision-toggle` rule (should be around line 405). Add the `#timeline-toggle` rules **immediately after** the `#vision-toggle.active` + `@keyframes visionGlow` block. Also rename `visionGlow` → `toggleGlow` so both buttons share it.

Replace:

```css
    #vision-toggle.active {
      opacity: 1;
      background: rgba(196, 88, 120, 0.25);
      border-color: rgba(196, 88, 120, 0.55);
      box-shadow: 0 0 12px rgba(196, 88, 120, 0.5);
      animation: visionGlow 2.4s ease-in-out infinite;
    }
    @keyframes visionGlow {
      0%, 100% { box-shadow: 0 0 10px rgba(196, 88, 120, 0.4); }
      50%      { box-shadow: 0 0 18px rgba(196, 88, 120, 0.75); }
    }
```

With:

```css
    #vision-toggle.active {
      opacity: 1;
      background: rgba(196, 88, 120, 0.25);
      border-color: rgba(196, 88, 120, 0.55);
      box-shadow: 0 0 12px rgba(196, 88, 120, 0.5);
      animation: toggleGlow 2.4s ease-in-out infinite;
    }
    @keyframes toggleGlow {
      0%, 100% { box-shadow: 0 0 10px rgba(196, 88, 120, 0.4); }
      50%      { box-shadow: 0 0 18px rgba(196, 88, 120, 0.75); }
    }

    /* ─── Memory timeline toggle ─────────────────────────────────────── */
    #timeline-toggle {
      position: fixed;
      top: 3.8rem;
      right: 6rem;
      z-index: 50;
      width: 2.4rem;
      height: 2.4rem;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: 1px solid rgba(58, 15, 28, 0.25);
      border-radius: 50%;
      background: rgba(254, 245, 237, 0.45);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      color: #3a0f1c;
      opacity: 0.8;
      transition: opacity 0.3s ease, background 0.3s ease, box-shadow 0.3s ease;
      user-select: none;
      padding: 0;
    }
    #timeline-toggle:hover {
      opacity: 1;
      background: rgba(254, 245, 237, 0.7);
    }
    #timeline-toggle.active {
      opacity: 1;
      background: rgba(196, 88, 120, 0.25);
      border-color: rgba(196, 88, 120, 0.55);
      box-shadow: 0 0 12px rgba(196, 88, 120, 0.5);
      animation: toggleGlow 2.4s ease-in-out infinite;
    }

    /* ─── Memory timeline panel ─────────────────────────────────────── */
    #timeline-panel {
      position: fixed;
      inset: 0;
      z-index: 60;
      background: rgba(254, 245, 237, 0.94);
      backdrop-filter: blur(30px);
      -webkit-backdrop-filter: blur(30px);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.4s ease;
      overflow-y: auto;
    }
    #timeline-panel.visible {
      opacity: 1;
      pointer-events: auto;
    }
    #timeline-panel .timeline-inner {
      max-width: 720px;
      margin: 4rem auto 6rem;
      padding: 2rem 2.5rem;
    }
    #timeline-panel .timeline-header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      margin-bottom: 1.2rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid rgba(92, 32, 48, 0.15);
    }
    #timeline-panel .timeline-header h2 {
      font-family: 'Cormorant Garamond', serif;
      font-size: 2rem;
      font-weight: 400;
      font-style: italic;
      color: #3a0f1c;
      margin: 0;
    }
    #timeline-panel .timeline-close {
      background: transparent;
      border: none;
      color: #3a0f1c;
      font-size: 1.6rem;
      cursor: pointer;
      opacity: 0.5;
      transition: opacity 0.2s ease;
      padding: 0.2rem 0.6rem;
    }
    #timeline-panel .timeline-close:hover { opacity: 1; }

    #timeline-panel .timeline-filters {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-bottom: 1.6rem;
    }
    #timeline-panel .chip {
      font-family: 'Outfit', sans-serif;
      font-size: 0.72rem;
      font-weight: 400;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #3a0f1c;
      background: rgba(254, 245, 237, 0.5);
      border: 1px solid rgba(58, 15, 28, 0.2);
      border-radius: 999px;
      padding: 0.35rem 0.85rem;
      cursor: pointer;
      transition: background 0.2s ease, color 0.2s ease;
      opacity: 0.65;
    }
    #timeline-panel .chip:hover { opacity: 0.9; }
    #timeline-panel .chip.active {
      background: #3a0f1c;
      color: #fef5ed;
      opacity: 1;
    }

    #timeline-panel .day-bucket {
      margin-bottom: 2rem;
    }
    #timeline-panel .day-bucket-header {
      font-family: 'Outfit', sans-serif;
      font-size: 0.68rem;
      font-weight: 500;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: #7a3a48;
      margin-bottom: 0.6rem;
      opacity: 0.75;
    }
    #timeline-panel .entry {
      position: relative;
      padding: 0.7rem 2rem 0.7rem 0.9rem;
      border-radius: 8px;
      transition: background 0.2s ease, opacity 0.3s ease;
    }
    #timeline-panel .entry:hover { background: rgba(92, 32, 48, 0.06); }
    #timeline-panel .entry .entry-kicker {
      font-family: 'Outfit', sans-serif;
      font-size: 0.58rem;
      font-weight: 500;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: #7a3a48;
      margin-right: 0.6rem;
    }
    #timeline-panel .entry .entry-title {
      font-family: 'Cormorant Garamond', serif;
      font-size: 0.95rem;
      font-style: italic;
      color: #3a0f1c;
    }
    #timeline-panel .entry .entry-body {
      font-family: 'Cormorant Garamond', serif;
      font-size: 1.05rem;
      color: #3a0f1c;
      margin-top: 0.15rem;
      line-height: 1.4;
    }
    #timeline-panel .entry-delete {
      position: absolute;
      right: 0.5rem;
      top: 50%;
      transform: translateY(-50%);
      background: transparent;
      border: none;
      color: #3a0f1c;
      font-size: 1.1rem;
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.2s ease;
      padding: 0.2rem 0.5rem;
    }
    #timeline-panel .entry:hover .entry-delete { opacity: 0.5; }
    #timeline-panel .entry-delete:hover { opacity: 1 !important; }

    #timeline-panel .timeline-empty {
      text-align: center;
      color: #7a3a48;
      font-family: 'Cormorant Garamond', serif;
      font-style: italic;
      font-size: 1.1rem;
      padding: 3rem 1rem;
    }
    #timeline-panel .timeline-footer {
      text-align: center;
      color: #7a3a48;
      font-family: 'Cormorant Garamond', serif;
      font-style: italic;
      font-size: 0.9rem;
      padding: 1.5rem 0;
      opacity: 0.7;
    }
    #timeline-panel .timeline-toast {
      position: fixed;
      bottom: 2rem;
      left: 50%;
      transform: translateX(-50%);
      background: rgba(58, 15, 28, 0.92);
      color: #fef5ed;
      font-family: 'Outfit', sans-serif;
      font-size: 0.82rem;
      padding: 0.7rem 1.2rem;
      border-radius: 999px;
      box-shadow: 0 6px 24px rgba(58, 15, 28, 0.35);
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.3s ease;
      z-index: 70;
    }
    #timeline-panel .timeline-toast.visible {
      opacity: 1;
      pointer-events: auto;
    }
    #timeline-panel .timeline-toast .undo-btn {
      background: transparent;
      border: none;
      color: #fef5ed;
      font-weight: 500;
      cursor: pointer;
      text-decoration: underline;
      margin-left: 0.5rem;
      padding: 0;
    }
```

- [ ] **Step 2: Add the toggle button + panel DOM markup**

Find the `<button id="vision-toggle">` element (it was changed to an SVG in the earlier vision-icon fix). Immediately **BEFORE** it (so the timeline button sits to the LEFT of vision), add:

```html
  <button id="timeline-toggle" type="button" title="Memory — click to open" aria-label="Open memory timeline">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
      <circle cx="5" cy="6" r="1.5"/>
      <line x1="9" y1="6" x2="20" y2="6"/>
      <circle cx="5" cy="12" r="1.5"/>
      <line x1="9" y1="12" x2="20" y2="12"/>
      <circle cx="5" cy="18" r="1.5"/>
      <line x1="9" y1="18" x2="20" y2="18"/>
    </svg>
  </button>
```

Then, just before the closing `</body>` tag (scroll to near the end of the file), add the panel markup:

```html
  <div id="timeline-panel" role="dialog" aria-label="Samantha's Memory" aria-hidden="true">
    <div class="timeline-inner">
      <header class="timeline-header">
        <h2>Samantha's Memory</h2>
        <button class="timeline-close" type="button" aria-label="Close">×</button>
      </header>
      <div class="timeline-filters">
        <button class="chip active" data-type="fact">Facts</button>
        <button class="chip active" data-type="observation">Observations</button>
        <button class="chip active" data-type="episode">Episodes</button>
        <button class="chip active" data-type="mood">Moods</button>
        <button class="chip" data-type="entity">Entities</button>
        <button class="chip" data-type="news">News</button>
      </div>
      <div class="timeline-scroll"></div>
    </div>
    <div class="timeline-toast"></div>
  </div>
```

- [ ] **Step 3: Rebuild visual-shell to verify syntax**

```bash
docker compose build visual-shell 2>&1 | tail -3
```

Expected: `Image samantha-os-visual-shell Built` — no HTML/CSS parse errors.

- [ ] **Step 4: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat(visual-shell): add timeline toggle button and panel CSS/DOM"
```

---

## Task 6: Visual shell — Timeline JS module (open/close/load/render)

**Files:**
- Modify: `services/visual-shell/index.html`

- [ ] **Step 1: Add the Timeline IIFE module**

Inside the main IIFE in `services/visual-shell/index.html`, find the `Vision` module (search for `const Vision = (() =>`). Immediately AFTER the Vision module closing `})();` and its toggle wiring block, add:

```js
    // ─── Memory Timeline module ──────────────────────────────────────
    const Timeline = (() => {
      const panel = document.getElementById('timeline-panel');
      const scrollEl = panel.querySelector('.timeline-scroll');
      const filtersEl = panel.querySelector('.timeline-filters');
      const closeBtn = panel.querySelector('.timeline-close');
      const toastEl = panel.querySelector('.timeline-toast');

      let isOpen = false;
      let loading = false;
      let entries = [];
      let nextBefore = null;
      let hasMore = false;
      let selectedTypes = new Set(['fact', 'observation', 'episode', 'mood']);
      const pendingDeletes = new Map(); // entry.id → timeout handle

      function open() {
        if (isOpen) return;
        isOpen = true;
        panel.classList.add('visible');
        panel.setAttribute('aria-hidden', 'false');
        entries = [];
        nextBefore = null;
        hasMore = false;
        scrollEl.innerHTML = '';
        load();
      }

      function close() {
        if (!isOpen) return;
        isOpen = false;
        panel.classList.remove('visible');
        panel.setAttribute('aria-hidden', 'true');
        hideToast();
      }

      function toggle() {
        if (isOpen) close(); else open();
      }

      async function load() {
        if (loading) return;
        if (selectedTypes.size === 0) {
          renderEmpty('Pick a filter above');
          return;
        }
        loading = true;
        try {
          const types = Array.from(selectedTypes).join(',');
          const url = `/memory/timeline?types=${encodeURIComponent(types)}&limit=100`
            + (nextBefore ? `&before=${encodeURIComponent(nextBefore)}` : '');
          const resp = await fetch(url);
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const data = await resp.json();
          entries = entries.concat(data.entries || []);
          nextBefore = data.next_before;
          hasMore = !!data.has_more;
          render();
        } catch (e) {
          console.warn('Timeline load failed', e);
          renderEmpty("Can't reach memory right now");
        } finally {
          loading = false;
        }
      }

      function bucketFor(ts) {
        if (!ts) return 'Earlier';
        const d = new Date(ts);
        const now = new Date();
        const msPerDay = 86400000;
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const entryDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
        const dayDiff = Math.floor((today - entryDay) / msPerDay);
        if (dayDiff === 0) return 'Today';
        if (dayDiff === 1) return 'Yesterday';
        if (dayDiff < 7) return 'This week';
        if (dayDiff < 14) return 'Last week';
        return 'Earlier';
      }

      const KICKER_FOR_TYPE = {
        fact: 'FACT',
        entity: 'ENTITY',
        observation: 'OBS',
        episode: 'EPISODE',
        mood: 'MOOD',
        news: 'NEWS',
      };

      function renderEmpty(msg) {
        scrollEl.innerHTML = `<div class="timeline-empty">${escapeHtml(msg)}</div>`;
      }

      function render() {
        if (entries.length === 0) {
          renderEmpty('Nothing here yet. Keep talking to me.');
          return;
        }
        // Group into day buckets, preserving order
        const bucketOrder = ['Today', 'Yesterday', 'This week', 'Last week', 'Earlier'];
        const buckets = new Map();
        for (const e of entries) {
          const b = bucketFor(e.ts);
          if (!buckets.has(b)) buckets.set(b, []);
          buckets.get(b).push(e);
        }
        let html = '';
        for (const label of bucketOrder) {
          if (!buckets.has(label)) continue;
          html += `<div class="day-bucket">`;
          html += `<div class="day-bucket-header">${label}</div>`;
          for (const e of buckets.get(label)) {
            html += renderEntry(e);
          }
          html += `</div>`;
        }
        if (hasMore) {
          html += `<div class="timeline-footer"><button class="load-more" type="button">Load older…</button></div>`;
        } else if (entries.length > 0) {
          html += `<div class="timeline-footer">That's everything.</div>`;
        }
        scrollEl.innerHTML = html;

        // Wire delete buttons
        scrollEl.querySelectorAll('.entry-delete').forEach(btn => {
          btn.addEventListener('click', (ev) => {
            ev.stopPropagation();
            const id = btn.dataset.id;
            const entry = entries.find(x => x.id === id);
            if (entry) deleteEntry(entry);
          });
        });
        // Wire load more
        const loadMoreBtn = scrollEl.querySelector('.load-more');
        if (loadMoreBtn) loadMoreBtn.addEventListener('click', () => load());
      }

      function renderEntry(e) {
        const kicker = KICKER_FOR_TYPE[e.type] || e.type.toUpperCase();
        return `
          <div class="entry" data-id="${escapeHtml(e.id)}">
            <span class="entry-kicker">${kicker}</span>
            <span class="entry-title">${escapeHtml(e.title || '')}</span>
            ${e.body ? `<div class="entry-body">${escapeHtml(e.body)}</div>` : ''}
            <button class="entry-delete" type="button" data-id="${escapeHtml(e.id)}" aria-label="Delete">×</button>
          </div>
        `;
      }

      function escapeHtml(s) {
        return String(s)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/"/g, '&quot;')
          .replace(/'/g, '&#39;');
      }

      async function deleteEntry(entry) {
        const [entryType, numId] = entry.id.split(':');
        const rowEl = scrollEl.querySelector(`[data-id="${cssEscape(entry.id)}"]`);
        if (rowEl) rowEl.style.opacity = '0';

        try {
          const resp = await fetch(`/memory/entry/${entryType}/${numId}`, { method: 'DELETE' });
          if (!resp.ok && resp.status !== 204) throw new Error(`HTTP ${resp.status}`);
        } catch (e) {
          console.warn('Delete failed', e);
          if (rowEl) rowEl.style.opacity = '1';
          showToast("Couldn't forget that — try again", null);
          return;
        }

        showToast('Forgot this.', entry);

        const handle = setTimeout(() => {
          // Truly remove from local state after 5s
          entries = entries.filter(x => x.id !== entry.id);
          if (rowEl && rowEl.parentNode) rowEl.remove();
          pendingDeletes.delete(entry.id);
          hideToast();
        }, 5000);
        pendingDeletes.set(entry.id, handle);
      }

      async function undoDelete(entry) {
        const handle = pendingDeletes.get(entry.id);
        if (handle) clearTimeout(handle);
        pendingDeletes.delete(entry.id);

        const [entryType, numId] = entry.id.split(':');
        try {
          await fetch(`/memory/entry/${entryType}/${numId}/restore`, { method: 'POST' });
        } catch (e) {
          console.warn('Restore failed', e);
        }

        const rowEl = scrollEl.querySelector(`[data-id="${cssEscape(entry.id)}"]`);
        if (rowEl) rowEl.style.opacity = '1';
        hideToast();
      }

      function showToast(message, entryOrNull) {
        toastEl.innerHTML = escapeHtml(message);
        if (entryOrNull) {
          const btn = document.createElement('button');
          btn.className = 'undo-btn';
          btn.textContent = 'Undo';
          btn.addEventListener('click', () => undoDelete(entryOrNull));
          toastEl.appendChild(btn);
        }
        toastEl.classList.add('visible');
      }

      function hideToast() {
        toastEl.classList.remove('visible');
      }

      function cssEscape(s) {
        // Minimal CSS.escape shim for old browsers. Attribute selectors only need
        // quoting + backslash escaping of quotes.
        return String(s).replace(/"/g, '\\"');
      }

      // Filter chip clicks
      filtersEl.addEventListener('click', (ev) => {
        const chip = ev.target.closest('.chip');
        if (!chip) return;
        const type = chip.dataset.type;
        if (chip.classList.toggle('active')) {
          selectedTypes.add(type);
        } else {
          selectedTypes.delete(type);
        }
        entries = [];
        nextBefore = null;
        scrollEl.innerHTML = '';
        load();
      });

      // Close button
      closeBtn.addEventListener('click', close);

      // Infinite scroll — load more when near bottom
      panel.addEventListener('scroll', () => {
        if (!hasMore || loading) return;
        const scrollBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight;
        if (scrollBottom < 200) load();
      });

      // Click outside .timeline-inner to close (optional quality-of-life)
      panel.addEventListener('click', (ev) => {
        if (ev.target === panel) close();
      });

      return { open, close, toggle, isOpen: () => isOpen };
    })();

    // ─── Timeline toggle wiring ──────────────────────────────────────
    const timelineToggleEl = document.getElementById('timeline-toggle');
    function renderTimelineToggle() {
      if (Timeline.isOpen()) {
        timelineToggleEl.classList.add('active');
        timelineToggleEl.title = 'Memory — click to close';
      } else {
        timelineToggleEl.classList.remove('active');
        timelineToggleEl.title = 'Memory — click to open';
      }
    }
    timelineToggleEl.addEventListener('click', () => {
      Timeline.toggle();
      renderTimelineToggle();
    });

    // Keyboard shortcut: Cmd+K / Ctrl+K toggles the panel; Escape closes it
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        Timeline.toggle();
        renderTimelineToggle();
      }
      if (e.key === 'Escape' && Timeline.isOpen()) {
        e.preventDefault();
        Timeline.close();
        renderTimelineToggle();
      }
    });
```

- [ ] **Step 2: Rebuild visual-shell**

```bash
docker compose build visual-shell 2>&1 | tail -3
```

Expected: `Image samantha-os-visual-shell Built` — no JS syntax errors.

- [ ] **Step 3: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat(visual-shell): Timeline IIFE with load/render/delete/undo + Cmd+K"
```

---

## Task 7: Manual smoke + README

- [ ] **Step 1: Bring up the stack**

```bash
docker compose up -d orchestrator visual-shell
sleep 4
```

- [ ] **Step 2: Seed the DB with a test fact if empty**

```bash
curl -s -X POST http://127.0.0.1:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"text":"My favorite color is blue"}' >/dev/null
```

(This triggers the existing fact extractor in the orchestrator, which writes a row into `facts`.)

- [ ] **Step 3: Test the GET endpoint**

```bash
curl -s 'http://127.0.0.1:8000/memory/timeline?types=fact,observation,episode,mood&limit=10' | python3 -m json.tool
```

Expected: a JSON object with `entries`, `has_more`, `next_before`. At least one entry if any memory has been recorded during this or prior sessions.

- [ ] **Step 4: Test the UI**

Open http://localhost:3333 in the browser. Hard-refresh (Cmd+Shift+R).

- Click the clean line-art timeline button (three rows with dots) in the top-right.
- Expected: full-screen cream frosted panel fades in. "Samantha's Memory" header. Filter chips row. Day-grouped entries or empty state.
- Hover an entry — a × button appears on the right.
- Click the × — entry fades out, a toast appears at the bottom with "Forgot this. Undo?".
- Click Undo within 5 seconds — entry fades back in, toast disappears.
- Click the × again on another entry, wait 5 seconds — the row disappears silently, the soft-delete persists in the DB.
- Click a filter chip (e.g. Entities) to enable it — panel re-fetches.
- Press Escape or Cmd+K — panel closes.
- Press Cmd+K again — panel opens.

- [ ] **Step 5: Inspect the DB directly to confirm soft-delete**

```bash
docker compose exec orchestrator python -c "
import sqlite3
c = sqlite3.connect('/app/config/samantha_memory.db')
c.row_factory = sqlite3.Row
for r in c.execute('SELECT id, key, value, deleted_at FROM facts ORDER BY id DESC LIMIT 5'):
    print(dict(r))
"
```

Expected: deleted facts show `deleted_at` with a non-NULL timestamp. Non-deleted ones show `None`.

- [ ] **Step 6: Update README**

Edit `README.md`. Update the features grid to add a Memory column if space, or update the existing row. More importantly, add a new **"Memory Timeline"** section in the feature descriptions area (before the existing "Proactive" bullet section):

```markdown
### Memory Timeline
- **📖 Timeline panel** — click the timeline icon in the top-right (or press `Cmd+K` / `Ctrl+K`) to open a full-screen overlay showing everything Samantha has learned: facts, observations she made through the camera, conversation episodes, your mood patterns, entities (people/pets/places), and news digests.
- **Day-grouped** — entries bucket into Today / Yesterday / This week / Last week / Earlier, newest first.
- **Filter chips** — toggle which types you want to see. Facts, Observations, Episodes, and Moods are on by default; Entities and News are one click away.
- **Audit + prune** — hover any entry to reveal a × delete icon. Click to forget. A 5-second undo toast lets you take it back. After 5 seconds the row is soft-deleted (still on disk with `deleted_at` set, but invisible in the timeline).
- **Infinite scroll** — scroll near the bottom to load older entries automatically.
- **Privacy-first** — everything is text, stored locally in the SQLite DB alongside her other memories. Nothing leaves your machine.
```

- [ ] **Step 7: Final commit**

```bash
git add README.md
git commit -m "docs: add Memory Timeline section to README"
```

---

## Spec coverage map

| Spec section | Implementing task(s) |
|---|---|
| §1 Goal | All |
| §2 Non-goals | Enforced by omission |
| §3.1 File layout | Tasks 2, 3, 4 |
| §3.2 Module boundaries | Tasks 2, 3, 4, 6 |
| §3.3 Data flow | Tasks 4, 6 |
| §3.4 Pagination | Task 2 (`before` cursor), Task 6 (infinite scroll) |
| §4.1 Migration | Task 1 |
| §4.2 Unified entry shape | Task 2 (`_*_to_entry` projections) |
| §4.3 Per-type projections | Task 2 |
| §4.4 Query structure | Task 2 |
| §5.1 GET /memory/timeline | Task 4 |
| §5.2 DELETE /memory/entry | Task 4 |
| §5.3 POST restore | Task 4 |
| §6.1 Toggle placement | Task 5 |
| §6.2 Panel markup | Task 5 |
| §6.3 CSS styling | Task 5 |
| §6.4 Day grouping logic | Task 6 (`bucketFor`) |
| §6.5 Keyboard shortcut (Cmd+K) | Task 6 |
| §6.6 Delete + undo flow | Task 6 |
| §7 Error handling | Tasks 4 (HTTP 400s), 6 (fetch catches) |
| §8 Testing strategy | Tasks 1-4 |
| §9 Acceptance criteria | Task 7 (manual smoke checklist) |
