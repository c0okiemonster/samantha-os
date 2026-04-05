import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from integrations.tasks.models import Recurrence
from integrations.tasks.scheduler import run_tick
from integrations.tasks.store import SCHEMA_SQL, TasksStore

UTC = timezone.utc


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return TasksStore(memory_db)


@pytest.mark.asyncio
async def test_due_reminder_fires_exactly_once(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    store.create_reminder(text="call mom", trigger_at=now - timedelta(seconds=1))

    emit = AsyncMock()
    await run_tick(store, emit, now=now, heads_up_window_min=10)
    assert emit.await_count == 1
    args = emit.await_args.args[0]
    assert args["event"] == "overlay_card"
    assert args["kind"] == "reminder"
    assert args["chime"] is True

    emit.reset_mock()
    await run_tick(store, emit, now=now, heads_up_window_min=10)
    assert emit.await_count == 0


@pytest.mark.asyncio
async def test_schedule_heads_up_then_start_fire_separately(store):
    start = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    store.create_schedule_event(title="Meeting", start_at=start)

    emit = AsyncMock()

    heads_up_time = start - timedelta(minutes=10)
    await run_tick(store, emit, now=heads_up_time, heads_up_window_min=10)
    assert emit.await_count == 1
    assert emit.await_args.args[0]["kind"] == "schedule_heads_up"

    emit.reset_mock()
    await run_tick(store, emit, now=start - timedelta(minutes=5), heads_up_window_min=10)
    assert emit.await_count == 0

    emit.reset_mock()
    await run_tick(store, emit, now=start, heads_up_window_min=10)
    assert emit.await_count == 1
    assert emit.await_args.args[0]["kind"] == "schedule"


@pytest.mark.asyncio
async def test_recurring_event_advances_and_fires_next_cycle(store):
    mon_8am = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Vitamins", start_at=mon_8am, recurrence=Recurrence("daily")
    )

    emit = AsyncMock()
    await run_tick(store, emit, now=mon_8am, heads_up_window_min=10)
    assert emit.await_count == 1

    refetched = store.get_schedule_event(e.id)
    assert refetched.start_at == datetime(2026, 4, 7, 8, 0, tzinfo=UTC)
    assert refetched.fired_at is None


@pytest.mark.asyncio
async def test_exception_in_tick_does_not_raise(store, monkeypatch):
    emit = AsyncMock()

    def boom(self, now):
        raise RuntimeError("boom")

    monkeypatch.setattr(TasksStore, "reminders_due", boom)
    await run_tick(store, emit, now=datetime.now(UTC), heads_up_window_min=10)
    assert emit.await_count == 0


@pytest.mark.asyncio
async def test_list_cards_do_not_come_from_scheduler(store):
    store.add_list_item("shopping", "milk")
    emit = AsyncMock()
    await run_tick(store, emit, now=datetime.now(UTC), heads_up_window_min=10)
    assert emit.await_count == 0
