# Samantha Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve Samantha into a living companion with deep memory, emotional intelligence, world awareness, and natural conversation — powered by gemma2:9b with semantic memory search.

**Architecture:** LLM-as-memory-engine pattern. gemma2:9b handles conversation, fact extraction, mood analysis, news digestion, and episode summaries. nomic-embed-text provides semantic vector search over all stored memories. All processing happens async in background tasks so conversation stays fast. SQLite + FTS5 + embeddings for storage.

**Tech Stack:** Python/FastAPI (orchestrator), Ollama (gemma2:9b + nomic-embed-text + Orpheus TTS), SQLite with FTS5, Three.js (visual shell), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-04-04-samantha-evolution-design.md`

---

## File Structure

```
services/orchestrator/
├── main.py                          # MODIFY — new background tasks, updated prompt assembly, model config
├── personality.py                   # MODIFY — date/time context, LLM mood analysis, emotional arc
├── memory/
│   ├── __init__.py                  # MODIFY — new tables, LLM fact extraction, LLM summaries, build_context v2
│   ├── embeddings.py                # CREATE — Ollama embedding client, cosine similarity search
│   ├── news_digest.py               # CREATE — background news cycle, translation, reactions
│   └── proactive.py                 # MODIFY — morning briefing, world-reactive mood
├── integrations/
│   ├── search_integration.py        # MODIFY — date context in queries
│   └── news_integration.py          # MODIFY — translation support
├── intents/
│   └── __init__.py                  # (no changes)
└── requirements.txt                 # MODIFY — add numpy
config/
├── settings.yml                     # MODIFY — new model, memory, news config
docker-compose.yml                   # MODIFY — OLLAMA_MODEL, EMBED_MODEL env vars
.env.example                         # MODIFY — document new vars
services/visual-shell/
└── index.html                       # MODIFY — handle mood_shift palette transitions
```

---

### Task 1: LLM Upgrade — gemma2:9b

**Files:**
- Modify: `docker-compose.yml`
- Modify: `config/settings.yml`
- Modify: `services/orchestrator/main.py:287-294`

- [ ] **Step 1: Pull gemma2 and embedding model**

```bash
ollama pull gemma2:9b
ollama pull nomic-embed-text
```

Expected: Both models download successfully.

- [ ] **Step 2: Update docker-compose.yml**

In the orchestrator service environment section, change:

```yaml
      - OLLAMA_MODEL=gemma2:9b
      - EMBED_MODEL=nomic-embed-text
```

(Replace the existing `OLLAMA_MODEL=llama3.2:3b` line and add the `EMBED_MODEL` line.)

- [ ] **Step 3: Update settings.yml LLM section**

Replace the `llm:` block in `config/settings.yml`:

```yaml
llm:
  provider: "ollama"
  model: "gemma2:9b"
  fallback_model: "llama3.1:8b"
  temperature: 0.8
  max_tokens: 300
  context_window: 8192
```

Add a new `memory:` section after `visual:`:

```yaml
memory:
  db_path: "config/samantha_memory.db"
  embed_model: "nomic-embed-text"
  fact_extraction: true       # LLM-based fact extraction after each exchange
  episode_summaries: true     # LLM-based episode summaries on session end
  news_digest_interval: 1800  # seconds between news digest cycles (30 min)
```

- [ ] **Step 4: Update llm_chat in main.py**

Replace the `llm_chat` function (lines 287-294) with:

```python
OLLAMA_CTX = int(os.getenv("OLLAMA_CTX", "8192"))

async def llm_chat(messages: list[dict], max_tokens: int = 300) -> str:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"http://{OLLAMA_HOST}/api/chat", json={
            "model": OLLAMA_MODEL, "messages": messages, "stream": False,
            "options": {"temperature": 0.8, "num_predict": max_tokens, "num_ctx": OLLAMA_CTX},
        })
        r.raise_for_status()
        return r.json()["message"]["content"]
```

- [ ] **Step 5: Update .env.example**

Add to `.env.example`:

```bash
# LLM Model: "gemma2:9b" (recommended), "llama3.2:3b" (lightweight)
OLLAMA_MODEL=gemma2:9b

# Embedding model for semantic memory search
EMBED_MODEL=nomic-embed-text
```

- [ ] **Step 6: Rebuild and test**

```bash
docker compose up --build -d orchestrator
sleep 5
curl -s -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"text":"Hey Samantha"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('text',''))"
```

Expected: Response from gemma2:9b (warmer, more natural than llama3.2:3b). Check orchestrator logs confirm `gemma2:9b` is being used.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml config/settings.yml services/orchestrator/main.py .env.example
git commit -m "feat: upgrade LLM to gemma2:9b with 8192 context window"
```

