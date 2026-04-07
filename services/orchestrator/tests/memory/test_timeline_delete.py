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
    assert soft_delete_entry(db, "fact", 999) is False


def test_delete_is_idempotent(db):
    db.execute("INSERT INTO facts (category, key, value) VALUES ('c', 'k', 'v')")
    db.commit()
    assert soft_delete_entry(db, "fact", 1) is True
    assert soft_delete_entry(db, "fact", 1) is False
    assert build_timeline(db, types={"fact"}, limit=10)["entries"] == []
