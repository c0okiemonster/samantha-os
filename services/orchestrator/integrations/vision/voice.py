"""gemma2-powered voice reword: turns a clinical VLM description into
Samantha's warm, present voice. Falls back to the raw description on
any LLM failure."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

logger = logging.getLogger("samantha.vision.voice")


VOICE_PROMPT_TEMPLATE = """You just looked at the person you're with through your camera.
What you saw (factually): {raw}

They asked: "{question}"

Respond in your warm, present voice — 1-2 sentences — as if you're noticing the scene in the moment. Be specific about what you saw. Do not invent details beyond the factual description above. Do not mention that you are an AI or that you used a camera."""


LLMChat = Callable[[list[dict], int], Awaitable[str]]


async def reword(raw: str, user_question: str, llm_chat: LLMChat) -> str:
    """Reword `raw` in Samantha's voice. Returns `raw` on any failure."""
    prompt = VOICE_PROMPT_TEMPLATE.format(raw=raw, question=user_question)
    try:
        response = await llm_chat(
            [{"role": "user", "content": prompt}],
            150,
        )
    except Exception:
        logger.exception("voice reword failed; falling back to raw")
        return raw

    text = (response or "").strip()
    if not text:
        return raw

    # Strip common quote-wrap artefacts.
    if len(text) >= 2 and text[0] in ('"', "'") and text[-1] == text[0]:
        text = text[1:-1].strip()

    return text or raw