---

### Task 2: Date/Time Awareness

**Files:**
- Modify: `services/orchestrator/personality.py:35-52`

- [ ] **Step 1: Update context_block with full date**

Replace the `context_block` method in `personality.py` (lines 35-52):

```python
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
```

- [ ] **Step 2: Rebuild and verify**

```bash
docker compose up --build -d orchestrator
sleep 3
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected: Orchestrator starts. The system prompt now includes the full date.

- [ ] **Step 3: Commit**

```bash
git add services/orchestrator/personality.py
git commit -m "feat: add full date/time awareness to system prompt"
```

---

### Task 3: Embedding Client

**Files:**
- Create: `services/orchestrator/memory/embeddings.py`

- [ ] **Step 1: Create embeddings.py**

Create `services/orchestrator/memory/embeddings.py`:

```python
"""
Samantha OS — Semantic Embedding Search
Uses Ollama's nomic-embed-text for vector similarity over memories.
"""

import os
import struct
import logging
import sqlite3
from typing import Optional

import httpx

logger = logging.getLogger("samantha.embeddings")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "host.docker.internal:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


class EmbeddingEngine:
    """Compute and search embeddings via Ollama."""

    def __init__(self, db: sqlite3.Connection):
        self.db = db
        self._create_table()

    def _create_table(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS memory_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                text_content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_emb_source
            ON memory_embeddings(source_type, source_id)
        """)
        self.db.commit()

    async def embed_text(self, text: str) -> list[float] | None:
        """Get embedding vector from Ollama."""
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(f"http://{OLLAMA_HOST}/api/embed", json={
                    "model": EMBED_MODEL,
                    "input": text,
                })
                r.raise_for_status()
                embeddings = r.json().get("embeddings", [])
                if embeddings:
                    return embeddings[0]
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
        return None

    def _pack_embedding(self, vec: list[float]) -> bytes:
        """Pack float list to bytes for SQLite storage."""
        return struct.pack(f'{len(vec)}f', *vec)

    def _unpack_embedding(self, blob: bytes) -> list[float]:
        """Unpack bytes to float list."""
        n = len(blob) // 4
        return list(struct.unpack(f'{n}f', blob))

    async def store(self, source_type: str, source_id: int, text: str):
        """Embed text and store alongside its source reference."""
        vec = await self.embed_text(text)
        if vec is None:
            return
        self.db.execute(
            "INSERT INTO memory_embeddings (source_type, source_id, embedding, text_content) VALUES (?, ?, ?, ?)",
            (source_type, source_id, self._pack_embedding(vec), text)
        )
        self.db.commit()

    async def search(self, query: str, limit: int = 5, source_type: Optional[str] = None) -> list[dict]:
        """Find most similar memories by cosine similarity."""
        query_vec = await self.embed_text(query)
        if query_vec is None:
            return []

        # Load all embeddings (fast enough for <10k memories)
        if source_type:
            rows = self.db.execute(
                "SELECT id, source_type, source_id, embedding, text_content FROM memory_embeddings WHERE source_type = ?",
                (source_type,)
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT id, source_type, source_id, embedding, text_content FROM memory_embeddings"
            ).fetchall()

        if not rows:
            return []

        # Compute cosine similarities
        results = []
        q_norm = _norm(query_vec)
        for row in rows:
            stored_vec = self._unpack_embedding(row[3])
            sim = _cosine_sim(query_vec, stored_vec, q_norm)
            results.append({
                "id": row[0],
                "source_type": row[1],
                "source_id": row[2],
                "text": row[4],
                "similarity": sim,
            })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]


def _norm(vec: list[float]) -> float:
    return sum(x * x for x in vec) ** 0.5


def _cosine_sim(a: list[float], b: list[float], a_norm: float = 0) -> float:
    if not a_norm:
        a_norm = _norm(a)
    b_norm = _norm(b)
    if a_norm == 0 or b_norm == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (a_norm * b_norm)
```

- [ ] **Step 2: Add numpy to requirements.txt**

Append to `services/orchestrator/requirements.txt`:

```
numpy==2.2.1
```

(numpy is already an indirect dependency but pinning it ensures consistency.)

- [ ] **Step 3: Verify module loads in container**

```bash
docker compose up --build -d orchestrator
sleep 5
docker compose exec orchestrator python3 -c "from memory.embeddings import EmbeddingEngine; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add services/orchestrator/memory/embeddings.py services/orchestrator/requirements.txt
git commit -m "feat: add semantic embedding engine with Ollama nomic-embed-text"
```

---

### Task 4: LLM-Based Fact Extraction

**Files:**
- Modify: `services/orchestrator/memory/__init__.py`
- Modify: `services/orchestrator/main.py`

- [ ] **Step 1: Add extract_facts_llm method to ConversationMemory**

Add this method to the `ConversationMemory` class in `memory/__init__.py`, after the existing `learn_fact` method:

```python
async def extract_facts_llm(self, user_text: str, assistant_text: str, llm_fn) -> list[tuple]:
    """Use the LLM to extract structured facts from a conversation exchange."""
    prompt = f"""Extract personal facts from this conversation exchange. Return a JSON array only.
Each item: {{"category": "personal|work|preferences|stories|emotional|interests|relationships", "key": "short_label", "value": "what was said", "importance": "high|medium|low"}}
Return [] if nothing worth remembering.

User: {user_text}
Assistant: {assistant_text}

JSON:"""
    try:
        result = await llm_fn(
            [{"role": "system", "content": "You extract structured facts from conversations. Return only valid JSON arrays. No explanation."},
             {"role": "user", "content": prompt}],
            max_tokens=200,
        )
        # Parse JSON from response
        result = result.strip()
        if result.startswith("```"):
            result = result.split("```")[1].strip()
            if result.startswith("json"):
                result = result[4:].strip()
        facts = json.loads(result)
        if not isinstance(facts, list):
            return []
        stored = []
        for f in facts:
            cat = f.get("category", "personal")
            key = f.get("key", "")
            val = f.get("value", "")
            imp = f.get("importance", "medium")
            if key and val:
                confidence = {"high": 0.95, "medium": 0.8, "low": 0.6}.get(imp, 0.8)
                self.learn_fact(cat, key, val, confidence)
                stored.append((cat, key, val))
        return stored
    except (json.JSONDecodeError, Exception) as e:
        logger.debug(f"LLM fact extraction failed: {e}")
        return []
```

- [ ] **Step 2: Update main.py add_message to use LLM extraction**

In `main.py`, replace the fact extraction block inside `add_message` (the section that starts with `# Phase 3: extract and store facts from user messages`):

```python
        # Phase 3: extract and store facts from user messages
        if role == "user" and self.memory:
            # Legacy regex extraction as fallback
            facts = self.summarizer.extract_facts([{"role": role, "content": content}])
            for cat, key, val in facts:
                self.memory.learn_fact(cat, key, val)

        # Notify proactive engine
        self.proactive.on_interaction()
```

Then add a new background task launcher after the WebSocket handlers process a message. In the `_send_audio` function area, add a new helper:

```python
async def _extract_memories(user_text: str, assistant_text: str):
    """Background: extract facts from the latest exchange using LLM."""
    if state.memory:
        try:
            facts = await state.memory.extract_facts_llm(user_text, assistant_text, llm_chat)
            if facts:
                logger.info(f"🧠 Learned {len(facts)} facts: {facts}")
                # Embed new facts for semantic search
                if hasattr(state, 'embeddings') and state.embeddings:
                    for cat, key, val in facts:
                        fact_text = f"{cat}/{key}: {val}"
                        # Find the fact ID
                        row = state.memory.conn.execute(
                            "SELECT id FROM facts WHERE category=? AND key=?", (cat, key)
                        ).fetchone()
                        if row:
                            await state.embeddings.store("fact", row[0], fact_text)
        except Exception as e:
            logger.debug(f"Background fact extraction failed: {e}")
```

- [ ] **Step 3: Wire up background extraction in WebSocket handlers**

In both the `audio_chunk` and `text_input` handlers in `ws_endpoint`, after `asyncio.create_task(_send_audio(ws, result))`, add:

```python
                asyncio.create_task(_extract_memories(
                    user_text if data.get("event") == "audio_chunk" else text,
                    result.get("tts_text", result["text"])
                ))
```

- [ ] **Step 4: Initialize embeddings engine in SamanthaState**

In `main.py`, add to `SamanthaState.__init__`:

```python
        self.embeddings = None  # initialized in load_config
```

In `load_config`, after the memory initialization:

```python
        # Semantic embeddings
        from memory.embeddings import EmbeddingEngine
        self.embeddings = EmbeddingEngine(self.memory.conn)
        logger.info("Embeddings engine initialized")
```

- [ ] **Step 5: Rebuild and test**

```bash
docker compose up --build -d orchestrator
sleep 5
curl -s -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"text":"My cat is named Luna and she loves sleeping on my keyboard"}'
sleep 3
docker compose logs orchestrator --tail 10 | grep "🧠"
```

Expected: Log line `🧠 Learned N facts: [('personal', 'pet', 'cat named Luna'), ...]`

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/memory/__init__.py services/orchestrator/main.py
git commit -m "feat: LLM-based fact extraction replaces regex patterns"
```

---

### Task 5: LLM-Based Episode Summaries + Thread Tracking

**Files:**
- Modify: `services/orchestrator/memory/__init__.py`
- Modify: `services/orchestrator/main.py`

- [ ] **Step 1: Add unresolved_threads column**

Add to `_create_tables` in `memory/__init__.py`, after the existing episodes table creation (the `CREATE TABLE IF NOT EXISTS episodes` block won't add the column to existing tables, so add a migration):

```python
        # Migration: add unresolved_threads if missing
        try:
            self.conn.execute("ALTER TABLE episodes ADD COLUMN unresolved_threads TEXT DEFAULT '[]'")
            self.conn.commit()
        except Exception:
            pass  # column already exists
```

- [ ] **Step 2: Add generate_summary_llm method**

Add to `ConversationMemory` class:

```python
async def generate_summary_llm(self, messages: list[dict], llm_fn) -> tuple[str, list[str]]:
    """Generate episode summary and unresolved threads via LLM."""
    # Build a condensed transcript
    transcript = []
    for m in messages[-20:]:  # last 20 messages max
        role = "Lenny" if m.get("role") == "user" else "Samantha"
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
        # Fallback to existing heuristic
        summarizer = ConversationSummarizer()
        summary = summarizer.generate_summary(messages)
        return summary, []
```

- [ ] **Step 3: Update save_episode to include threads**

Update the `save_episode` method signature and SQL:

```python
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
```

- [ ] **Step 4: Update shutdown and reset to use LLM summaries**

In `main.py`, update the lifespan shutdown block (the section after `yield` in `lifespan`):

```python
    # Phase 3: save conversation summary on shutdown
    if state.memory and state.conversation:
        summarizer = ConversationSummarizer()
        topics = summarizer.extract_topics(state.conversation)
        try:
            summary, threads = await state.memory.generate_summary_llm(state.conversation, llm_chat)
        except Exception:
            summary = summarizer.generate_summary(state.conversation)
            threads = []
        state.memory.save_episode(
            summary=summary, topics=topics,
            mood_arc=state.personality.mood,
            message_count=len(state.conversation),
            started_at=state._session_start,
            unresolved_threads=threads,
        )
        # Embed the episode summary
        if state.embeddings:
            ep_id = state.memory.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            await state.embeddings.store("episode", ep_id, summary)
        logger.info(f"Saved episode: {topics}, threads: {threads}")
        state.memory.close()
```

Do the same for the `/reset` endpoint.

- [ ] **Step 5: Add get_unresolved_threads to ConversationMemory**

```python
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
```

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/memory/__init__.py services/orchestrator/main.py
git commit -m "feat: LLM-based episode summaries with unresolved thread tracking"
```

---

### Task 6: Enhanced Context Building (build_context v2)

**Files:**
- Modify: `services/orchestrator/memory/__init__.py`
- Modify: `services/orchestrator/main.py`

- [ ] **Step 1: Rewrite build_context in ConversationMemory**

Replace the existing `build_context` method:

```python
async def build_context(self, current_input: str = "", embeddings=None) -> str:
    """Build rich memory context for injection into the LLM system prompt."""
    sections = []

    # 1. User profile (facts by importance)
    facts = self.recall_facts(limit=15)
    if facts:
        fact_lines = []
        for f in facts:
            fact_lines.append(f"  {f['category']}/{f['key']}: {f['value']}")
        sections.append("What you know about the user:\n" + "\n".join(fact_lines))

    # 2. Recent conversation summaries
    episodes = self.get_recent_episodes(3)
    if episodes:
        ep_lines = []
        for ep in episodes:
            topics = json.loads(ep.get("topics", "[]"))
            topic_str = ", ".join(topics) if topics else "general"
            ep_lines.append(f"  - {ep['ended_at']}: {ep['summary']} (topics: {topic_str})")
        sections.append("Recent conversations:\n" + "\n".join(ep_lines))

    # 3. Unresolved threads
    threads = self.get_unresolved_threads(5)
    if threads:
        thread_lines = [f"  - {t['topic']} ({t['from_date']})" for t in threads]
        sections.append(
            "Things worth naturally following up on (only if it feels right):\n" + "\n".join(thread_lines)
        )

    # 4. Semantic memory search (if embeddings available and user said something)
    if current_input and embeddings:
        relevant = await embeddings.search(current_input, limit=5)
        relevant = [r for r in relevant if r["similarity"] > 0.3]
        if relevant:
            rel_lines = [f"  - {r['text']} (relevance: {r['similarity']:.0%})" for r in relevant]
            sections.append("Related memories:\n" + "\n".join(rel_lines))

    # 5. Emotional pattern
    dominant = self.get_dominant_mood(4)
    if dominant != "unknown":
        sections.append(f"User's recent emotional tendency: {dominant}")

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
        pass  # table may not exist yet

    if not sections:
        return ""

    return "Memory context:\n" + "\n\n".join(sections)
```

- [ ] **Step 2: Update system_prompt property in main.py**

The `system_prompt` property in `SamanthaState` currently calls `self.memory.build_context(current_input)` synchronously. Since the new version is async, change the approach — compute context before building the prompt. Replace the `system_prompt` property:

```python
@property
def system_prompt(self) -> str:
    base = self._personality_config.get("system_prompt", "You are Samantha.")
    context = self.personality.context_block()
    intg_context = "\n".join(self.registry.get_context_blocks())
    tools_desc = self.router.get_tools_description() if self.router else ""

    return f"""{base}

{context}

{self._memory_context}

{intg_context}

{tools_desc}

When you want to use a tool, respond with a JSON block like:
{{"tool": "action_name", "params": {{"key": "value"}}}}
Only use this format when you need to take an action. For normal conversation, just respond naturally."""
```

Add `self._memory_context = ""` to `__init__`, and add a method:

```python
async def refresh_memory_context(self, current_input: str = ""):
    """Refresh memory context before generating a response."""
    if self.memory:
        self._memory_context = await self.memory.build_context(current_input, self.embeddings)
    else:
        self._memory_context = ""
```

- [ ] **Step 3: Call refresh_memory_context before llm_chat**

In `process_message`, add before the `state.add_message("user", user_text)` line:

```python
    await state.refresh_memory_context(user_text)
```

- [ ] **Step 4: Rebuild and test**

```bash
docker compose up --build -d orchestrator
sleep 5
# Ask something that should trigger memory recall
curl -s -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"text":"Do you remember what my cat is called?"}'
```

Expected: Samantha recalls "Luna" from the facts stored in Task 4.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/memory/__init__.py services/orchestrator/main.py
git commit -m "feat: enhanced context building with semantic search and thread injection"
```

---

### Task 7: LLM-Based Mood Analysis

**Files:**
- Modify: `services/orchestrator/personality.py`
- Modify: `services/orchestrator/memory/__init__.py`
- Modify: `services/orchestrator/main.py`

- [ ] **Step 1: Add mood schema migration**

In `ConversationMemory._create_tables`, add:

```python
        # Migration: enhanced mood log
        for col, default in [("sentiment", "'neutral'"), ("intensity", "0.5"), ("note", "''")]:
            try:
                self.conn.execute(f"ALTER TABLE mood_log ADD COLUMN {col} TEXT DEFAULT {default}")
                self.conn.commit()
            except Exception:
                pass
```

Update `log_mood` to accept new fields:

```python
def log_mood(self, user_mood: str, samantha_mood: str, trigger: str = "",
             sentiment: str = "neutral", intensity: float = 0.5, note: str = ""):
    self.conn.execute(
        "INSERT INTO mood_log (user_mood, samantha_mood, trigger, sentiment, intensity, note) VALUES (?, ?, ?, ?, ?, ?)",
        (user_mood, samantha_mood, trigger, sentiment, intensity, note)
    )
    self.conn.commit()
```

- [ ] **Step 2: Add LLM mood analysis to PersonalityEngine**

Add to `personality.py`:

```python
async def analyze_mood_llm(self, text: str, llm_fn) -> dict:
    """Use LLM for nuanced mood detection instead of keyword matching."""
    prompt = f"""Analyze the emotional tone of this message. Return JSON only:
{{"mood": "calm|warm|playful|thoughtful|concerned|energetic", "sentiment": "positive|negative|neutral", "intensity": 0.0-1.0, "note": "brief observation"}}

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
        # Fallback to keyword analysis
        return self.analyze_input(text)
```

Add emotional arc method:

```python
def get_emotional_arc_summary(self, mood_history: list[dict]) -> str:
    """Generate a one-line emotional arc summary from mood history."""
    if not mood_history:
        return ""
    moods = [m.get("user_mood", "calm") for m in mood_history]
    sentiments = [m.get("sentiment", "neutral") for m in mood_history]
    notes = [m.get("note", "") for m in mood_history if m.get("note")]

    # Count dominant patterns
    from collections import Counter
    mood_counts = Counter(moods)
    sentiment_counts = Counter(sentiments)
    dominant_mood = mood_counts.most_common(1)[0][0]
    dominant_sentiment = sentiment_counts.most_common(1)[0][0]

    summary = f"User has been mostly {dominant_mood} ({dominant_sentiment})"
    if notes:
        summary += f". Notable: {notes[-1]}"
    return summary
```

- [ ] **Step 3: Wire LLM mood analysis into main.py**

In `_extract_memories`, add mood analysis:

```python
async def _extract_memories(user_text: str, assistant_text: str):
    """Background: extract facts and analyze mood from the latest exchange."""
    if state.memory:
        try:
            # LLM fact extraction
            facts = await state.memory.extract_facts_llm(user_text, assistant_text, llm_chat)
            if facts:
                logger.info(f"🧠 Learned {len(facts)} facts: {facts}")
                if state.embeddings:
                    for cat, key, val in facts:
                        row = state.memory.conn.execute(
                            "SELECT id FROM facts WHERE category=? AND key=?", (cat, key)
                        ).fetchone()
                        if row:
                            await state.embeddings.store("fact", row[0], f"{cat}/{key}: {val}")

            # LLM mood analysis
            analysis = await state.personality.analyze_mood_llm(user_text, llm_chat)
            state.personality.update_mood(analysis)
            state.memory.log_mood(
                user_mood=analysis.get("detected_mood", "calm"),
                samantha_mood=state.personality.mood,
                trigger=user_text[:80],
                sentiment=analysis.get("sentiment", "neutral"),
                intensity=analysis.get("intensity", 0.5),
                note=analysis.get("note", ""),
            )
        except Exception as e:
            logger.debug(f"Background memory extraction failed: {e}")
```

- [ ] **Step 4: Inject emotional arc into context**

In `build_context`, replace the emotional pattern section:

```python
    # 5. Emotional arc (richer than just dominant mood)
    mood_history = self.get_mood_history(hours=48)
    if mood_history:
        from personality import PersonalityEngine
        arc = PersonalityEngine().get_emotional_arc_summary(mood_history)
        if arc:
            sections.append(f"Emotional arc: {arc}")
```

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/personality.py services/orchestrator/memory/__init__.py services/orchestrator/main.py
git commit -m "feat: LLM-based mood analysis with emotional arc tracking"
```

---

### Task 8: News Digest Engine

**Files:**
- Create: `services/orchestrator/memory/news_digest.py`
- Modify: `services/orchestrator/memory/__init__.py`
- Modify: `services/orchestrator/memory/proactive.py`
- Modify: `services/orchestrator/main.py`

- [ ] **Step 1: Add news_digests table**

In `ConversationMemory._create_tables`, add:

```python
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS news_digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary TEXT NOT NULL,
                sentiment TEXT DEFAULT 'neutral',
                notable_items TEXT DEFAULT '[]',
                reaction TEXT DEFAULT '',
                sources TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
```

- [ ] **Step 2: Create news_digest.py**

Create `services/orchestrator/memory/news_digest.py`:

```python
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

        # Fetch headlines from news integration
        news_intg = self.registry.get("news")
        if not news_intg:
            return None

        result = await news_intg.execute("headlines", {"count": 8})
        headlines = result.get("headlines", [])
        if not headlines:
            return None

        # Build headline text for LLM
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

            # Store digest
            self.memory.conn.execute(
                "INSERT INTO news_digests (summary, sentiment, notable_items, reaction, sources) VALUES (?, ?, ?, ?, ?)",
                (summary, sentiment, json.dumps(notable), reaction, json.dumps([h.get("category") for h in headlines]))
            )
            self.memory.conn.commit()

            # Embed for semantic search
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
```

- [ ] **Step 3: Wire news digest into proactive_loop**

In `main.py`, update the `proactive_loop` function. Add news digest scheduling after the existing proactive check:

```python
import time as _time

# Track last digest time
_last_news_digest = 0
NEWS_DIGEST_INTERVAL = int(os.getenv("NEWS_DIGEST_INTERVAL", "1800"))  # 30 min

async def proactive_loop():
    """Periodically check integrations, behaviors, and news."""
    global _last_news_digest
    while True:
        await asyncio.sleep(PROACTIVE_INTERVAL)
        try:
            # Integration notifications
            updates = await state.registry.check_proactive()
            for update in updates:
                await state.broadcast(update)

            # Proactive behaviors
            event = state.proactive.check()
            if event:
                if event.card_title or event.card_body:
                    await state.broadcast({
                        "event": "card",
                        "title": event.card_title or "",
                        "body": event.card_body or "",
                    })
                if event.mood:
                    await state.broadcast({"event": "mood_shift", "mood": event.mood})

            # News digest cycle
            now = _time.time()
            if now - _last_news_digest > NEWS_DIGEST_INTERVAL and state.news_digest:
                _last_news_digest = now
                digest = await state.news_digest.run_digest(llm_chat)
                if digest and digest.get("notable"):
                    await state.broadcast({
                        "event": "card",
                        "title": "World News",
                        "body": digest["reaction"] or digest["summary"][:100],
                    })

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Proactive check error: {e}")
```

- [ ] **Step 4: Initialize NewsDigestEngine in SamanthaState**

In `load_config`, after embeddings init:

```python
        # News digest engine
        from memory.news_digest import NewsDigestEngine
        self.news_digest = NewsDigestEngine(self.memory, self.embeddings, self.registry)
```

Add `self.news_digest = None` to `__init__`.

- [ ] **Step 5: Rebuild and test**

```bash
docker compose up --build -d orchestrator
sleep 10
# Trigger a manual digest
docker compose exec orchestrator python3 -c "
import asyncio
from main import state, llm_chat
async def test():
    state.load_config()
    await state.init_integrations()
    d = await state.news_digest.run_digest(llm_chat)
    print('Digest:', d)
asyncio.run(test())
"
```

Expected: A news digest is generated with summary, sentiment, reaction, and notable items.

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/memory/news_digest.py services/orchestrator/memory/__init__.py services/orchestrator/memory/proactive.py services/orchestrator/main.py
git commit -m "feat: news digest engine with LLM summarization, translation, and reactions"
```

---

### Task 9: Translation Layer for Non-English Content

**Files:**
- Modify: `services/orchestrator/integrations/news_integration.py`
- Modify: `services/orchestrator/integrations/search_integration.py`

- [ ] **Step 1: Add date context to search queries**

In `search_integration.py`, update the `_search` method to prepend date context. Find the `params` dict where the DuckDuckGo API call is made and update:

```python
async def _search(self, query: str) -> dict:
    """Search DuckDuckGo with date-aware context."""
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")

    async with httpx.AsyncClient(timeout=10) as client:
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }
        # ... rest of existing search code
