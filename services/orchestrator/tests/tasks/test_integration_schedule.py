import pytest
from freezegun import freeze_time

from integrations.tasks import TasksIntegration
from integrations.tasks.store import SCHEMA_SQL, TasksStore


@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    integ = TasksIntegration()
    integ.store = TasksStore(memory_db)
    integ.tz = "UTC"
    return integ


@freeze_time("2026-04-05 12:00:00")
async def test_add_one_shot_schedule(integration):
    result = await integration.handle_action(
        "add_schedule", "meeting with Jussi friday at 3pm"
    )
    assert result.overlay is not None
    assert result.overlay.kind == "schedule"
    events = integration.store.conn.execute(
        "SELECT title, start_at, recurrence FROM schedule_events"
    ).fetchall()
    assert len(events) == 1
    assert "jussi" in events[0]["title"].lower()
    assert events[0]["recurrence"] is None


@freeze_time("2026-04-05 12:00:00")
async def test_add_recurring_weekdays(integration):
    result = await integration.handle_action(
        "add_schedule", "every weekday at 8 vitamins"
    )
    assert result.overlay is not None
    events = integration.store.conn.execute(
        "SELECT title, recurrence FROM schedule_events"
    ).fetchall()
    assert len(events) == 1
    assert events[0]["recurrence"] == "weekdays"


@freeze_time("2026-04-05 12:00:00")
async def test_add_recurring_weekly_monday(integration):
    await integration.handle_action(
        "add_schedule", "every monday at 9 planning session"
    )
    row = integration.store.conn.execute(
        "SELECT recurrence FROM schedule_events"
    ).fetchone()
    assert row["recurrence"] == "weekly:mon"


@freeze_time("2026-04-05 12:00:00")
async def test_show_schedule_returns_upcoming(integration):
    await integration.handle_action("add_schedule", "dentist tuesday at 10am")
    result = await integration.handle_action("show_schedule", "what's next")
    assert result.overlay is not None
    assert result.overlay.kind == "schedule"
    assert "dentist" in result.overlay.title.lower()


async def test_show_schedule_empty(integration):
    result = await integration.handle_action("show_schedule", "what's on my schedule")
    assert "nothing" in result.spoken.lower() or "no " in result.spoken.lower()
    assert result.overlay is None


@freeze_time("2026-04-05 12:00:00")
async def test_add_schedule_unparseable_time(integration):
    result = await integration.handle_action("add_schedule", "meeting glorp")
    assert result.overlay is None
