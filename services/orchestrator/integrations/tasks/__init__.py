"""Tasks integration — reminders, schedule events, lists."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from integrations import BaseIntegration, IntegrationAction

from .models import OverlayPayload, ParseError, TaskActionResult
from .parser import parse_recurrence, parse_when
from .store import SCHEMA_SQL, TasksStore

logger = logging.getLogger("samantha.tasks")


DEFAULT_TZ = os.environ.get("TZ", "Europe/Stockholm")


def _strip_reminder_lead(text: str) -> str:
    """Remove the 'remind me (to|about)' prefix so what's left is subject + time."""
    return re.sub(r"^\s*remind me( to| about)?\s*", "", text, flags=re.IGNORECASE).strip()


def _split_subject_and_time(text: str) -> tuple[str, str]:
    """Heuristic: split on the first time marker. Returns (subject, time_phrase)."""
    patterns = [
        r"\s+(at\s+.+)$",
        r"\s+(in\s+\d.+)$",
        r"\s+(tomorrow.*)$",
        r"\s+(tonight.*)$",
        r"\s+(this\s+(?:morning|afternoon|evening|night).*)$",
        r"\s+(next\s+.+)$",
        r"\s+(on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday).*)$",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            subject = text[: m.start()].strip()
            time_phrase = m.group(1).strip()
            return subject, time_phrase
    return text.strip(), ""


class TasksIntegration(BaseIntegration):
    name = "tasks"
    display_name = "Reminders, Schedules & Lists"
    description = "Hold reminders, schedule events, and lists for the user"
    icon = "🗓️"
    requires_auth = False

    def __init__(self):
        super().__init__()
        self.db_path: str = "config/samantha_memory.db"
        self.conn: Optional[sqlite3.Connection] = None
        self.store: Optional[TasksStore] = None
        self.tz: str = DEFAULT_TZ

    async def initialize(self, config: dict) -> bool:
        self.db_path = config.get("db_path", self.db_path)
        self.tz = config.get("tz", DEFAULT_TZ)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA_SQL)
        self.store = TasksStore(self.conn)
        logger.info(f"Tasks store ready at {self.db_path} (tz={self.tz})")
        return True

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="add_reminder",
                description="Create a one-shot reminder for a specific time",
                keywords=["remind me", "remind me to", "remind me about"],
                parameters=["text"],
                examples=["Remind me to call mom at 5pm", "Remind me in 20 minutes to check the oven"],
            ),
            IntegrationAction(
                name="cancel_last_reminder",
                description="Cancel the most recent pending reminder",
                keywords=["cancel that", "forget that", "cancel the last reminder", "remove that reminder"],
                parameters=[],
                examples=["Cancel that", "Forget the last reminder"],
            ),
            IntegrationAction(
                name="add_schedule",
                description="Add a calendar event or recurring routine",
                keywords=["meeting with", "appointment", "dentist", "call with",
                          "every morning", "every weekday", "every monday",
                          "every tuesday", "every wednesday", "every thursday",
                          "every friday", "every saturday", "every sunday", "every day"],
                parameters=["text"],
                examples=["Meeting with Jussi Friday at 3pm", "Every weekday at 8 remind me to take vitamins"],
            ),
            IntegrationAction(
                name="show_schedule",
                description="Show upcoming schedule events",
                keywords=["what's next", "what's on my schedule", "what's today",
                          "what's this week", "show my schedule"],
                parameters=[],
                examples=["What's next?", "What's on my schedule today?"],
            ),
            IntegrationAction(
                name="add_to_list",
                description="Add an item to a named list (shopping, todo, or any name you pick)",
                keywords=["add to", "put on", "shopping list", "todo", "grocery",
                          "remind me to buy", "need to buy", "I should", "I need to"],
                parameters=["text"],
                examples=["Add milk to the shopping list", "I should call the bank"],
            ),
            IntegrationAction(
                name="show_list",
                description="Show items on a named list",
                keywords=["show my list", "what's on my", "shopping list", "todo list"],
                parameters=["text"],
                examples=["What's on my shopping list?", "Show me my todo"],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        """Back-compat dict interface. Prefer handle_action()."""
        text = params.get("text") or params.get("content") or ""
        result = await self.handle_action(action_name, text)
        return {
            "spoken": result.spoken,
            "overlay": result.overlay.to_envelope() if result.overlay else None,
        }

    async def handle_action(self, action_name: str, text: str) -> TaskActionResult:
        handlers = {
            "add_reminder": self._add_reminder,
            "cancel_last_reminder": self._cancel_last_reminder,
            "add_schedule": self._add_schedule,
            "show_schedule": self._show_schedule,
            "add_to_list": self._add_to_list,
            "show_list": self._show_list,
        }
        handler = handlers.get(action_name)
        if not handler:
            return TaskActionResult(spoken=f"I don't know how to {action_name}.", overlay=None)
        return await handler(text)

    # ─── Handlers ───────────────────────────────────────────────────────

    async def _add_reminder(self, text: str) -> TaskActionResult:
        stripped = _strip_reminder_lead(text)
        subject, time_phrase = _split_subject_and_time(stripped)

        if not time_phrase:
            return TaskActionResult(
                spoken="When should I remind you?",
                overlay=None,
            )
        if not subject:
            return TaskActionResult(
                spoken="What should I remind you about?",
                overlay=None,
            )

        try:
            trigger_at = parse_when(time_phrase, tz=self.tz)
        except ParseError:
            return TaskActionResult(
                spoken="I couldn't figure out the time — can you rephrase it?",
                overlay=None,
            )

        self.store.create_reminder(
            text=subject,
            trigger_at=trigger_at,
            source_text=text,
        )

        local_str = self._format_local(trigger_at)
        spoken = f"Got it — I'll remind you to {subject} at {local_str}."
        overlay = OverlayPayload(
            kind="reminder",
            title=subject,
            chime=False,
            when=f"at {local_str}",
        )
        return TaskActionResult(spoken=spoken, overlay=overlay)

    async def _cancel_last_reminder(self, text: str) -> TaskActionResult:
        now = datetime.now(timezone.utc)
        cancelled = self.store.cancel_last_reminder(now)
        if cancelled is None:
            return TaskActionResult(
                spoken="There's nothing pending to cancel.",
                overlay=None,
            )
        return TaskActionResult(
            spoken=f"Cancelled — I won't remind you to {cancelled.text}.",
            overlay=None,
        )

    async def _add_schedule(self, text: str) -> TaskActionResult:
        body = re.sub(r"^\s*(schedule|add|create)\s+", "", text, flags=re.IGNORECASE).strip()

        # Detect recurrence first; then parse time on the stripped remainder.
        recurrence, stripped = parse_recurrence(body)

        title, time_phrase = _split_subject_and_time(stripped)

        if not time_phrase:
            m = re.match(r"^(at\s+\S+|in\s+\d+\s+\w+)\s+(.+)$", stripped, re.IGNORECASE)
            if m:
                time_phrase = m.group(1)
                title = m.group(2)

        if not title:
            return TaskActionResult(
                spoken="What's the event?",
                overlay=None,
            )
        if not time_phrase:
            return TaskActionResult(
                spoken="When should this be?",
                overlay=None,
            )

        try:
            start_at = parse_when(time_phrase, tz=self.tz)
        except ParseError:
            return TaskActionResult(
                spoken="I couldn't figure out the time — can you rephrase it?",
                overlay=None,
            )

        self.store.create_schedule_event(
            title=title,
            start_at=start_at,
            recurrence=recurrence,
        )

        local_str = self._format_local(start_at)
        if recurrence:
            spoken = f"Added — {title}, {self._recurrence_phrase(recurrence)} at {local_str}."
            when_display = f"{self._recurrence_phrase(recurrence)} at {local_str}"
        else:
            spoken = f"Added — {title} at {local_str}."
            when_display = f"at {local_str}"

        overlay = OverlayPayload(
            kind="schedule",
            title=title,
            chime=False,
            when=when_display,
        )
        return TaskActionResult(spoken=spoken, overlay=overlay)

    async def _show_schedule(self, text: str) -> TaskActionResult:
        now = datetime.now(timezone.utc)
        row = self.store.conn.execute(
            "SELECT * FROM schedule_events "
            "WHERE start_at > ? AND cancelled_at IS NULL "
            "ORDER BY start_at ASC LIMIT 1",
            (now.isoformat(),),
        ).fetchone()
        if row is None:
            return TaskActionResult(
                spoken="There's nothing on your schedule.",
                overlay=None,
            )
        from .store import _row_to_schedule_event
        event = _row_to_schedule_event(row)
        local_str = self._format_local(event.start_at)
        overlay = OverlayPayload(
            kind="schedule",
            title=event.title,
            chime=False,
            when=f"at {local_str}",
        )
        return TaskActionResult(
            spoken=f"Next up: {event.title} at {local_str}.",
            overlay=overlay,
        )

    def _recurrence_phrase(self, rec) -> str:
        kind = rec.kind
        if kind == "daily":
            return "every day"
        if kind == "weekdays":
            return "every weekday"
        if kind.startswith("weekly:"):
            day_abbr = kind.split(":", 1)[1]
            names = {
                "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
                "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
            }
            return f"every {names.get(day_abbr, day_abbr)}"
        return kind

    def _detect_list_and_item(self, text: str) -> tuple[str, str]:
        """Return (list_name, item) or ("", "") if nothing recognized."""
        t = text.strip()

        # "add X to the Y list" / "put X on Y list"
        m = re.search(
            r"^(?:add|put)\s+(.+?)\s+(?:to|on)\s+(?:the\s+)?(?:my\s+)?(\w+)(?:\s+list)?$",
            t, re.IGNORECASE,
        )
        if m:
            item = m.group(1).strip()
            list_name = m.group(2).lower()
            if list_name in ("groceries", "grocery"):
                list_name = "shopping"
            return list_name, item

        # "remind me to buy X" / "need to buy X" / "pick up X"
        m = re.search(
            r"^(?:remind me to buy|need to buy|pick up|get|buy)\s+(.+)$",
            t, re.IGNORECASE,
        )
        if m:
            return "shopping", m.group(1).strip()

        # "I should X" / "I need to X" / "todo: X"
        m = re.search(
            r"^(?:i should|i need to|todo:?)\s+(.+)$",
            t, re.IGNORECASE,
        )
        if m:
            return "todo", m.group(1).strip()

        return "", ""

    def _detect_list_to_show(self, text: str) -> str:
        m = re.search(
            r"(?:show me|what(?:'s| is) on|show)\s+(?:my\s+|the\s+)?(\w+)(?:\s+list)?",
            text, re.IGNORECASE,
        )
        if m:
            name = m.group(1).lower()
            if name in ("groceries", "grocery"):
                return "shopping"
            if name in ("list", "my"):
                return ""
            return name
        return ""

    async def _add_to_list(self, text: str) -> TaskActionResult:
        list_name, item = self._detect_list_and_item(text)
        if not list_name or not item:
            return TaskActionResult(
                spoken="What should I add, and to which list?",
                overlay=None,
            )

        duplicate = self.store.is_duplicate(list_name, item)
        self.store.add_list_item(list_name, item)
        all_items = self.store.get_list(list_name)
        texts = [i.text for i in all_items]
        highlight = None
        for idx in range(len(texts) - 1, -1, -1):
            if texts[idx].lower() == item.lower():
                highlight = idx
                break

        if duplicate:
            spoken = f"{item} was already on your {list_name} list — added again."
        else:
            spoken = f"Added {item} to your {list_name} list."

        overlay = OverlayPayload(
            kind="list",
            title=f"{list_name.capitalize()} list",
            chime=False,
            items=texts,
            highlight_index=highlight,
            list_name=list_name,
        )
        return TaskActionResult(spoken=spoken, overlay=overlay)

    async def _show_list(self, text: str) -> TaskActionResult:
        list_name = self._detect_list_to_show(text)
        if not list_name:
            return TaskActionResult(
                spoken="Which list?",
                overlay=None,
            )
        items = self.store.get_list(list_name)
        if not items:
            return TaskActionResult(
                spoken=f"Your {list_name} list is empty.",
                overlay=None,
            )
        overlay = OverlayPayload(
            kind="list",
            title=f"{list_name.capitalize()} list",
            chime=False,
            items=[i.text for i in items],
            highlight_index=None,
            list_name=list_name,
        )
        return TaskActionResult(
            spoken=f"Here's your {list_name} list.",
            overlay=overlay,
        )

    # ─── Helpers ────────────────────────────────────────────────────────

    def _format_local(self, dt: datetime) -> str:
        try:
            from zoneinfo import ZoneInfo
            return dt.astimezone(ZoneInfo(self.tz)).strftime("%H:%M")
        except Exception:
            return dt.strftime("%H:%M")

    async def shutdown(self):
        if self.conn:
            self.conn.close()
