"""Dataclasses used across the tasks integration. Pure data, no I/O."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


class ParseError(Exception):
    """Raised when parser.py cannot extract a time or content."""


RecurrenceKind = Literal[
    "daily",
    "weekdays",
    "weekly:mon", "weekly:tue", "weekly:wed", "weekly:thu",
    "weekly:fri", "weekly:sat", "weekly:sun",
]


@dataclass(frozen=True)
class Recurrence:
    kind: RecurrenceKind


@dataclass
class Reminder:
    id: Optional[int]
    text: str
    trigger_at: datetime                 # UTC
    created_at: Optional[datetime] = None
    fired_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    entity_id: Optional[int] = None
    source_text: Optional[str] = None


@dataclass
class ScheduleEvent:
    id: Optional[int]
    title: str
    start_at: datetime                   # UTC; next occurrence for recurring
    duration_min: Optional[int] = None
    recurrence: Optional[Recurrence] = None
    notes: Optional[str] = None
    entity_id: Optional[int] = None
    created_at: Optional[datetime] = None
    heads_up_fired_at: Optional[datetime] = None
    fired_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None


@dataclass
class ListItem:
    id: Optional[int]
    list_name: str
    text: str
    added_at: Optional[datetime] = None
    done_at: Optional[datetime] = None
    position: int = 0


@dataclass
class OverlayPayload:
    kind: Literal["reminder", "schedule", "schedule_heads_up", "list"]
    title: str
    chime: bool
    when: Optional[str] = None
    items: Optional[list[str]] = None
    highlight_index: Optional[int] = None
    list_name: Optional[str] = None
    duration_ms: int = 25000

    def to_envelope(self) -> dict:
        """Convert to the dict broadcast over the WebSocket."""
        return {
            "event": "overlay_card",
            "kind": self.kind,
            "title": self.title,
            "chime": self.chime,
            "when": self.when,
            "items": self.items,
            "highlight_index": self.highlight_index,
            "list_name": self.list_name,
            "duration_ms": self.duration_ms,
        }


@dataclass
class TaskActionResult:
    spoken: str
    overlay: Optional[OverlayPayload]
