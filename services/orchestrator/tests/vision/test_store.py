import pytest

from integrations.vision.store import VisionStore, SCHEMA_SQL


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return VisionStore(memory_db)


def test_create_and_fetch_observation(store):
    obs = store.create_observation(
        raw_description="a plant on a desk",
        spoken_text="I see your plant, soaking up the light.",
        user_trigger="what do you see?",
    )
    assert obs.id is not None
    assert obs.raw_description == "a plant on a desk"
    assert obs.spoken_text.startswith("I see")
    assert obs.user_trigger == "what do you see?"
    assert obs.deleted_at is None


def test_list_recent_returns_newest_first(store):
    a = store.create_observation("first", "first voiced", "q1")
    b = store.create_observation("second", "second voiced", "q2")
    c = store.create_observation("third", "third voiced", "q3")
    recent = store.list_recent(limit=10)
    assert [o.id for o in recent] == [c.id, b.id, a.id]


def test_list_recent_respects_limit(store):
    for i in range(5):
        store.create_observation(f"d{i}", f"v{i}", None)
    assert len(store.list_recent(limit=3)) == 3


def test_list_recent_excludes_deleted(store):
    a = store.create_observation("a", "av", None)
    store.create_observation("b", "bv", None)
    store.soft_delete(a.id)
    recent = store.list_recent(limit=10)
    assert a.id not in [o.id for o in recent]


def test_search_by_text_case_insensitive(store):
    store.create_observation("a green Plant on the desk", "warm voiced", None)
    store.create_observation("empty room with chair", "empty voiced", None)
    result = store.search_by_text("plant")
    assert result is not None
    assert "plant" in result.raw_description.lower()


def test_search_by_text_returns_none_when_no_match(store):
    store.create_observation("a chair", "chair voiced", None)
    assert store.search_by_text("dragon") is None


def test_search_by_text_excludes_deleted(store):
    a = store.create_observation("a plant", "v", None)
    store.soft_delete(a.id)
    assert store.search_by_text("plant") is None


def test_search_with_empty_query_returns_most_recent(store):
    store.create_observation("first", "f", None)
    b = store.create_observation("second", "s", None)
    result = store.search_by_text("")
    assert result is not None
    assert result.id == b.id
