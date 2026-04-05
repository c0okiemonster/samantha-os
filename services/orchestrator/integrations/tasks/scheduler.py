"""Background scheduler that surfaces due reminders and schedule events."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from .models import OverlayPayload
from .store import TasksStore

logger = logging.getLogger("samantha.tasks.scheduler")

EmitOverlay = Callable[[dict], Awaitable[None]]


def _format_time_local(dt: datetime, tz: str) -> str:
    """HH:MM in local timezone."""
    try:
        from zoneinfo import ZoneInfo
        local = dt.astimezone(ZoneInfo(tz))
    except Exception:
        local = dt
    return local.strftime("%H:%M")


def _reminder_envelope(reminder, tz: str) -> dict:
    when_str = f"now · {_format_time_local(reminder.trigger_at, tz)}"
    return OverlayPayload(
        kind="reminder",
        title=reminder.text,
        chime=True,
        when=when_str,
    ).to_envelope()


def _schedule_envelope(event, tz: str) -> dict:
    when_str = _format_time_local(event.start_at, tz)
    return OverlayPayload(
        kind="schedule",
        title=event.title,
        chime=True,
        when=f"now · {when_str}",
    ).to_envelope()


def _schedule_heads_up_envelope(event, now: datetime, tz: str) -> dict:
    delta_min = max(0, int((event.start_at - now).total_seconds() // 60))
    when_str = f"in {delta_min} min · {_format_time_local(event.start_at, tz)}"
    return OverlayPayload(
        kind="schedule_heads_up",
        title=event.title,
        chime=True,
        when=when_str,
    ).to_envelope()


async def run_tick(
    store: TasksStore,
    emit: EmitOverlay,
    now: datetime,
    heads_up_window_min: int = 10,
    tz: str = "Europe/Stockholm",
) -> None:
    """Process one scheduler tick. Exceptions are logged, not raised."""
    try:
        for r in store.reminders_due(now):
            await emit(_reminder_envelope(r, tz))
            store.mark_reminder_fired(r.id, now)

        for e in store.schedule_heads_up_due(now, window_min=heads_up_window_min):
            await emit(_schedule_heads_up_envelope(e, now, tz))
            store.mark_heads_up_fired(e.id, now)

        for e in store.schedule_due(now):
            await emit(_schedule_envelope(e, tz))
            if e.recurrence:
                store.advance_recurrence(e.id, now)
            else:
                store.mark_schedule_fired(e.id, now)
    except Exception:
        logger.exception("scheduler tick failed")


async def run(
    store: TasksStore,
    emit: EmitOverlay,
    poll_interval_s: int = 15,
    heads_up_window_min: int = 10,
    tz: str = "Europe/Stockholm",
) -> None:
    """Long-running scheduler loop. Runs forever; cancel externally."""
    logger.info("tasks scheduler started")
    while True:
        await run_tick(
            store,
            emit,
            now=datetime.now(timezone.utc),
            heads_up_window_min=heads_up_window_min,
            tz=tz,
        )
        await asyncio.sleep(poll_interval_s)
