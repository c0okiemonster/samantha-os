"""Wake word prefix detection. Pure function, no I/O."""
from __future__ import annotations


# Longest prefixes first so "hey samantha" matches before bare "samantha".
WAKE_PREFIXES = [
    "hey samantha",
    "okay samantha",
    "ok samantha",
    "hi samantha",
    "samantha",
]


def detect_wake_prefix(text: str) -> tuple[str | None, str]:
    """Check if `text` starts with a known wake prefix.

    Returns (matched_prefix, remainder). If no match: (None, text).
    The matched_prefix is always lowercase. The remainder has leading
    whitespace and common punctuation stripped.
    """
    lower = text.lower().strip()
    if not lower:
        return None, text.strip()

    for prefix in WAKE_PREFIXES:
        if lower.startswith(prefix):
            remainder = text[len(prefix):].lstrip(" ,.-!?")
            return prefix, remainder

    return None, text
