import pytest

from integrations.tasks import TasksIntegration
from integrations.tasks.store import SCHEMA_SQL, TasksStore


@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    integ = TasksIntegration()
    integ.store = TasksStore(memory_db)
    integ.tz = "UTC"
    return integ


async def test_add_to_shopping_list(integration):
    result = await integration.handle_action(
        "add_to_list", "add milk to the shopping list"
    )
    assert result.overlay is not None
    assert result.overlay.kind == "list"
    assert result.overlay.list_name == "shopping"
    assert "milk" in result.overlay.items
    assert result.overlay.highlight_index == 0
    assert result.overlay.chime is False


async def test_add_to_named_list(integration):
    result = await integration.handle_action(
        "add_to_list", "add The Shining to the movies list"
    )
    assert result.overlay.list_name == "movies"
    assert any("shining" in i.lower() for i in result.overlay.items)


async def test_add_to_todo_list_via_phrasing(integration):
    result = await integration.handle_action(
        "add_to_list", "I should refactor the memory schema"
    )
    assert result.overlay.list_name == "todo"


async def test_add_shopping_via_buy_phrasing(integration):
    result = await integration.handle_action(
        "add_to_list", "remind me to buy bread"
    )
    assert result.overlay.list_name == "shopping"
    assert any("bread" in i.lower() for i in result.overlay.items)


async def test_duplicate_is_flagged_in_kicker(integration):
    await integration.handle_action("add_to_list", "add milk to the shopping list")
    result = await integration.handle_action("add_to_list", "add Milk to shopping")
    assert "already" in result.spoken.lower()


async def test_show_list(integration):
    await integration.handle_action("add_to_list", "add milk to shopping")
    await integration.handle_action("add_to_list", "add bread to shopping")
    result = await integration.handle_action("show_list", "what's on my shopping list")
    assert result.overlay is not None
    assert result.overlay.list_name == "shopping"
    assert result.overlay.highlight_index is None
    assert "milk" in result.overlay.items
    assert "bread" in result.overlay.items


async def test_show_empty_list(integration):
    result = await integration.handle_action("show_list", "what's on my shopping list")
    assert "empty" in result.spoken.lower() or "nothing" in result.spoken.lower()
