"""Ollama HTTP client for vision-language models (moondream by default)."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger("samantha.vision.vlm")


# Generic scene description — used when the caller has no specific question.
VISION_PROMPT = (
    "Describe this image in 2-3 sentences. Focus on people, their clothing "
    "and accessories (glasses, hats, jewelry), notable objects they may be "
    "holding, and the overall scene. Be specific and literal. Do not invent "
    "details you cannot see."
)


def build_question_prompt(user_question: str) -> str:
    """Build a targeted VLM prompt when the user asked something specific.
    Context-aware prompting dramatically improves small-model accuracy."""
    return (
        f'The person in the image is asking: "{user_question}"\n\n'
        "Look carefully at the image and answer their question directly. "
        "Be literal and specific about what you actually see. If the thing "
        "they are asking about is visible, describe exactly where it is. "
        "If it is not visible in the image, say so clearly. "
        "Do not guess or invent. Keep your answer to 1-3 sentences."
    )


async def describe(
    image_b64: str,
    model: str,
    host: str,
    timeout_s: float,
    user_question: Optional[str] = None,
) -> str:
    """Call Ollama's /api/generate with an image. Returns the description
    text on success, empty string on any failure.

    If `user_question` is provided, a focused question-answering prompt is
    used instead of the generic scene description prompt — small VLMs like
    moondream answer targeted questions far more reliably than they
    synthesize open-ended descriptions.
    """
    prompt = (
        build_question_prompt(user_question)
        if user_question and user_question.strip()
        else VISION_PROMPT
    )
    url = f"http://{host}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 200,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()
    except Exception as e:
        logger.warning("VLM describe failed: %s: %s", type(e).__name__, e)
        return ""

    text = (body.get("response") or "").strip()
    return text
