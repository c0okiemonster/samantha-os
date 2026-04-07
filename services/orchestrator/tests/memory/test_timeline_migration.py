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

    m = ConversationMemory(db_path=str(db))
    cols = {r[1] for r in m.conn.execute("PRAGMA table_info(facts)").fetchall()}
    assert "deleted_at" in cols
    row = m.conn.execute("SELECT category, key, value FROM facts").fetchone()
    assert row is not None
    assert row[2] == "blue"
