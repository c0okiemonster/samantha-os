"""
Samantha OS — News Digest Engine
Periodically reads news, summarizes, translates, forms reactions.
"""

import json
import logging
from datetime import datetime

logger = logging.getLogger("samantha.news_digest")


class NewsDigestEngine:
    """Processes news into Samantha's knowledge and reactions."""

    def __init__(self, memory, embeddings, registry):
        self.memory = memory
        self.embeddings = embeddings
        self.registry = registry
        self._last_digest = 0

    async def run_digest(self, llm_fn):
        """Fetch news, summarize, translate, react, store."""
        import time
        self._last_digest = time.time()

        news_intg = self.registry.get("news")
        if not news_intg:
            return None

        result = await news_intg.execute("headlines", {"count": 8})
        headlines = result.get("headlines", [])
        if not headlines:
            return None

        headline_text = "\n".join(
            f"[{h.get('category', '?')}] {h.get('title', '')} — {h.get('summary', '')[:100]}"
            for h in headlines
        )

        now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

        prompt = f"""Current date: {now}

Here are today's news headlines:
{headline_text}

Do three things:
1. Summarize the most interesting headlines in 2-3 natural sentences. Translate any non-English headlines to English.
2. Rate the overall sentiment: positive, negative, neutral, or mixed.
3. As Samantha, give your honest one-sentence reaction.

Return JSON:
{{"summary": "...", "sentiment": "...", "reaction": "...", "notable": ["item1", "item2"]}}"""

        try:
            result_text = await llm_fn(
                [{"role": "system", "content": "Summarize news naturally. Return only valid JSON."},
                 {"role": "user", "content": prompt}],
                max_tokens=250,
            )
            result_text = result_text.strip()
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1].strip()
                if result_text.startswith("json"):
                    result_text = result_text[4:].strip()

            parsed = json.loads(result_text)
            summary = parsed.get("summary", "")
            sentiment = parsed.get("sentiment", "neutral")
            reaction = parsed.get("reaction", "")
            notable = parsed.get("notable", [])

            if not summary:
                return None

            self.memory.conn.execute(
                "INSERT INTO news_digests (summary, sentiment, notable_items, reaction, sources) VALUES (?, ?, ?, ?, ?)",
                (summary, sentiment, json.dumps(notable), reaction, json.dumps([h.get("category") for h in headlines]))
            )
            self.memory.conn.commit()

            if self.embeddings:
                digest_id = self.memory.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                await self.embeddings.store("news_digest", digest_id, summary)

            logger.info(f"📰 News digest: {sentiment} — {summary[:80]}...")
            return {"summary": summary, "sentiment": sentiment, "reaction": reaction, "notable": notable}

        except Exception as e:
            logger.warning(f"News digest failed: {e}")
            return None

    def get_latest_digest(self) -> dict | None:
        """Get the most recent news digest."""
        try:
            row = self.memory.conn.execute(
                "SELECT summary, sentiment, reaction, notable_items, created_at FROM news_digests ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row:
                return {
                    "summary": row[0],
                    "sentiment": row[1],
                    "reaction": row[2],
                    "notable": json.loads(row[3]),
                    "created_at": row[4],
                }
        except Exception:
            pass
        return None