```

- [ ] **Step 2: Translation is already handled by news_digest.py**

The news digest engine (Task 8) already asks gemma2 to "Translate any non-English headlines to English" in its digest prompt. No additional code needed for RSS translation.

For search results, DuckDuckGo already returns English results by default. If non-English results appear, they'll be handled naturally by gemma2 when formatting the response.

- [ ] **Step 3: Commit**

```bash
git add services/orchestrator/integrations/search_integration.py
git commit -m "feat: add date context to search queries"
```

---

### Task 10: Visual Shell Mood Transitions

**Files:**
- Modify: `services/visual-shell/index.html`

- [ ] **Step 1: Handle mood_shift WebSocket event**

In the `handleEvt` function in `index.html`, the `mood_shift` case is already listed but doesn't do anything visible. Update it:

```javascript
        case 'mood_shift':
          if(d.mood && MOODS[d.mood]) {
            setMood(d.mood);
          }
          break;
```

This already works because `setMood` updates CSS variables and orb class. The particles transition smoothly via the existing `col` lerping in the `tick` function.

- [ ] **Step 2: Rebuild and test**

```bash
docker compose up --build -d visual-shell
```

Expected: When Samantha's mood shifts (via proactive behavior or conversation), the visual shell transitions smoothly.

- [ ] **Step 3: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat: handle mood_shift events in visual shell"
```

