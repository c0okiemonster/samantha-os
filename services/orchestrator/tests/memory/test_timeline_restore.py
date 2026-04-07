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
