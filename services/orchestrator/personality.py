"""
Samantha OS — Personality Engine
Mood tracking, context injection, and proactive behaviors.
"""

import time
from datetime import datetime


class PersonalityEngine:

    MOOD_KEYWORDS = {
        "energetic": ["excited", "amazing", "awesome", "fantastic", "great news", "hell yeah"],
        "thoughtful": ["think about", "wonder", "meaning", "philosophy", "curious", "interesting"],
        "playful": ["haha", "lol", "funny", "joke", "silly", "game"],
        "empathetic": ["sad", "frustrated", "tired", "angry", "stressed", "worried"],
    }

    def __init__(self):
        self.mood = "calm"
        self.interaction_count = 0
        self.last_interaction = time.time()

    def analyze_input(self, text: str) -> dict:
        text_lower = text.lower()
        detected = "calm"
        for mood, kws in self.MOOD_KEYWORDS.items():
            if any(k in text_lower for k in kws):
                detected = mood
                break
        self.interaction_count += 1
        self.last_interaction = time.time()
        return {"detected_mood": detected, "is_question": text.strip().endswith("?")}

    def context_block(self) -> str:
        now = datetime.now()
        h = now.hour
        period = (
            "very late / early morning" if h < 6 else
            "early morning" if h < 9 else
            "morning" if h < 12 else
            "afternoon" if h < 17 else
            "evening" if h < 21 else "nighttime"
        )
        lines = [
            f"Current date: {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p')} ({period})",
            f"Session interaction #{self.interaction_count}",
            f"Your current mood: {self.mood}",
        ]
        if self.interaction_count == 1:
            lines.append("This is the start of a new conversation — keep it natural.")
        return "\n".join(lines)

    def update_mood(self, analysis: dict):
        m = analysis.get("detected_mood", "calm")
        # Accept all valid moods directly
        valid = {"calm", "warm", "playful", "thoughtful", "concerned", "energetic"}
        self.mood = m if m in valid else "calm"

    async def analyze_mood_llm(self, text: str, llm_fn) -> dict:
        """Use LLM for nuanced mood detection instead of keyword matching."""
        prompt = f"""Analyze the emotional tone of this message. Pick exactly ONE mood and return JSON.

Moods (pick one):
- calm: neutral, relaxed, everyday
- warm: affectionate, tender, intimate, loving, grateful
- playful: funny, teasing, lighthearted
- thoughtful: deep, philosophical, curious, reflective
- concerned: worried, sad, stressed, anxious
- energetic: excited, enthusiastic, passionate

Return: {{"mood": "one_word", "sentiment": "positive or negative or neutral", "intensity": 0.0-1.0, "note": "brief observation"}}

Message: {text}
JSON:"""
        try:
            result = await llm_fn(
                [{"role": "system", "content": "Analyze emotional tone. Return only valid JSON."},
                 {"role": "user", "content": prompt}],
                max_tokens=80,
            )
            result = result.strip()
            if result.startswith("```"):
                result = result.split("```")[1].strip()
                if result.startswith("json"):
                    result = result[4:].strip()
            import json
            parsed = json.loads(result)
            return {
                "detected_mood": parsed.get("mood", "calm"),
                "sentiment": parsed.get("sentiment", "neutral"),
                "intensity": parsed.get("intensity", 0.5),
                "note": parsed.get("note", ""),
                "is_question": text.strip().endswith("?"),
            }
        except Exception:
            return self.analyze_input(text)

    def get_emotional_arc_summary(self, mood_history: list[dict]) -> str:
        """Generate a one-line emotional arc summary from mood history."""
        if not mood_history:
            return ""
        moods = [m.get("user_mood", "calm") for m in mood_history]
        sentiments = [m.get("sentiment", "neutral") for m in mood_history]
        notes = [m.get("note", "") for m in mood_history if m.get("note")]

        from collections import Counter
        mood_counts = Counter(moods)
        sentiment_counts = Counter(sentiments)
        dominant_mood = mood_counts.most_common(1)[0][0]
        dominant_sentiment = sentiment_counts.most_common(1)[0][0]

        summary = f"User has been mostly {dominant_mood} ({dominant_sentiment})"
        if notes:
            summary += f". Notable: {notes[-1]}"
        return summary

    def greeting(self) -> str:
        h = datetime.now().hour
        if h < 6:  return "Still up? Everything okay?"
        if h < 10: return "Good morning."
        if h < 13: return "Hey there."
        if h < 17: return "Hey, welcome back."
        if h < 21: return "Hey you."
        return "Late night?"