---

### Task 11: Morning Briefing

**Files:**
- Modify: `services/orchestrator/memory/proactive.py`
- Modify: `services/orchestrator/main.py`

- [ ] **Step 1: Update morning briefing in proactive.py**

Replace the morning briefing block in `ProactiveBehavior.check()`:

```python
        # ─── Morning briefing (first interaction of the day, 7-10am) ───
        if not self.daily_checkin_done and 7 <= hour <= 10 and self.interaction_count >= 1:
            self.daily_checkin_done = True
            self.last_proactive = now
            return ProactiveEvent(
                type="morning_briefing",
                message=None,
                card_title="Good Morning",
                card_body="Let me see what's happening today...",
                priority=1,
            )
```

- [ ] **Step 2: Handle morning_briefing event in proactive_loop**

In `main.py`'s `proactive_loop`, after the existing proactive event handling:

```python
            # Handle morning briefing
            if event and event.type == "morning_briefing":
                try:
                    # Get weather
                    weather_intg = state.registry.get("weather")
                    weather = await weather_intg.execute("current_weather", {}) if weather_intg else {}

                    # Get latest news digest (or run one)
                    digest = state.news_digest.get_latest_digest() if state.news_digest else None
                    if not digest and state.news_digest:
                        digest = await state.news_digest.run_digest(llm_chat)

                    # Get unresolved threads
                    threads = state.memory.get_unresolved_threads(3) if state.memory else []

                    # Ask LLM to compose briefing
                    context_parts = []
                    if weather:
                        context_parts.append(f"Weather: {json.dumps(weather)}")
                    if digest:
                        context_parts.append(f"News: {digest.get('summary', '')}")
                    if threads:
                        context_parts.append(f"Unresolved from recent chats: {[t['topic'] for t in threads]}")

                    if context_parts:
                        briefing = await llm_chat([
                            {"role": "system", "content": "You are Samantha. Give a warm, natural morning briefing in 2-3 sentences. No lists. Mention weather, news, and any follow-ups from recent conversations."},
                            {"role": "user", "content": "\n".join(context_parts)},
                        ], max_tokens=150)
                        await state.broadcast({
                            "event": "card",
                            "title": "Good Morning",
                            "body": briefing[:200],
                        })
                except Exception as e:
                    logger.warning(f"Morning briefing failed: {e}")
```

