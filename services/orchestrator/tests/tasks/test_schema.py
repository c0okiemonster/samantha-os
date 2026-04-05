"""Verify the memory module creates the new tasks tables and drops the legacy one."""
import sqlite3

from memory import ConversationMemory


def _connect(tmp_path):
    db = tmp_path / "m.db"
    m = ConversationMemory(db_path=str(db))
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
    assert "text" in cols
    assert "trigger_at" in cols
    assert "fired_at" in cols
    assert "cancelled_at" in cols
    assert "entity_id" in cols
    assert "source_text" in cols
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
    """Simulate an existing DB that had the legacy schema. ConversationMemory init
    should drop it and recreate with the new one."""
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

    m = ConversationMemory(db_path=str(db))
    cols = {r[1] for r in m.conn.execute("PRAGMA table_info(reminders)").fetchall()}
    assert "text" in cols
    assert "trigger_at" in cols
    count = m.conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
    assert count == 0
