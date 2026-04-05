"""
Samantha OS — Intent Router
Maps natural language input to integration actions.

Strategy:
  1. Keyword matching (fast, no LLM call needed)
  2. If ambiguous, ask the LLM to classify the intent (uses the tool-use pattern)

The router returns either:
  - An integration action to execute
  - None (meaning: just have a normal conversation)
"""

from __future__ import annotations
import logging
import re
from dataclasses import dataclass

from integrations import IntegrationRegistry, IntegrationAction

logger = logging.getLogger("samantha.intent")


# Common English stopwords that should NOT contribute to example-overlap
# scoring. Without this filter, any sentence containing "me" and "to" would
# score 0.4 against the reminder examples and get misrouted.
_STOPWORDS = frozenset({
    "a", "an", "the", "i", "me", "my", "you", "your", "we", "us", "our",
    "he", "she", "it", "they", "them", "this", "that", "these", "those",
    "is", "am", "are", "was", "were", "be", "been", "being", "do", "does",
    "did", "have", "has", "had", "will", "would", "could", "should", "can",
    "may", "might", "must", "shall",
    "to", "of", "in", "on", "at", "for", "with", "by", "from", "as",
    "into", "about", "so", "or", "and", "but", "if", "because",
    "not", "no", "yes", "what", "where", "when", "who", "why", "how",
    "get", "got", "know", "tell", "say", "ask",
    "better", "more", "less", "some", "any",
})


@dataclass
class ResolvedIntent:
    integration_name: str
    action_name: str
    parameters: dict
    confidence: float  # 0.0 to 1.0


class IntentRouter:
    """Routes user messages to the appropriate integration action."""

    # Phrases that indicate the user just wants to chat, not trigger an action
    CHAT_SIGNALS = [
        "what do you think", "how do you feel", "tell me about yourself",
        "I feel", "I'm feeling", "let's talk", "what's your opinion",
        "do you like", "can you believe", "that's funny", "haha",
        "thanks", "thank you", "cool", "nice", "interesting",
        "good morning", "good night", "hello", "hi", "hey",
    ]

    def __init__(self, registry: IntegrationRegistry):
        self.registry = registry

    def route(self, user_text: str) -> ResolvedIntent | None:
        """Try to match user input to an integration action.
        Returns None if this should be a normal conversation."""

        text = user_text.lower().strip()

        # Skip very short messages
        if len(text.split()) < 2:
            return None

        # Check for chat signals — don't try to route these.
        # Use whole-word matching so short signals like "hi" don't match
        # inside unrelated words like "this" or "chi".
        for signal in self.CHAT_SIGNALS:
            if " " in signal:
                # Multi-word signals: substring match is safe.
                if signal in text:
                    return None
            else:
                # Single-word signals: require word boundaries.
                if re.search(rf"\b{re.escape(signal)}\b", text):
                    return None

        # Score each available action
        best_match: ResolvedIntent | None = None
        best_score = 0.0

        for intg_name, action in self.registry.get_all_actions():
            score = self._score_match(text, action)
            if score > best_score and score >= 0.3:  # Minimum threshold
                best_score = score
                best_match = ResolvedIntent(
                    integration_name=intg_name,
                    action_name=action.name,
                    parameters=self._extract_params(text, action),
                    confidence=score,
                )

        if best_match:
            logger.info(f"Intent: {best_match.action_name} ({best_match.confidence:.2f}) → {best_match.integration_name}")

        return best_match

    def _score_match(self, text: str, action: IntegrationAction) -> float:
        """Score how well the text matches an action based on keywords."""
        score = 0.0
        matched_keywords = 0

        for keyword in action.keywords:
            kw_lower = keyword.lower()
            if kw_lower in text:
                # Multi-word keywords get higher scores
                word_count = len(kw_lower.split())
                score += 0.3 * word_count
                matched_keywords += 1

        # Bonus for matching multiple keywords
        if matched_keywords > 1:
            score += 0.2

        # Check against example phrases for similarity. Filter out stopwords
        # so overlap on "me", "to", "the" doesn't promote unrelated sentences.
        text_words = {w for w in re.findall(r"\b\w+\b", text) if w not in _STOPWORDS}
        for example in action.examples:
            example_words = {
                w for w in re.findall(r"\b\w+\b", example.lower())
                if w not in _STOPWORDS
            }
            overlap = len(example_words & text_words)
            if overlap >= 2:
                score += 0.1 * overlap

        return min(score, 1.0)

    def _extract_params(self, text: str, action: IntegrationAction) -> dict:
        """Try to extract parameter values from the text.
        This is best-effort — the LLM will refine these."""
        params = {}

        # Email-related extraction
        email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text)
        if email_match and "to" in action.parameters:
            params["to"] = email_match.group()

        # Time extraction (basic)
        time_match = re.search(r'(\d{1,2})\s*(am|pm|:\d{2})', text, re.IGNORECASE)
        if time_match:
            params["time_hint"] = time_match.group()

        # Number extraction
        num_match = re.search(r'(\d+)\s*(minutes?|hours?|days?)', text)
        if num_match and "days_ahead" in action.parameters:
            val = int(num_match.group(1))
            unit = num_match.group(2).lower()
            if "day" in unit:
                params["days_ahead"] = val
            elif "hour" in unit:
                params["days_ahead"] = max(1, val // 24)

        # Category extraction — match words against categories listed after "Categories:"
        if "category" in action.parameters:
            cat_match = re.search(r'Categories:\s*(.+)', action.description, re.IGNORECASE)
            if cat_match:
                categories = [c.strip().lower() for c in cat_match.group(1).split(",")]
                for word in text.split():
                    word_clean = word.strip(".,!?").lower()
                    if word_clean in categories:
                        params["category"] = word_clean
                        break

        # Query extraction — everything after the keyword
        for kw in action.keywords:
            if kw in text:
                after = text.split(kw, 1)[-1].strip()
                if after and len(after) > 2:
                    # Use as query or content depending on action
                    if "query" in action.parameters:
                        params["query"] = after
                    elif "content" in action.parameters:
                        params["content"] = after
                    break

        return params

    def get_tools_description(self) -> str:
        """Generate a description of all available tools for the LLM system prompt."""
        lines = ["Available tools you can use:"]
        for intg_name, action in self.registry.get_all_actions():
            lines.append(f"  - {action.name}: {action.description}")
        return "\n".join(lines)

    def build_tool_prompt(self, user_text: str, intent: ResolvedIntent) -> str:
        """Build a prompt asking the LLM to extract structured parameters for an action."""
        action = None
        intg = self.registry.get(intent.integration_name)
        if intg:
            for a in intg.get_actions():
                if a.name == intent.action_name:
                    action = a
                    break

        if not action:
            return ""

        return f"""The user said: "{user_text}"

I detected this as a "{action.name}" action ({action.description}).
Required parameters: {', '.join(action.parameters)}
Pre-extracted: {intent.parameters}

Please extract the parameters as JSON, filling in any missing values from context.
Respond with ONLY a JSON object, nothing else. If a parameter can't be determined, use null."""