- [ ] **Step 3: Commit**

```bash
git add services/orchestrator/memory/proactive.py services/orchestrator/main.py
git commit -m "feat: morning briefing with weather, news, and conversation follow-ups"
```

---

### Task 12: Final Integration + Config Updates

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `config/settings.yml`

- [ ] **Step 1: Update .env.example with all new vars**

Replace the full `.env.example`:

```bash
# ─────────────────────────────────────────────────
# Samantha OS — Environment Variables
# Copy this to .env and customize for your hardware
# ─────────────────────────────────────────────────

# LLM Model: "gemma2:9b" (recommended), "qwen2.5:14b" (smarter, slower)
OLLAMA_MODEL=gemma2:9b

# Embedding model for semantic memory search
EMBED_MODEL=nomic-embed-text

# TTS Engine: "piper" (lightweight, CPU) or "orpheus" (high-quality, needs Ollama)
TTS_ENGINE=orpheus
ORPHEUS_VOICE=tara
ORPHEUS_MODEL=legraphista/Orpheus:3b-ft-q4_k_m

# News digest interval (seconds, default 1800 = 30 min)
NEWS_DIGEST_INTERVAL=1800

# Microsoft 365 (Outlook + Calendar)
MS365_CLIENT_ID=
MS365_CLIENT_SECRET=
MS365_TENANT_ID=common

# Spotify
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=

# Google credentials: config/google_credentials.json
```

