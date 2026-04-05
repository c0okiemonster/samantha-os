from datetime import datetime, timezone

from integrations.tasks.models import (
    Reminder,
    ScheduleEvent,
    ListItem,
    Recurrence,
    OverlayPayload,
    TaskActionResult,
    ParseError,
)


def test_reminder_defaults():
    r = Reminder(id=None, text="call mom", trigger_at=datetime(2026, 4, 5, 17, 0, tzinfo=timezone.utc))
    assert r.text == "call mom"
    assert r.fired_at is None
    assert r.cancelled_at is None
    assert r.entity_id is None


def test_schedule_event_recurrence_optional():
    e = ScheduleEvent(id=None, title="Meeting", start_at=datetime(2026, 4, 10, 15, 0, tzinfo=timezone.utc))
    assert e.recurrence is None
    assert e.duration_min is None


def test_recurrence_parse():
    assert Recurrence("daily").kind == "daily"
    assert Recurrence("weekly:mon").kind == "weekly:mon"


def test_overlay_payload_defaults():
    p = OverlayPayload(kind="reminder", title="Call mom", chime=True)
    assert p.duration_ms == 25000
    assert p.items is None


def test_task_action_result_holds_both():
    p = OverlayPayload(kind="reminder", title="X", chime=True)
    r = TaskActionResult(spoken="ok", overlay=p)
    assert r.spoken == "ok"
    assert r.overlay is p


def test_parse_error_is_exception():
    assert issubclass(ParseError, Exception)
