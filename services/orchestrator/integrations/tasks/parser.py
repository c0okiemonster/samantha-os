"""Time + recurrence parsing for the tasks integration.
Pure functions, no I/O."""
from __future__ import annotations

import re
from typing import Optional

from .models import ParseError, Recurrence  # noqa: F401 (ParseError used in Task 8)


# ─── Recurrence ────────────────────────────────────────────────────────

_DAY_ALIASES = {
    "mon": "mon", "monday": "mon",
    "tue": "tue", "tues": "tue", "tuesday": "tue",
    "wed": "wed", "wednesday": "wed",
    "thu": "thu", "thur": "thu", "thurs": "thu", "thursday": "thu",
    "fri": "fri", "friday": "fri",
    "sat": "sat", "saturday": "sat",
    "sun": "sun", "sunday": "sun",
}

_DAY_PATTERN = "|".join(sorted(_DAY_ALIASES.keys(), key=len, reverse=True))

_RE_EVERY_WEEKDAY = re.compile(r"\bevery\s+weekdays?\b", re.IGNORECASE)
_RE_EVERY_DAY = re.compile(r"\bevery\s+(day|morning|evening|night)\b", re.IGNORECASE)
_RE_EVERY_DOW = re.compile(rf"\bevery\s+({_DAY_PATTERN})\b", re.IGNORECASE)


def parse_recurrence(text: str) -> tuple[Optional[Recurrence], str]:
    """Detect a recurrence phrase. Return (Recurrence | None, stripped_text)."""

    m = _RE_EVERY_WEEKDAY.search(text)
    if m:
        stripped = (text[: m.start()] + text[m.end():]).strip()
        return Recurrence("weekdays"), _collapse_spaces(stripped)

    m = _RE_EVERY_DAY.search(text)
    if m:
        stripped = (text[: m.start()] + text[m.end():]).strip()
        return Recurrence("daily"), _collapse_spaces(stripped)

    m = _RE_EVERY_DOW.search(text)
    if m:
        day_word = m.group(1).lower()
        day_key = _DAY_ALIASES[day_word]
        stripped = (text[: m.start()] + text[m.end():]).strip()
        return Recurrence(f"weekly:{day_key}"), _collapse_spaces(stripped)

    return None, text


def _collapse_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()