- [ ] **Step 2: Final docker-compose.yml env vars**

Ensure the orchestrator environment section includes:

```yaml
      - OLLAMA_MODEL=${OLLAMA_MODEL:-gemma2:9b}
      - EMBED_MODEL=${EMBED_MODEL:-nomic-embed-text}
      - OLLAMA_CTX=8192
      - NEWS_DIGEST_INTERVAL=${NEWS_DIGEST_INTERVAL:-1800}
```

- [ ] **Step 3: Full rebuild and smoke test**

```bash
docker compose down
docker compose up --build -d
sleep 15

# Test 1: Chat works
curl -s -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"text":"Hey Samantha, my name is Lenny and I live in Landskrona"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('text',''))"

sleep 5

# Test 2: Memory extraction worked
docker compose logs orchestrator --tail 20 | grep "🧠"

# Test 3: News works
curl -s -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"text":"Any interesting news from Sweden today?"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('text',''))"

# Test 4: Memory recall
curl -s -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"text":"Where do I live?"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('text',''))"

# Test 5: Health
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected: All tests pass. Samantha responds naturally, remembers facts, fetches Swedish news in English, and recalls personal information.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: Samantha evolution — gemma2:9b, LLM memory, semantic search, news digest, mood analysis"
```

---

## Execution Order

Tasks 1-3 are foundational (must go first, in order).
Tasks 4-7 build on each other (memory → context → mood).
Task 8 is independent (news digest).
Tasks 9-11 are polish (translation, visual, briefing).
Task 12 is final integration.

```
Task 1 (LLM upgrade)
  → Task 2 (date/time)
  → Task 3 (embeddings)
    → Task 4 (fact extraction)
    → Task 5 (episode summaries)
      → Task 6 (context building v2)
      → Task 7 (mood analysis)
    → Task 8 (news digest) — can run parallel with 6-7
  → Task 9 (translation)
  → Task 10 (visual mood)
  → Task 11 (morning briefing)
→ Task 12 (final integration)
```
