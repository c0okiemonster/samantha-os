from memory import ConversationMemory


def test_observations_table_exists(tmp_path):
    db = tmp_path / "m.db"
    m = ConversationMemory(db_path=str(db))
    rows = m.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "observations" in names


def test_observations_columns(tmp_path):
    db = tmp_path / "m.db"
    m = ConversationMemory(db_path=str(db))
    cols = {r[1] for r in m.conn.execute("PRAGMA table_info(observations)").fetchall()}
    for expected in [
        "id", "raw_description", "spoken_text", "user_trigger",
        "created_at", "deleted_at",
    ]:
        assert expected in cols, f"missing column: {expected}"


def test_observations_index(tmp_path):
    db = tmp_path / "m.db"
    m = ConversationMemory(db_path=str(db))
    rows = m.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='observations'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_observations_time" in names
