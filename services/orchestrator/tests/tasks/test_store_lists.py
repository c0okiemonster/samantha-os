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
    assert store.is_duplicate("shopping", "milk") is False


def test_add_item_assigns_incrementing_position(store):
    a = store.add_list_item("shopping", "milk")
    b = store.add_list_item("shopping", "bread")
    c = store.add_list_item("shopping", "eggs")
    assert a.position < b.position < c.position
