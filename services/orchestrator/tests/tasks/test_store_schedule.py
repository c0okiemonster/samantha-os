from datetime import datetime, timedelta, timezone

import pytest

from integrations.tasks.models import Recurrence
from integrations.tasks.store import TasksStore, SCHEMA_SQL

UTC = timezone.utc


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return TasksStore(memory_db)


def test_create_one_shot_schedule(store):
    when = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    e = store.create_schedule_event(title="Meeting with Jussi", start_at=when)
    assert e.id is not None
    assert e.recurrence is None
    assert e.fired_at is None
    assert e.heads_up_fired_at is None


def test_create_recurring_schedule(store):
    when = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)  # Monday
    e = store.create_schedule_event(
        title="Vitamins",
        start_at=when,
        recurrence=Recurrence("weekdays"),
    )
    assert e.recurrence == Recurrence("weekdays")


def test_schedule_due_at_start(store):
    now = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    e = store.create_schedule_event(title="Meeting", start_at=now)
    due = store.schedule_due(now)
    assert len(due) == 1
    assert due[0].id == e.id


def test_schedule_due_excludes_future(store):
    now = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    store.create_schedule_event(title="Later", start_at=now + timedelta(minutes=5))
    assert store.schedule_due(now) == []


def test_schedule_heads_up_window(store):
    now = datetime(2026, 4, 10, 14, 55, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Meeting", start_at=now + timedelta(minutes=5)  # 15:00, 5 min away
    )
    due = store.schedule_heads_up_due(now, window_min=10)
    assert len(due) == 1
    assert due[0].id == e.id


def test_schedule_heads_up_excludes_already_fired(store):
    now = datetime(2026, 4, 10, 14, 55, tzinfo=UTC)
    e = store.create_schedule_event(title="Meeting", start_at=now + timedelta(minutes=5))
    store.mark_heads_up_fired(e.id, now)
    assert store.schedule_heads_up_due(now, window_min=10) == []


def test_schedule_heads_up_outside_window(store):
    now = datetime(2026, 4, 10, 14, 0, tzinfo=UTC)
    store.create_schedule_event(title="Meeting", start_at=now + timedelta(minutes=30))
    # 30 min away, window is 10 → not yet
    assert store.schedule_heads_up_due(now, window_min=10) == []


def test_mark_schedule_fired(store):
    now = datetime(2026, 4, 10, 15, 0, tzinfo=UTC)
    e = store.create_schedule_event(title="Meeting", start_at=now)
    store.mark_schedule_fired(e.id, now)
    assert store.schedule_due(now) == []


def test_advance_recurrence_daily(store):
    start = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Vitamins", start_at=start, recurrence=Recurrence("daily")
    )
    store.advance_recurrence(e.id, now=start)
    refetched = store.get_schedule_event(e.id)
    assert refetched.start_at == datetime(2026, 4, 7, 8, 0, tzinfo=UTC)
    assert refetched.heads_up_fired_at is None
    assert refetched.fired_at is None


def test_advance_recurrence_weekdays_skips_weekend(store):
    # Friday 8:00
    friday = datetime(2026, 4, 10, 8, 0, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Vitamins", start_at=friday, recurrence=Recurrence("weekdays")
    )
    store.advance_recurrence(e.id, now=friday)
    refetched = store.get_schedule_event(e.id)
    assert refetched.start_at == datetime(2026, 4, 13, 8, 0, tzinfo=UTC)


def test_advance_recurrence_weekly_specific_day(store):
    mon = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)
    e = store.create_schedule_event(
        title="Planning", start_at=mon, recurrence=Recurrence("weekly:mon")
    )
    store.advance_recurrence(e.id, now=mon)
    refetched = store.get_schedule_event(e.id)
    assert refetched.start_at == datetime(2026, 4, 13, 8, 0, tzinfo=UTC)


def test_advance_recurrence_skips_past_downtime(store):
    """If we've been offline for days, advance past all missed days
    and surface only the most recent missed occurrence."""
    start = datetime(2026, 4, 6, 8, 0, tzinfo=UTC)  # Monday
    e = store.create_schedule_event(
        title="Vitamins", start_at=start, recurrence=Recurrence("daily")
    )
    five_days_later = start + timedelta(days=5)
    store.advance_recurrence(e.id, now=five_days_later)
    refetched = store.get_schedule_event(e.id)
    assert refetched.start_at > five_days_later
    assert refetched.start_at == datetime(2026, 4, 12, 8, 0, tzinfo=UTC)
