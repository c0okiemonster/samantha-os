"""
Samantha OS — Proactive Behaviors (Phase 3)

Samantha doesn't just respond — she initiates when appropriate.
This module manages time-aware behaviors, silence handling,
and contextual check-ins.
"""

from __future__ import annotations
import time
import logging
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger("samantha.proactive")


@dataclass
class ProactiveEvent:
    type: str           # "greeting", "checkin", "reminder", "mood_shift", "card"
    message: str | None
    mood: str | None = None
    card_title: str | None = None
    card_body: str | None = None
    priority: int = 0   # higher = more important


class ProactiveBehavior:
    """Manages Samantha's proactive behaviors."""

    def __init__(self):
        self.session_start: float = time.time()
        self.last_interaction: float = time.time()
        self.last_proactive: float = 0
        self.has_greeted: bool = False
        self.interaction_count: int = 0
        self.daily_checkin_done: bool = False
        self._cooldown: float = 300  # min seconds between proactive events

    def on_interaction(self):
        self.last_interaction = time.time()
        self.interaction_count += 1

    def check(self) -> ProactiveEvent | None:
        """Called periodically. Returns an event if Samantha should do something."""
        now = time.time()

        # Cooldown — don't be annoying
        if now - self.last_proactive < self._cooldown:
            return None

        silence = now - self.last_interaction
        hour = datetime.now().hour

        # ─── Session greeting ─────────────────
        if not self.has_greeted:
            self.has_greeted = True
            self.last_proactive = now
            return ProactiveEvent(
                type="greeting",
                message=self._greeting_for_hour(hour),
                mood="calm",
                card_title="Samantha",
                card_body=self._greeting_for_hour(hour),
            )

        # ─── Morning briefing (first interaction of the day, 7-10am) ───
        if not self.daily_checkin_done and 7 <= hour <= 10 and self.interaction_count >= 1:
            self.daily_checkin_done = True
            self.last_proactive = now
            return ProactiveEvent(
                type="morning_briefing",
                message=None,
                card_title="Good Morning",
                card_body="Let me see what's happening today...",
                priority=1,
            )

        # ─── Silence comfort (5+ minutes) ────
        if silence > 300 and silence < 360:
            self.last_proactive = now
            return ProactiveEvent(
                type="mood_shift",
                message=None,
                mood="calm",
            )

        # ─── Long silence check-in (20+ minutes) ──
        if silence > 1200 and silence < 1260:
            self.last_proactive = now
            if hour >= 22 or hour < 6:
                return ProactiveEvent(
                    type="card",
                    message=None,
                    card_title="",
                    card_body="Still here if you need me.",
                    mood="calm",
                )

        # ─── Late night nudge (after 1am) ─────
        if hour >= 1 and hour < 5 and silence > 600:
            self.last_proactive = now
            return ProactiveEvent(
                type="card",
                message=None,
                card_title="Late Night",
                card_body="It's getting late. Don't forget to rest.",
                mood="calm",
            )

        return None

    def _greeting_for_hour(self, hour: int) -> str:
        if hour < 5:   return "Hey. Couldn't sleep?"
        if hour < 8:   return "Good morning. Early start today."
        if hour < 12:  return "Good morning."
        if hour < 14:  return "Hey there."
        if hour < 17:  return "Hey, welcome back."
        if hour < 20:  return "Hey you. How was your day?"
        if hour < 23:  return "Evening."
        return "Late night?"

    def get_morning_briefing_prompt(self) -> str:
        """Prompt for the LLM to generate a morning briefing from integration data."""
        return """Based on the tool results below, give me a brief, warm morning briefing.
Keep it natural — you're telling a friend what's coming up today.
Mention the weather, any meetings, and unread email count if relevant.
Keep it under 3 sentences. Don't use bullet points."""
