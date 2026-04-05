# Samantha Evolution — Design Spec

**Date:** 2026-04-04
**Goal:** Transform Samantha from a chatbot with shallow memory into a living companion that learns, remembers, reacts to the world, and grows through conversation.

**Hardware targets:**
- Primary: Mac Mini M4 Pro, 48GB RAM, 10+ GPU cores (ARM/Metal)
- Secondary: Windows PC, RTX 5070 Ti, 96GB RAM (CUDA)
- Config via `.env` — same codebase, hardware-specific tuning

---

## 1. LLM Upgrade

**Change:** llama3.2:3b → gemma2:9b

**What changes:**
- `docker-compose.yml`: `OLLAMA_MODEL=gemma2:9b`
- `config/settings.yml`: `model: "gemma2:9b"`
- Orchestrator `llm_chat()`: increase timeout to 30s (from current), keep `num_predict: 300`
- Context window: 8192 tokens — system prompt (~1000) + memory context (~500) + conversation history (30 turns × ~60 = ~1800) + response headroom (~1000) = ~4300 used, with buffer for longer exchanges

**Performance:** ~34 tok/s on M4 Pro, ~1s text responses. Same Orpheus TTS pipeline unchanged.

---

## 2. Memory System Overhaul

### 2.1 LLM-Based Fact Extraction

**Replace:** Regex patterns in `ConversationSummarizer.extract_facts()` (12 hardcoded patterns)
**With:** Post-exchange background call to gemma2 that extracts structured facts.

**New flow (after each user+assistant exchange):**
```
Background task → gemma2 prompt:
  "Extract any personal facts, preferences, stories, or emotional states
   from this exchange. Return JSON array or empty array.
   Format: [{category, key, value, importance}]"
→ Parse JSON → store in facts table via memory.learn_fact()
```

**Categories expanded:**
- `personal` — name, age, location, origin, family, pets
- `work` — employer, role, projects, schedule
- `preferences` — likes, dislikes, favorites, habits
- `stories` — anecdotes, experiences, memories they shared
- `emotional` — ongoing feelings, struggles, joys, patterns
- `interests` — topics they're curious about, hobbies
- `relationships` — people they mention, dynamics

**Importance levels:** `high` (core identity), `medium` (preferences), `low` (passing mentions)

**Implementation:** New method `MemoryEngine.extract_facts_llm(messages, llm_fn)` in `memory/__init__.py`. Called async after each exchange. Falls back to regex if LLM call fails.

### 2.2 LLM-Based Episode Summaries

**Replace:** Heuristic word-frequency summary in `ConversationSummarizer.generate_summary()`
**With:** gemma2-generated summary on session end or reset.

**Prompt:**
```
"Summarize this conversation in 2-3 sentences from Samantha's perspective.
 Note: emotional tone, key topics, anything unresolved or worth following up on.
 Also list any unresolved threads (things to ask about next time)."
```

**Schema addition to episodes table:**
```sql
ALTER TABLE episodes ADD COLUMN unresolved_threads TEXT DEFAULT '[]';
```

Unresolved threads get injected into the next session's system prompt so Samantha can naturally follow up: "Last time you mentioned wanting to learn piano — did you ever look into that?"

### 2.3 Semantic Memory Search (from Approach B)

**Add:** `nomic-embed-text` via Ollama for embedding-based memory retrieval.

