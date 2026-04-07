"""HTTP endpoint tests for /memory/timeline and /memory/entry/..."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path):
    """A TestClient against the real app with a fresh on-disk memory DB."""
    from main import app, state
    from memory import ConversationMemory
    # Point state.memory at a fresh tmp DB for this test
    original = state.memory
    state.memory = ConversationMemory(db_path=str(tmp_path / "m.db"))
    yield TestClient(app)
    state.memory.close()
    state.memory = original


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
