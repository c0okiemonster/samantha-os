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
    types = {e["type"] for e in result["entries"]}
    assert types == set(VALID_TYPES)
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
    ids1 = {e["id"] for e in page1["entries"]}
    ids2 = {e["id"] for e in page2["entries"]}
    assert ids1.isdisjoint(ids2)
    assert page2["has_more"] is False


def test_empty_types_returns_empty_list(db):
    _seed_all(db)
    result = build_timeline(db, types=set(), limit=100)
    assert result["entries"] == []
    assert result["has_more"] is False


def test_invalid_type_raises(db):
    with pytest.raises(ValueError):
        build_timeline(db, types={"fact", "bogus"}, limit=100)