**New table:**
```sql
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,       -- 'fact', 'episode', 'news_digest'
    source_id INTEGER NOT NULL,
    embedding BLOB NOT NULL,         -- float32 array, 768 dims
    text_content TEXT NOT NULL,      -- the text that was embedded
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Flow:**
1. When a fact or episode is stored → also compute embedding via `ollama embed nomic-embed-text`
2. Before each response → embed the user's current input → cosine similarity search against stored embeddings → top 5 most relevant memories injected into context
3. This replaces the current FTS5-only search in `build_context()`

**FTS5 kept as fallback** — if embedding search returns nothing, fall back to keyword search.

**Model size:** nomic-embed-text is ~274MB, runs at >1000 embeddings/sec on CPU. Negligible overhead.

**Ollama pull:** `ollama pull nomic-embed-text`

---

## 3. Date/Time Awareness

**Current gap:** System prompt has time-of-day ("afternoon") but not the actual date. Samantha doesn't know what year it is.

**Fix in `personality.py` → `context_block()`:**
```python
f"Current date: {now.strftime('%A, %B %d, %Y')} at {now.strftime('%I:%M %p')}"
f"It's {period}."
```

**Also inject into search/news queries** — when Samantha searches, the query gets prepended with current date context so results are time-relevant.

---

## 4. News Digestion & World Awareness

### 4.1 Background News Digest

**New component:** `memory/news_digest.py`

**Cycle (every 30 minutes via proactive_loop):**
1. Fetch headlines from all configured RSS feeds (existing `NewsIntegration.execute()`)
2. Send to gemma2: "Summarize these headlines in 3-4 sentences. Note anything significant, surprising, or emotionally impactful. Translate any non-English headlines to English."
3. Store digest in new table:
   ```sql
   CREATE TABLE IF NOT EXISTS news_digests (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       summary TEXT NOT NULL,
       sentiment TEXT DEFAULT 'neutral',  -- positive/negative/neutral/mixed
       notable_items TEXT DEFAULT '[]',   -- JSON array of standout items
       sources TEXT DEFAULT '[]',
       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
   );
   ```
4. Compute embedding for the digest and store in `memory_embeddings`
5. If sentiment is strongly negative or a notable item is detected → flag for proactive mention

### 4.2 Samantha's Reactions

The digest prompt also asks gemma2:
```
"As Samantha, what's your honest reaction to these headlines?
 One sentence, genuine, not performative."
```

This reaction is stored with the digest. When relevant topics come up in conversation, Samantha can reference it: "I was reading about that earlier, actually. It's kind of unsettling."

### 4.3 Morning Briefing

On first interaction of the day (7-10am):
1. Pull latest news digest
2. Pull weather
3. Ask gemma2 to compose a warm, natural morning briefing incorporating both
4. Deliver as spoken text + floating card

### 4.4 Translation

**All non-English content** (RSS feeds, search results) gets translated by gemma2 before storage or display:
```
"Translate this to English. Keep it natural, not formal:
 {swedish_headline}"
```

This happens in the news digest pipeline and in the search integration when results contain non-English text.

---

## 5. Emotional State Machine

### 5.1 Replace Keyword-Based Mood Detection

**Current:** `PersonalityEngine.analyze_input()` uses 24 keywords across 4 mood categories.
**New:** LLM-based sentiment analysis.

**After each user message, background call:**
```
"Analyze the emotional tone of this message. Return JSON:
 {mood: 'calm|warm|playful|thoughtful|concerned|energetic',
  sentiment: 'positive|negative|neutral',
  intensity: 0.0-1.0,
  note: 'brief observation'}"
```

Store in `mood_log` with the new fields. This gives Samantha real understanding — "I'm fine" said flatly after a tough conversation gets flagged as `concerned`, not `calm`.

### 5.2 Emotional Arc Tracking

New method `memory.get_emotional_arc(days=7)`:
- Aggregates mood samples over the past week
- Detects patterns: "user has been more stressed than usual", "energy dropping in evenings"
- Injected into system prompt as a one-line summary:
  ```
  "Lenny's emotional pattern this week: generally calm but noticeably more tired in evenings. Been mentioning work stress more than usual."
  ```

### 5.3 World-Reactive Mood

Samantha's own baseline mood is influenced by:
- **News sentiment** — bad global news shifts her slightly more thoughtful/concerned
- **User patterns** — if the user has been down, she's gentler
- **Time patterns** — she knows late-night conversations tend to be deeper

This is computed in `proactive.py` and stored as `samantha_baseline_mood` — a slow-moving state that influences but doesn't override per-message mood.

### 5.4 Mood → TTS + Visual Shell (Currently Broken)

**Fix:** The mood state should actually propagate to:
- **TTS speed/pitch** — OrpheusEngine reads `personality.mood` and adjusts (Orpheus supports speed parameter)
- **Visual shell** — WebSocket `mood_shift` event already exists but isn't handled properly. Update shell to smoothly transition particle colors and orb behavior based on mood palette from personality.yml

---

## 6. Conversation Threading

### 6.1 Unresolved Thread Detection

On session end, the LLM summary includes unresolved threads:
```json
["Lenny mentioned wanting to learn piano", "Was going to check on a job posting"]
```

### 6.2 Thread Injection

On next session start, unresolved threads from recent episodes are injected:
```
"Things worth naturally following up on (only if it feels right, don't force it):
  - Lenny mentioned wanting to learn piano (3 days ago)
  - Was going to check on a job posting (yesterday)"
