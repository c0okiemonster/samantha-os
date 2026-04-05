"""Vision integration — on-demand webcam snapshots with observation memory."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Awaitable, Callable, Optional

from integrations import BaseIntegration, IntegrationAction

from . import vlm as vlm_module
from .models import Observation, SnapshotError, SnapshotResult
from .store import SCHEMA_SQL, VisionStore
from .voice import reword

logger = logging.getLogger("samantha.vision")


DEFAULT_VLM_MODEL = os.environ.get("VLM_MODEL", "moondream")
DEFAULT_VLM_HOST = os.environ.get("VLM_HOST", "host.docker.internal:11434")
DEFAULT_VLM_TIMEOUT_S = float(os.environ.get("VLM_TIMEOUT_S", "15"))


LLMChat = Callable[[list[dict], int], Awaitable[str]]


# ─── Noun extraction for recall queries ───────────────────────────────

_RECALL_LEAD_RE = re.compile(
    r"^\s*(?:what|when)\s+(?:did|do|was|were)\s+"
    r"(?:"
    r"you\s+(?:see(?:ing|n)?|saw|last\s+saw|last\s+see)"
    r"|"
    r"i\s+(?:look(?:ing|ed)?|wear(?:ing)?|wore)"
    r")\b\s*",
    re.IGNORECASE,
)

_RECALL_STOPWORDS = frozenset({
    "a", "an", "the", "i", "me", "my", "you", "your",
    "this", "that", "these", "those",
    "in", "on", "at", "for", "with", "to", "of",
    "earlier", "today", "yesterday", "morning", "afternoon",
    "evening", "night", "ago", "last",
    "like", "wearing",
})


def _extract_recall_noun(text: str) -> str:
    """Pull a content noun from a recall question. Empty string if none."""
    stripped = _RECALL_LEAD_RE.sub("", text.lower()).strip()
    stripped = stripped.rstrip("?.!,")
    tokens = re.findall(r"\b\w+\b", stripped)
    for tok in tokens:
        if tok not in _RECALL_STOPWORDS:
            return tok
    return ""


class VisionIntegration(BaseIntegration):
    name = "vision"
    display_name = "Vision"
    description = "Let Samantha see you through the webcam when you allow it"
    icon = "👁️"
    requires_auth = False

    def __init__(self):
        super().__init__()
        self.conn: Optional[sqlite3.Connection] = None
        self.store: Optional[VisionStore] = None
        self.vlm_model: str = DEFAULT_VLM_MODEL
        self.vlm_host: str = DEFAULT_VLM_HOST
        self.vlm_timeout_s: float = DEFAULT_VLM_TIMEOUT_S
        self.llm_chat: Optional[LLMChat] = None

    async def initialize(self, config: dict) -> bool:
        # The main.py lifespan wires store/llm_chat after ConversationMemory
        # is ready. Returning True here so the registry counts us as configured.
        return True

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="take_snapshot",
                description="Look through the webcam and describe what you see",
                keywords=[
                    "what do you see", "look at me", "what am i wearing",
                    "describe what you see", "can you see me", "look around",
                    "take a look",
                ],
                parameters=["text"],
                examples=[
                    "What do you see?",
                    "Look at me — what am I wearing today?",
                    "Take a look around",
                ],
            ),
            IntegrationAction(
                name="recall_observation",
                description="Recall something Samantha saw earlier",
                keywords=[
                    "what did you see", "when did you last see",
                    "what did i look like", "what was i wearing",
                    "remember what you saw",
                ],
                parameters=["text"],
                examples=[
                    "What did you see this morning?",
                    "When did you last see my plant?",
                    "What was I wearing yesterday?",
                ],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        """Back-compat dict interface; prefer handle_action."""
        text = params.get("text") or ""
        image_b64 = params.get("image_b64")
        result = await self.handle_action(action_name, text, image_b64=image_b64)
        return {
            "spoken": result.spoken,
            "observation_id": result.observation_id,
            "overlay": None,
        }

    async def handle_action(
        self,
        action_name: str,
        user_text: str,
        image_b64: Optional[str] = None,
    ) -> SnapshotResult:
        if action_name == "take_snapshot":
            return await self._take_snapshot(user_text, image_b64)
        if action_name == "recall_observation":
            return await self._recall_observation(user_text)
        return SnapshotResult(
            spoken=f"I don't know how to {action_name}.",
            observation_id=None,
            overlay=None,
        )

    async def _take_snapshot(
        self, user_text: str, image_b64: Optional[str]
    ) -> SnapshotResult:
        if not image_b64:
            return SnapshotResult(
                spoken=(
                    "My eyes are closed right now. Enable vision in the "
                    "top-right corner if you'd like me to see."
                ),
                observation_id=None,
                overlay=None,
            )

        raw = await vlm_module.describe(
            image_b64=image_b64,
            model=self.vlm_model,
            host=self.vlm_host,
            timeout_s=self.vlm_timeout_s,
        )
        if not raw:
            return SnapshotResult(
                spoken=(
                    "My vision's a bit fuzzy right now — I can't quite make "
                    "out what I'm seeing."
                ),
                observation_id=None,
                overlay=None,
            )

        spoken = raw
        if self.llm_chat is not None:
            spoken = await reword(raw, user_text, self.llm_chat)

        obs = self.store.create_observation(
            raw_description=raw,
            spoken_text=spoken,
            user_trigger=user_text,
        )
        return SnapshotResult(
            spoken=spoken,
            observation_id=obs.id,
            overlay=None,
        )

    async def _recall_observation(self, user_text: str) -> SnapshotResult:
        noun = _extract_recall_noun(user_text)
        obs = self.store.search_by_text(noun)
        if obs is None:
            if noun:
                return SnapshotResult(
                    spoken=f"I haven't seen anything matching {noun} yet.",
                    observation_id=None,
                    overlay=None,
                )
            return SnapshotResult(
                spoken="I haven't opened my eyes yet today.",
                observation_id=None,
                overlay=None,
            )
        return SnapshotResult(
            spoken=obs.spoken_text,
            observation_id=obs.id,
            overlay=None,
        )
