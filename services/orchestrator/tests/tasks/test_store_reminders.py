from datetime import datetime, timedelta, timezone

import pytest

from integrations.tasks.store import TasksStore, SCHEMA_SQL

UTC = timezone.utc


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return TasksStore(memory_db)


def test_create_and_fetch_reminder(store):
    when = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    r = store.create_reminder(text="call mom", trigger_at=when, source_text="remind me to call mom at 5")
    assert r.id is not None
    assert r.text == "call mom"
    assert r.trigger_at == when
    assert r.fired_at is None
    assert r.source_text == "remind me to call mom at 5"


def test_reminders_due_returns_only_past_pending(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    past = store.create_reminder(text="past", trigger_at=now - timedelta(minutes=5))
    future = store.create_reminder(text="future", trigger_at=now + timedelta(minutes=5))
    due = store.reminders_due(now)
    ids = [r.id for r in due]
    assert past.id in ids
    assert future.id not in ids


def test_reminders_due_excludes_fired(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    r = store.create_reminder(text="x", trigger_at=now - timedelta(minutes=1))
    store.mark_reminder_fired(r.id, now)
    assert store.reminders_due(now) == []


def test_reminders_due_excludes_cancelled(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    r = store.create_reminder(text="x", trigger_at=now - timedelta(minutes=1))
    store.cancel_reminder(r.id, now)
    assert store.reminders_due(now) == []


def test_cancel_last_pending_reminder(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    r1 = store.create_reminder(text="first", trigger_at=now + timedelta(hours=1))
    r2 = store.create_reminder(text="second", trigger_at=now + timedelta(hours=2))
    cancelled = store.cancel_last_reminder(now)
    assert cancelled is not None
    assert cancelled.id == r2.id
    pending = store.list_pending_reminders()
    assert {r.id for r in pending} == {r1.id}


def test_cancel_last_when_none_pending_returns_none(store):
    now = datetime(2026, 4, 5, 17, 0, tzinfo=UTC)
    assert store.cancel_last_reminder(now) is None
