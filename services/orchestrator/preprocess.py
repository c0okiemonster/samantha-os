"""Input preprocessing: language detection and translation to English.

Samantha's TTS model and intent router are English-only, but the user may
type or speak in Swedish (or other Scandinavian languages). We detect the
language with a fast heuristic and translate to English via the local LLM
before anything else sees the text.
"""
from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable

logger = logging.getLogger("samantha.preprocess")


# Scandinavian-only characters (å/ä/ö are rare-to-nonexistent in English)
_SCAND_CHARS = re.compile(r"[åäöÅÄÖ]")

# Common Swedish (and partially Norwegian/Danish) stopwords that rarely
# appear in English text. Whole-word matches only.
_SV_STOPWORDS = frozenset({
    "jag", "du", "är", "inte", "och", "det", "att", "en", "ett",
    "som", "på", "med", "för", "har", "kan", "men", "om", "mig",
    "dig", "han", "hon", "vi", "de", "detta", "där", "här", "så",
    "nu", "ja", "nej", "bara", "också", "man", "ska", "vill",
    "kommer", "när", "vad", "vem", "varför", "hur", "vilken",
    "imorgon", "idag", "ikväll", "igår", "påminn", "lägg", "till",
    "köp", "hämta", "möte", "varje", "måndag", "tisdag", "onsdag",
    "torsdag", "fredag", "lördag", "söndag", "vecka",
})


def detect_language(text: str) -> str:
    """Return 'sv' if text looks Scandinavian, otherwise 'en'.

    Uses a cheap heuristic:
    - Any å/ä/ö character → Swedish-ish.
    - Two or more Swedish stopwords as whole words → Swedish-ish.
    """
    if not text or not text.strip():
        return "en"

    if _SCAND_CHARS.search(text):
        return "sv"

    # Whole-word stopword check
    words = re.findall(r"\b\w+\b", text.lower())
    hits = sum(1 for w in words if w in _SV_STOPWORDS)
    if hits >= 2:
        return "sv"

    return "en"


LLMChat = Callable[[list[dict], int], Awaitable[str]]


async def translate_to_english(text: str, llm_chat: LLMChat) -> str:
    """Translate `text` to English via the local LLM.

    Returns the translated text on success, or the original text on any
    failure (the caller continues with the best available input).
    """
    prompt = (
        "Translate the following to English. Reply with ONLY the translation, "
        "no quotes, no explanation, no original text.\n\n"
        f"{text}"
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        result = await llm_chat(messages, 200)
    except Exception:
        logger.exception("translation failed; using original text")
        return text

    translated = (result or "").strip()
    # Strip common LLM preamble artefacts just in case the model ignored
    # the instruction and wrapped the translation in quotes.
    if len(translated) >= 2 and translated[0] in ('"', "'") and translated[-1] == translated[0]:
        translated = translated[1:-1].strip()
    # LLMs often append a trailing period to translations ("shopping list.")
    # which downstream intent/time parsers treat as part of the token.
    # Strip one trailing period if it wasn't part of the original input.
    if translated.endswith(".") and not text.rstrip().endswith("."):
        translated = translated[:-1].rstrip()

    return translated or text


async def maybe_translate(text: str, llm_chat: LLMChat) -> tuple[str, str]:
    """Return (processed_text, detected_language).

    If the language is not English, translate to English and log both.
    Otherwise return the text unchanged.
    """
    lang = detect_language(text)
    if lang == "en":
        return text, "en"

    translated = await translate_to_english(text, llm_chat)
    if translated != text:
        logger.info(f"🌐 Translated ({lang}→en): {text!r} → {translated!r}")
    return translated, lang
