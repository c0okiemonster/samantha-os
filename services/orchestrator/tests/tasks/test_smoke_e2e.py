"""End-to-end smoke: create a reminder via the integration, advance the
clock, run one scheduler tick, and verify the envelope is emitted."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from freezegun import freeze_time

from integrations.tasks import TasksIntegration
from integrations.tasks.scheduler import run_tick
from integrations.tasks.store import SCHEMA_SQL, TasksStore


@pytest.fixture
def wired(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    store = TasksStore(memory_db)
    integ = TasksIntegration()
    integ.store = store
    integ.tz = "UTC"
    return integ, store


@freeze_time("2026-04-05 16:59:00")  # 1 min before 17:00
async def test_reminder_end_to_end(wired):
    integ, store = wired
    emit = AsyncMock()

    # User creates a reminder for 5pm
    result = await integ.handle_action("add_reminder", "remind me to call mom at 5pm")
    assert result.overlay is not None
    assert result.overlay.kind == "reminder"
    assert result.overlay.chime is False  # creation, not fire

    # DB has it
    pending = store.list_pending_reminders()
    assert len(pending) == 1

    # Advance the clock past 5pm and run a scheduler tick
    with freeze_time("2026-04-05 17:00:05"):
        await run_tick(
            store,
            emit,
            now=datetime(2026, 4, 5, 17, 0, 5, tzinfo=timezone.utc),
            heads_up_window_min=10,
            tz="UTC",
        )

    assert emit.await_count == 1
    envelope = emit.await_args.args[0]
    assert envelope["event"] == "overlay_card"
    assert envelope["kind"] == "reminder"
    assert envelope["chime"] is True
    assert envelope["title"] == "call mom"

    # And the reminder is marked fired
    assert store.list_pending_reminders() == []


@freeze_time("2026-04-05 12:00:00")
async def test_list_add_and_show(wired):
    integ, store = wired

    await integ.handle_action("add_to_list", "add milk to shopping")
    await integ.handle_action("add_to_list", "add bread to shopping")

    result = await integ.handle_action("show_list", "what's on my shopping list")
    assert result.overlay is not None
    assert result.overlay.kind == "list"
    assert set(result.overlay.items) == {"milk", "bread"}
    assert result.overlay.highlight_index is None
