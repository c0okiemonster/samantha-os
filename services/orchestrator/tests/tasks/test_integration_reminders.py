from datetime import datetime, timezone

import pytest
from freezegun import freeze_time

from integrations.tasks import TasksIntegration
from integrations.tasks.store import SCHEMA_SQL, TasksStore


@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    store = TasksStore(memory_db)
    integ = TasksIntegration()
    integ.store = store
    integ.tz = "UTC"
    return integ


@freeze_time("2026-04-05 12:00:00")
async def test_add_reminder_happy_path(integration):
    result = await integration.handle_action("add_reminder", "remind me to call mom at 5pm")
    assert "call mom" in result.spoken.lower()
    assert result.overlay is not None
    assert result.overlay.kind == "reminder"
    assert result.overlay.chime is False
    pending = integration.store.list_pending_reminders()
    assert len(pending) == 1
    assert pending[0].text == "call mom"


@freeze_time("2026-04-05 12:00:00")
async def test_add_reminder_missing_time_asks_clarification(integration):
    result = await integration.handle_action("add_reminder", "remind me to call mom")
    assert "when" in result.spoken.lower()
    assert result.overlay is None
    assert integration.store.list_pending_reminders() == []


@freeze_time("2026-04-05 12:00:00")
async def test_add_reminder_empty_text_asks_clarification(integration):
    result = await integration.handle_action("add_reminder", "remind me at 5pm")
    assert result.overlay is None or "what" in result.spoken.lower()


async def test_cancel_last_with_nothing_pending(integration):
    result = await integration.handle_action("cancel_last_reminder", "forget that")
    assert "nothing" in result.spoken.lower()
    assert result.overlay is None


@freeze_time("2026-04-05 12:00:00")
async def test_cancel_last_cancels_most_recent(integration):
    await integration.handle_action("add_reminder", "remind me to X at 3pm")
    await integration.handle_action("add_reminder", "remind me to Y at 4pm")
    result = await integration.handle_action("cancel_last_reminder", "cancel that")
    assert "Y" in result.spoken or "y" in result.spoken.lower()
    assert len(integration.store.list_pending_reminders()) == 1
