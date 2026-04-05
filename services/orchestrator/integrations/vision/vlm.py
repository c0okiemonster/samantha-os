"""Ollama HTTP client for vision-language models (moondream by default)."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("samantha.vision.vlm")


VISION_PROMPT = (
    "Describe this image in 1-2 concise sentences. Focus on people, notable "
    "objects, and the overall scene. Do not invent details you cannot see."
)


async def describe(
    image_b64: str,
    model: str,
    host: str,
    timeout_s: float,
) -> str:
    """Call Ollama's /api/generate with an image. Returns the description
    text on success, empty string on any failure."""
    url = f"http://{host}/api/generate"
    payload = {
        "model": model,
        "prompt": VISION_PROMPT,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 150,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()
    except Exception:
        logger.exception("VLM describe failed")
        return ""

    text = (body.get("response") or "").strip()
    return text
