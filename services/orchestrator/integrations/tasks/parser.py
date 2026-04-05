"""Time + recurrence parsing for the tasks integration.
Pure functions, no I/O."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import dateparser

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


# ─── Time parsing ──────────────────────────────────────────────────────


def parse_when(text: str, tz: str = "Europe/Stockholm") -> datetime:
    """Parse a natural-language time phrase into a UTC datetime.
    Raises ParseError if text is empty or unparseable."""
    if not text or not text.strip():
        raise ParseError("empty time phrase")

    # Strip filler words/punctuation dateparser doesn't handle.
    cleaned = re.sub(r"\s*o'?clock\s*", " ", text, flags=re.IGNORECASE)
    cleaned = cleaned.rstrip(".!?,").strip()

    # Disambiguate "at N" (bare hour) — dateparser treats "5" as day-of-month
    # and returns midnight. Pick the next N:00 that hasn't happened yet in
    # local time, so "at 5" said in the afternoon means 5pm today, and
    # "at 5" said at 9pm means 5am tomorrow.
    m = re.match(r"^at\s+(\d{1,2})$", cleaned, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        if 1 <= hour <= 23:
            try:
                from zoneinfo import ZoneInfo
                now_local = datetime.now(ZoneInfo(tz))
            except Exception:
                now_local = datetime.now()
            # If hour is 1-12, prefer the next "natural" occurrence:
            # pm if we're past noon and hour is in the afternoon range,
            # otherwise next occurrence forward.
            if hour <= 12:
                # Candidate A: today at <hour>:00 (24-hour)
                # Candidate B: today at <hour+12>:00 (24-hour)
                # Pick whichever is strictly in the future, preferring the
                # same half of day as now.
                candidates = [hour, hour + 12] if hour != 12 else [12, 0]
                # Sort so the closest future candidate comes first
                candidates_dt = []
                for h in candidates:
                    cand = now_local.replace(hour=h % 24, minute=0, second=0, microsecond=0)
                    if cand <= now_local:
                        cand = cand + timedelta(days=1)
                    candidates_dt.append(cand)
                chosen = min(candidates_dt)
                return chosen.astimezone(timezone.utc)
            else:
                # 13-23: unambiguous 24-hour
                cand = now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
                if cand <= now_local:
                    cand = cand + timedelta(days=1)
                return cand.astimezone(timezone.utc)

    dt = dateparser.parse(
        cleaned,
        settings={
            "TIMEZONE": tz,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(),
        },
    )
    if dt is None:
        raise ParseError(f"could not parse time from: {text!r}")

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