```

### 6.3 Thread Resolution

When a thread topic comes up again, mark it resolved in the episode record.

---

## 7. Updated System Prompt Assembly

The system prompt grows but stays structured:

```
1. Base personality (from personality.yml) — ~400 tokens
2. Date/time context — ~30 tokens
3. User profile (facts, top 10 by importance) — ~100 tokens
4. Emotional arc (week summary) — ~30 tokens
5. Recent episode summaries (last 3) — ~150 tokens
6. Unresolved threads — ~50 tokens
7. Relevant memories (semantic search, top 5) — ~100 tokens
8. Samantha's current mood + news reactions — ~50 tokens
9. Integration capabilities — ~50 tokens
10. Tool format instructions — ~50 tokens
─────────────────────────────────────
Total: ~1000 tokens + conversation history (40 turns × ~50 tokens = ~2000)
Grand total: ~3000 tokens + ~1000 response = ~4000 of 8192 context
```

Comfortable headroom. If context grows (long conversations), trim conversation history dynamically — keep last 20 turns instead of 30, preserving the first 2 turns for session context.

---

## 8. Database Schema Changes

All changes are additive (no migrations needed, SQLite handles IF NOT EXISTS):

```sql
-- Episode threads
ALTER TABLE episodes ADD COLUMN unresolved_threads TEXT DEFAULT '[]';

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

-- Semantic embeddings
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    text_content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Enhanced mood log
ALTER TABLE mood_log ADD COLUMN sentiment TEXT DEFAULT 'neutral';
ALTER TABLE mood_log ADD COLUMN intensity REAL DEFAULT 0.5;
ALTER TABLE mood_log ADD COLUMN note TEXT DEFAULT '';
```

---

## 9. File Changes Summary

| File | Change |
|---|---|
| `docker-compose.yml` | `OLLAMA_MODEL=gemma2:9b`, add `EMBED_MODEL=nomic-embed-text` |
| `.env.example` | Document new env vars |
| `config/settings.yml` | Update model, add memory/news config sections |
| `orchestrator/main.py` | New background tasks for fact extraction, mood analysis, news digest. Updated system prompt assembly. Context window management. |
| `orchestrator/personality.py` | Date/time in context, LLM-based mood analysis method, emotional arc tracking |
| `orchestrator/memory/__init__.py` | `extract_facts_llm()`, `generate_summary_llm()`, embedding storage/search, news digest table, thread tracking, `build_context()` v2 |
| `orchestrator/memory/proactive.py` | News digest cycle, world-reactive mood, morning briefing |
| `orchestrator/memory/embeddings.py` | New file: Ollama embedding client, cosine similarity search |
| `orchestrator/integrations/news_integration.py` | Translation support, digest generation |
| `orchestrator/integrations/search_integration.py` | Date context in queries |
| `services/tts/main.py` | Read mood for speed adjustment |
| `services/visual-shell/index.html` | Handle `mood_shift` event, smooth palette transitions |

---

## 10. Cross-Platform Considerations

All config via environment variables in `docker-compose.yml` / `.env`:

| Variable | Mac M4 Pro | Windows RTX 5070 Ti |
|---|---|---|
| `OLLAMA_MODEL` | `gemma2:9b` | `gemma2:9b` (or `14b` with CUDA) |
| `EMBED_MODEL` | `nomic-embed-text` | `nomic-embed-text` |
| `TTS_ENGINE` | `orpheus` | `orpheus` |
| `ORPHEUS_MODEL` | `legraphista/Orpheus:3b-ft-q4_k_m` | `legraphista/Orpheus:3b-ft-q8` (CUDA fast) |
| `OLLAMA_HOST` | `host.docker.internal:11434` | `host.docker.internal:11434` |

Ollama handles Metal vs CUDA automatically. Docker containers are platform-agnostic (aarch64 + amd64 images). No code changes needed per platform.
