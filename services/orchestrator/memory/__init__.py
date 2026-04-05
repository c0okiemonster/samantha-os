"""
Samantha OS — Conversation Memory (Phase 3)

Long-term memory that persists across sessions.
Uses SQLite FTS5 for full-text search (no vector DB needed).

Three memory layers:
  1. EPISODIC  — Summaries of past conversations (auto-generated)
  2. SEMANTIC  — Facts about the user (extracted from conversation)
  3. EMOTIONAL — Mood/emotional arc over time

The memory system injects relevant context into the LLM prompt
so Samantha genuinely "remembers" past interactions.
"""

from __future__ import annotations
import os
import re
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger("samantha.memory")


class ConversationMemory:
    """Persistent memory system for Samantha."""

    def __init__(self, db_path: str = "config/samantha_memory.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        # ── Legacy cleanup: drop old NotesIntegration reminders table if it has
        # the old schema. Safe no-op if the table doesn't exist or is already new.
        cols = {
            r[1]
            for r in self.conn.execute("PRAGMA table_info(reminders)").fetchall()
        }
        if cols and "content" in cols and "trigger_at" not in cols:
            self.conn.execute("DROP TABLE IF EXISTS reminders")
            self.conn.execute("DROP INDEX IF EXISTS idx_reminders_pending")
            self.conn.commit()

        self.conn.executescript("""
            -- Episodic memory: conversation summaries
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL,
                topics TEXT DEFAULT '[]',
                mood_arc TEXT DEFAULT 'neutral',
                message_count INTEGER DEFAULT 0,
                started_at TIMESTAMP,
                ended_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Semantic memory: facts about the user and their world
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL DEFAULT 'user',
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 0.8,
                source TEXT DEFAULT 'conversation',
                learned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_referenced TIMESTAMP,
                UNIQUE(subject, category, key)
            );

            -- Entities: people, pets, places the user has mentioned
            CREATE TABLE IF NOT EXISTS entities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                relation TEXT,
                aliases TEXT DEFAULT '[]',
                first_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_mentioned TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Emotional arc: mood samples over time
            CREATE TABLE IF NOT EXISTS mood_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_mood TEXT,
                samantha_mood TEXT,
                trigger TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Full-text search on episodes and facts
            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                summary, topics, content=episodes, content_rowid=id
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
                category, key, value, content=facts, content_rowid=id
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                INSERT INTO episodes_fts(rowid, summary, topics) VALUES (new.id, new.summary, new.topics);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                INSERT INTO facts_fts(rowid, category, key, value) VALUES (new.id, new.category, new.key, new.value);
            END;
            CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
                UPDATE facts_fts SET category=new.category, key=new.key, value=new.value WHERE rowid=new.id;
            END;

            -- News digests
            CREATE TABLE IF NOT EXISTS news_digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL,
                sentiment TEXT DEFAULT 'neutral',
                notable_items TEXT DEFAULT '[]',
                reaction TEXT DEFAULT '',
                sources TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Tasks integration: reminders (new schema), schedule events, lists
            CREATE TABLE IF NOT EXISTS reminders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                text          TEXT NOT NULL,
                trigger_at    TIMESTAMP NOT NULL,
                created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                fired_at      TIMESTAMP,
                cancelled_at  TIMESTAMP,
                entity_id     INTEGER,
                source_text   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_due
                ON reminders(trigger_at) WHERE fired_at IS NULL AND cancelled_at IS NULL;

            CREATE TABLE IF NOT EXISTS schedule_events (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                title               TEXT NOT NULL,
                start_at            TIMESTAMP NOT NULL,
                duration_min        INTEGER,
                recurrence          TEXT,
                notes               TEXT,
                entity_id           INTEGER,
                created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                heads_up_fired_at   TIMESTAMP,
                fired_at            TIMESTAMP,
                cancelled_at        TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_schedule_due
                ON schedule_events(start_at) WHERE cancelled_at IS NULL;

            CREATE TABLE IF NOT EXISTS list_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                list_name   TEXT NOT NULL,
                text        TEXT NOT NULL,
                added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                done_at     TIMESTAMP,
                position    INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_list_active
                ON list_items(list_name, position) WHERE done_at IS NULL;

            -- Vision: observations captured from webcam snapshots
            CREATE TABLE IF NOT EXISTS observations (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_description TEXT NOT NULL,
                spoken_text     TEXT NOT NULL,
                user_trigger    TEXT,
                created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleted_at      TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_observations_time
                ON observations(created_at DESC) WHERE deleted_at IS NULL;
        """)
        self.conn.commit()

        # Migration: add unresolved_threads if missing
        try:
            self.conn.execute("ALTER TABLE episodes ADD COLUMN unresolved_threads TEXT DEFAULT '[]'")
            self.conn.commit()
        except Exception:
            pass  # column already exists

        # Migration: enhanced mood log
        for col, default in [("sentiment", "'neutral'"), ("intensity", "0.5"), ("note", "''")]:
            try:
                self.conn.execute(f"ALTER TABLE mood_log ADD COLUMN {col} TEXT DEFAULT {default}")
                self.conn.commit()
            except Exception:
                pass

        # Migration: add subject column to facts (for entity-aware memory)
        try:
            self.conn.execute("ALTER TABLE facts ADD COLUMN subject TEXT DEFAULT 'user'")
            self.conn.commit()
        except Exception:
            pass

        # Migration: add deleted_at to timelined tables for the Memory Timeline UI
        # (observations already has deleted_at from the vision feature)
        for _tbl in ("facts", "entities", "episodes", "mood_log", "news_digests"):
            try:
                self.conn.execute(f"ALTER TABLE {_tbl} ADD COLUMN deleted_at TIMESTAMP")
                self.conn.commit()
            except Exception:
                pass  # column already exists

    # ─── Episodic Memory ──────────────────

    def save_episode(self, summary: str, topics: list[str], mood_arc: str,
                     message_count: int, started_at: str, unresolved_threads: list[str] | None = None):
        """Save a conversation summary."""
        threads_json = json.dumps(unresolved_threads or [])
        self.conn.execute(
            "INSERT INTO episodes (summary, topics, mood_arc, message_count, started_at, unresolved_threads) VALUES (?, ?, ?, ?, ?, ?)",
            (summary, json.dumps(topics), mood_arc, message_count, started_at, threads_json)
        )
        self.conn.commit()
        logger.info(f"Saved episode: {topics}")

    def search_episodes(self, query: str, limit: int = 5) -> list[dict]:
        """Search past conversation summaries."""
        # Sanitize for FTS5: extract words only, join with OR
        import re as _re
        words = _re.findall(r'\b\w{3,}\b', query)
        if not words:
            return []
        fts_query = " OR ".join(f'"{w}"' for w in words[:10])
        try:
            rows = self.conn.execute(
                "SELECT e.* FROM episodes e JOIN episodes_fts f ON e.id = f.rowid WHERE episodes_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_recent_episodes(self, limit: int = 5) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM episodes ORDER BY ended_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── Semantic Memory ──────────────────

    def learn_fact(self, category: str, key: str, value: str, confidence: float = 0.8, subject: str = "user"):
        """Store or update a fact. Subject defaults to 'user' but can be any entity name."""
        self.conn.execute(
            """INSERT INTO facts (subject, category, key, value, confidence)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(subject, category, key) DO UPDATE SET
                 value=excluded.value,
                 confidence=MAX(facts.confidence, excluded.confidence),
                 learned_at=CURRENT_TIMESTAMP""",
            (subject, category, key, value, confidence)
        )
        self.conn.commit()
        logger.info(f"Learned: [{subject}/{category}] {key} = {value}")

    def add_entity(self, name: str, entity_type: str, relation: str = None, aliases: list = None):
        """Register a new entity (person, pet, place) the user mentioned."""
        try:
            self.conn.execute(
                "INSERT INTO entities (name, type, relation, aliases) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET last_mentioned=CURRENT_TIMESTAMP",
                (name, entity_type, relation, json.dumps(aliases or []))
            )
            self.conn.commit()
        except Exception as e:
            logger.debug(f"Entity add failed: {e}")

    def get_entities(self) -> list[dict]:
        """Get all known entities."""
        try:
            rows = self.conn.execute(
                "SELECT name, type, relation, aliases FROM entities ORDER BY last_mentioned DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    async def extract_facts_llm(self, user_text: str, assistant_text: str, llm_fn) -> list[tuple]:
        """Extract facts with entity awareness. The LLM sees known entities to avoid confusion."""
        # Show the LLM what it already knows to prevent mixing up people
        entities = self.get_entities()
        entity_summary = ""
        if entities:
            entity_lines = []
            for e in entities[:15]:
                rel = f" ({e['relation']})" if e.get('relation') else ""
                entity_lines.append(f"  - {e['name']}{rel}: {e['type']}")
            entity_summary = "Known people/pets/places:\n" + "\n".join(entity_lines) + "\n\n"

        prompt = f"""Extract NEW facts about the user or people/things in their life.

{entity_summary}Each fact: {{"subject": "user" or an entity name, "category": "...", "key": "short_label", "value": "specific detail", "importance": "high|medium|low"}}

STRICT RULES:
1. Only extract from USER's messages. Samantha's words are NOT facts about the user.
2. Every fact has a SUBJECT:
   - "user" = facts about the user themselves
   - "Jussi", "Daniel" etc = facts about someone else they mentioned
3. If the user mentions a new person/pet/place, also add an entity:
   {{"entity": {{"name": "Daniel", "type": "person", "relation": "friend"}}}}
4. NO extraction from:
   - Samantha's feelings, thoughts, or imagination
   - News headlines or world events
   - Hypothetical scenarios or roleplay
   - Vague emotional states ("feels good", "is thinking")
5. Use specific, stable keys: "cat_name", "employer", "birthday" — not "name", "friend"

User message: {user_text}
Samantha replied: {assistant_text}

Return JSON array (facts + entity definitions mixed). Empty array if nothing factual:"""

        try:
            result = await llm_fn(
                [{"role": "system", "content": "Extract facts strictly. Return only JSON arrays. No explanation, no markdown."},
                 {"role": "user", "content": prompt}],
                max_tokens=400,
            )
            result = result.strip()
            if result.startswith("```"):
                result = result.split("```")[1].strip()
                if result.startswith("json"):
                    result = result[4:].strip()
            items = json.loads(result)
            if not isinstance(items, list):
                return []

            stored = []
            for item in items:
                # Entity definition
                if "entity" in item:
                    e = item["entity"]
                    if e.get("name"):
                        self.add_entity(
                            name=e["name"],
                            entity_type=e.get("type", "person"),
                            relation=e.get("relation"),
                        )
                    continue

                # Fact
                subject = item.get("subject", "user")
                cat = item.get("category", "personal")
                key = item.get("key", "")
                val = item.get("value", "")
                imp = item.get("importance", "medium")
                if key and val:
                    confidence = {"high": 0.95, "medium": 0.8, "low": 0.6}.get(imp, 0.8)
                    self.learn_fact(cat, key, val, confidence, subject=subject)
                    stored.append((subject, cat, key, val))
            return stored
        except (json.JSONDecodeError, Exception) as e:
            logger.debug(f"LLM fact extraction failed: {e}")
            return []

    async def generate_summary_llm(self, messages: list[dict], llm_fn) -> tuple[str, list[str]]:
        """Generate episode summary and unresolved threads via LLM."""
        transcript = []
        for m in messages[-20:]:
            role = "User" if m.get("role") == "user" else "Samantha"
            transcript.append(f"{role}: {m.get('content', '')[:150]}")
        transcript_text = "\n".join(transcript)

        prompt = f"""Summarize this conversation from Samantha's perspective in 2-3 sentences.
Then list any unresolved topics worth following up on next time.

Conversation:
{transcript_text}

Return JSON: {{"summary": "...", "threads": ["topic1", "topic2"]}}"""

        try:
            result = await llm_fn(
                [{"role": "system", "content": "Summarize conversations. Return only valid JSON."},
                 {"role": "user", "content": prompt}],
                max_tokens=200,
            )
            result = result.strip()
            if result.startswith("```"):
                result = result.split("```")[1].strip()
                if result.startswith("json"):
                    result = result[4:].strip()
            parsed = json.loads(result)
            summary = parsed.get("summary", "")
            threads = parsed.get("threads", [])
            if not summary:
                raise ValueError("Empty summary")
            return summary, threads
        except Exception as e:
            logger.debug(f"LLM summary failed, using heuristic: {e}")
            summarizer = ConversationSummarizer()
            summary = summarizer.generate_summary(messages)
            return summary, []

    def recall_facts(self, category: Optional[str] = None, limit: int = 30) -> list[dict]:
        """Get all known facts, optionally filtered by category."""
        if category:
            rows = self.conn.execute(
                "SELECT * FROM facts WHERE category = ? ORDER BY confidence DESC, learned_at DESC LIMIT ?",
                (category, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM facts ORDER BY confidence DESC, learned_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def search_facts(self, query: str, limit: int = 10) -> list[dict]:
        import re as _re
        words = _re.findall(r'\b\w{3,}\b', query)
        if not words:
            return []
        fts_query = " OR ".join(f'"{w}"' for w in words[:10])
        try:
            rows = self.conn.execute(
                "SELECT f.* FROM facts f JOIN facts_fts ff ON f.id = ff.rowid WHERE facts_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def forget_fact(self, category: str, key: str):
        self.conn.execute("DELETE FROM facts WHERE category=? AND key=?", (category, key))
        self.conn.commit()

    # ─── Emotional Arc ────────────────────

    def log_mood(self, user_mood: str, samantha_mood: str, trigger: str = "",
                 sentiment: str = "neutral", intensity: float = 0.5, note: str = ""):
        self.conn.execute(
            "INSERT INTO mood_log (user_mood, samantha_mood, trigger, sentiment, intensity, note) VALUES (?, ?, ?, ?, ?, ?)",
            (user_mood, samantha_mood, trigger, sentiment, intensity, note)
        )
        self.conn.commit()

    def get_mood_history(self, hours: int = 24) -> list[dict]:
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM mood_log WHERE timestamp > ? ORDER BY timestamp DESC",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dominant_mood(self, hours: int = 4) -> str:
        """What's the user's overall mood been recently?"""
        moods = self.get_mood_history(hours)
        if not moods:
            return "unknown"
        # Count occurrences
        counts: dict[str, int] = {}
        for m in moods:
            um = m.get("user_mood", "neutral")
            counts[um] = counts.get(um, 0) + 1
        return max(counts, key=counts.get)

    def get_unresolved_threads(self, limit: int = 5) -> list[dict]:
        """Get recent unresolved conversation threads."""
        rows = self.conn.execute(
            "SELECT unresolved_threads, ended_at FROM episodes WHERE unresolved_threads != '[]' ORDER BY ended_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        threads = []
        for row in rows:
            items = json.loads(row[0])
            for item in items:
                threads.append({"topic": item, "from_date": row[1]})
        return threads[:limit]

    # ─── Context Builder ──────────────────

    async def build_context(self, current_input: str = "", embeddings=None) -> str:
        """Build rich memory context, organized by entity (user + people/pets/places)."""
        sections = []

        # 1. Facts organized by subject (user first, then other entities)
        try:
            facts = self.conn.execute(
                "SELECT subject, category, key, value FROM facts ORDER BY subject='user' DESC, confidence DESC LIMIT 40"
            ).fetchall()
        except Exception:
            facts = self.conn.execute(
                "SELECT 'user' as subject, category, key, value FROM facts ORDER BY confidence DESC LIMIT 40"
            ).fetchall()

        if facts:
            by_subject = {}
            for f in facts:
                subj = f['subject'] if 'subject' in f.keys() else 'user'
                if subj not in by_subject:
                    by_subject[subj] = []
                by_subject[subj].append(f"{f['key']}: {f['value']}")

            fact_sections = []
            # User facts first
            if 'user' in by_subject:
                fact_sections.append("About the user:\n  " + "\n  ".join(by_subject['user']))
                del by_subject['user']
            # Other entities
            for subject, items in by_subject.items():
                fact_sections.append(f"About {subject}:\n  " + "\n  ".join(items))
            sections.append("\n\n".join(fact_sections))

        # 1b. Known entities for reference
        entities = self.get_entities()
        if entities:
            ent_lines = []
            for e in entities[:10]:
                rel = f" ({e['relation']})" if e.get('relation') else ""
                ent_lines.append(f"  - {e['name']}{rel}: {e['type']}")
            sections.append("People and things in their life:\n" + "\n".join(ent_lines))

        # 2. Your shared history
        episodes = self.get_recent_episodes(5)
        if episodes:
            ep_lines = []
            for ep in episodes:
                threads = json.loads(ep.get("unresolved_threads", "[]"))
                thread_note = f" (unfinished: {', '.join(threads)})" if threads else ""
                ep_lines.append(f"  - {ep['ended_at']}: {ep['summary']}{thread_note}")
            sections.append("Your conversation history together:\n" + "\n".join(ep_lines))

        # 3. Things to naturally follow up on
        threads = self.get_unresolved_threads(5)
        if threads:
            thread_lines = [f"  - {t['topic']} ({t['from_date']})" for t in threads]
            sections.append(
                "Topics worth revisiting when it feels natural:\n" + "\n".join(thread_lines)
            )

        # 4. Memories related to what they just said
        if current_input and embeddings:
            relevant = await embeddings.search(current_input, limit=5)
            relevant = [r for r in relevant if r["similarity"] > 0.3]
            if relevant:
                rel_lines = [f"  - {r['text']}" for r in relevant]
                sections.append("Related things you remember:\n" + "\n".join(rel_lines))

        # 5. Their emotional arc
        mood_history = self.get_mood_history(hours=48)
        if mood_history and len(mood_history) > 2:
            from personality import PersonalityEngine
            arc = PersonalityEngine().get_emotional_arc_summary(mood_history)
            if arc:
                sections.append(f"Their emotional pattern lately: {arc}")

        # 6. News digest (latest)
        try:
            digest = self.conn.execute(
                "SELECT summary, reaction FROM news_digests ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if digest:
                sections.append(f"Latest world news: {digest[0]}")
                if digest[1]:
                    sections.append(f"Your reaction to the news: {digest[1]}")
        except Exception:
            pass

        if not sections:
            return ""

        return "Memory context:\n" + "\n\n".join(sections)

    def close(self):
        self.conn.close()


class ConversationSummarizer:
    """Extracts summaries, topics, and facts from conversations.
    Uses pattern matching for fast extraction, LLM for deeper analysis."""

    # Patterns that indicate the user is sharing personal info
    FACT_PATTERNS = [
        (r"(?:my name is|I'm called|call me)\s+(\w+)", "personal", "name"),
        (r"I (?:work|am working) (?:at|for|with)\s+(.+?)(?:\.|$|,)", "work", "employer"),
        (r"I'm (?:a|an)\s+(\w[\w\s]+?)(?:\.|$|,|and)", "work", "role"),
        (r"I live (?:in|at)\s+(.+?)(?:\.|$|,)", "personal", "location"),
        (r"I'm from\s+(.+?)(?:\.|$|,)", "personal", "origin"),
        (r"I (?:have|got)\s+(?:a\s+)?(\w+)\s+(?:named?|called)\s+(\w+)", "personal", "pet_or_family"),
        (r"my (?:wife|husband|partner|spouse)(?:'s name is|\s+is)\s+(\w+)", "personal", "partner"),
        (r"I (?:really )?(?:like|love|enjoy|prefer)\s+(.+?)(?:\.|$|,)", "preferences", "likes"),
        (r"I (?:don't like|hate|can't stand|dislike)\s+(.+?)(?:\.|$|,)", "preferences", "dislikes"),
        (r"my favorite\s+(\w+)\s+is\s+(.+?)(?:\.|$|,)", "preferences", None),  # dynamic key
        (r"I'm\s+(\d+)\s+years?\s+old", "personal", "age"),
        (r"my birthday is\s+(.+?)(?:\.|$|,)", "personal", "birthday"),
    ]

    def extract_facts(self, messages: list[dict]) -> list[tuple[str, str, str]]:
        """Extract personal facts from conversation messages.
        Returns list of (category, key, value) tuples."""
        facts = []
        for msg in messages:
            if msg.get("role") != "user":
                continue
            text = msg.get("content", "")
            for pattern, category, key in self.FACT_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    if key is None and match.lastindex and match.lastindex >= 2:
                        # Dynamic key (e.g., "my favorite X is Y")
                        key = f"favorite_{match.group(1)}"
                        value = match.group(2).strip()
                    elif match.lastindex and match.lastindex >= 2:
                        value = f"{match.group(1)} named {match.group(2)}"
                    else:
                        value = match.group(1).strip() if match.lastindex else ""
                    if value and key:
                        facts.append((category, key, value))
        return facts

    def extract_topics(self, messages: list[dict]) -> list[str]:
        """Extract main topics from a conversation."""
        # Simple keyword extraction — count nouns/significant words
        word_freq: dict[str, int] = {}
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "need", "dare", "ought",
            "i", "me", "my", "you", "your", "he", "she", "it", "we", "they",
            "this", "that", "these", "those", "what", "which", "who", "whom",
            "and", "or", "but", "not", "no", "so", "if", "then", "than",
            "to", "of", "in", "on", "at", "by", "for", "with", "from",
            "up", "about", "into", "through", "during", "before", "after",
            "just", "also", "very", "really", "much", "more", "most",
            "like", "know", "think", "want", "get", "go", "come", "make",
            "say", "tell", "see", "look", "find", "give", "take", "use",
            "yeah", "yes", "no", "ok", "okay", "sure", "right", "well",
            "hmm", "haha", "lol", "thanks", "thank", "please", "sorry",
            "don't", "doesn't", "didn't", "won't", "can't", "couldn't",
            "it's", "that's", "there's", "here's", "let's", "i'm", "i've",
        }

        for msg in messages:
            text = msg.get("content", "").lower()
            words = re.findall(r'\b[a-z]{3,}\b', text)
            for w in words:
                if w not in stop_words:
                    word_freq[w] = word_freq.get(w, 0) + 1

        # Top words as topics
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, c in sorted_words[:5] if c >= 2]

    def generate_summary(self, messages: list[dict]) -> str:
        """Generate a brief conversation summary.
        For now uses a simple heuristic — Phase 5 will use the LLM."""
        if not messages:
            return "Empty conversation."

        user_msgs = [m["content"] for m in messages if m.get("role") == "user"]
        if not user_msgs:
            return "No user messages."

        # Use first and last user message to frame the summary
        first = user_msgs[0][:100]
        last = user_msgs[-1][:100] if len(user_msgs) > 1 else ""
        topics = self.extract_topics(messages)
        topic_str = ", ".join(topics[:3]) if topics else "general chat"

        parts = [f"Conversation about {topic_str}."]
        if len(user_msgs) == 1:
            parts.append(f"User asked about: {first}")
        else:
            parts.append(f"Started with: {first}")
            if last and last != first:
                parts.append(f"Ended with: {last}")
        parts.append(f"({len(messages)} messages total)")

        return " ".join(parts)
