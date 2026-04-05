"""
Samantha OS — Orchestrator (Phase 3)
The brain. Voice pipeline + LLM + integrations + memory + proactive behaviors.
"""

import os
import asyncio
import json
import logging
import time
from datetime import datetime
from contextlib import asynccontextmanager

import httpx
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from personality import PersonalityEngine
from memory import ConversationMemory, ConversationSummarizer
from memory.proactive import ProactiveBehavior, ProactiveEvent
from integrations import IntegrationRegistry
from integrations.weather_integration import WeatherIntegration
from integrations.search_integration import WebSearchIntegration
from integrations.notes_integration import NotesIntegration
from integrations.news_integration import NewsIntegration
from intents import IntentRouter

# Optional integrations (imported conditionally)
try:
    from integrations.google_integration import GoogleIntegration
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False

try:
    from integrations.ms365_integration import MS365Integration
    HAS_MS365 = True
except ImportError:
    HAS_MS365 = False

try:
    from integrations.spotify_integration import SpotifyIntegration
    HAS_SPOTIFY = True
except ImportError:
    HAS_SPOTIFY = False

# ─── Config ──────────────────────────────
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "host.docker.internal:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma2:9b")
OLLAMA_CTX = int(os.getenv("OLLAMA_CTX", "8192"))
STT_HOST = os.getenv("STT_HOST", "stt:8001")
TTS_HOST = os.getenv("TTS_HOST", "tts:8002")
PERSONALITY_FILE = os.getenv("PERSONALITY_FILE", "/app/config/personality.yml")
SETTINGS_FILE = os.getenv("SETTINGS_FILE", "/app/config/settings.yml")
PROACTIVE_INTERVAL = int(os.getenv("PROACTIVE_INTERVAL", "120"))

import time as _time
_last_news_digest = 0.0
NEWS_DIGEST_INTERVAL = int(os.getenv("NEWS_DIGEST_INTERVAL", "1800"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())
logger = logging.getLogger("samantha")


# ─── State ───────────────────────────────
class SamanthaState:
    def __init__(self):
        self.conversation: list[dict] = []
        self.personality = PersonalityEngine()
        self.registry = IntegrationRegistry()
        self.router: IntentRouter | None = None
        self.clients: list[WebSocket] = []
        self.settings: dict = {}
        self._personality_config: dict = {}
        # Phase 3
        self.memory: ConversationMemory | None = None
        self.summarizer = ConversationSummarizer()
        self.proactive = ProactiveBehavior()
        self._session_start: str = datetime.now().isoformat()
        self.embeddings = None
        self.news_digest = None
        self._memory_context = ""

    def load_config(self):
        # Personality
        try:
            with open(PERSONALITY_FILE) as f:
                self._personality_config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self._personality_config = {"name": "Samantha", "system_prompt": "You are Samantha, a warm AI companion."}

        # Settings
        try:
            with open(SETTINGS_FILE) as f:
                self.settings = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self.settings = {}

        # Memory
        mem_cfg = self.settings.get("memory", {})
        db_path = mem_cfg.get("db_path", "config/samantha_memory.db")
        self.memory = ConversationMemory(db_path)
        logger.info(f"Memory loaded: {db_path}")

        # Semantic embeddings
        from memory.embeddings import EmbeddingEngine
        self.embeddings = EmbeddingEngine(self.memory.conn)
        logger.info("Embeddings engine initialized")

    async def init_integrations(self):
        intg_config = self.settings.get("integrations", {})

        # Always-on (free, no API key)
        weather_cfg = intg_config.get("weather", {})
        weather = WeatherIntegration()
        self.registry.register(weather)
        if weather_cfg.get("enabled", True):
            await self.registry.enable("weather", weather_cfg)

        search = WebSearchIntegration()
        self.registry.register(search)
        if intg_config.get("web_search", {}).get("enabled", True):
            await self.registry.enable("web_search", {})

        notes = NotesIntegration()
        self.registry.register(notes)
        if intg_config.get("notes", {}).get("enabled", True):
            await self.registry.enable("notes", intg_config.get("notes", {}))

        news = NewsIntegration()
        self.registry.register(news)
        if intg_config.get("news", {}).get("enabled", True):
            await self.registry.enable("news", intg_config.get("news", {}))

        # Optional: Google
        if HAS_GOOGLE:
            google_cfg = intg_config.get("google", {})
            if google_cfg.get("enabled", False):
                g = GoogleIntegration()
                self.registry.register(g)
                await self.registry.enable("google", google_cfg)

        # Optional: MS365
        if HAS_MS365:
            ms_cfg = intg_config.get("ms365", {})
            if ms_cfg.get("enabled", False):
                m = MS365Integration()
                self.registry.register(m)
                await self.registry.enable("ms365", ms_cfg)

        # Optional: Spotify
        if HAS_SPOTIFY:
            sp_cfg = intg_config.get("spotify", {})
            if sp_cfg.get("enabled", False):
                s = SpotifyIntegration()
                self.registry.register(s)
                await self.registry.enable("spotify", sp_cfg)

        self.router = IntentRouter(self.registry)
        logger.info(f"Integrations: {self.registry.status_summary()}")

        # News digest (needs registry to be ready)
        if self.memory:
            from memory.news_digest import NewsDigestEngine
            self.news_digest = NewsDigestEngine(self.memory, self.embeddings, self.registry)
            logger.info("News digest engine initialized")

    async def refresh_memory_context(self, current_input: str = ""):
        """Refresh memory context before generating a response."""
        if self.memory:
            # Skip embedding search for speed — use FTS5 only
            self._memory_context = await self.memory.build_context(current_input, embeddings=None)
        else:
            self._memory_context = ""

    @property
    def system_prompt(self) -> str:
        base = self._personality_config.get("system_prompt", "You are Samantha.")
        context = self.personality.context_block()
        intg_context = "\n".join(self.registry.get_context_blocks())
        tools_desc = self.router.get_tools_description() if self.router else ""

        memory_context = self._memory_context

        # First-run: if we know almost nothing, be curious
        first_run_hint = ""
        if self.memory:
            fact_count = len(self.memory.recall_facts(limit=5))
            if fact_count == 0:
                first_run_hint = """
IMPORTANT: You have NEVER met this person before. You don't know their name.
Your FIRST question must be asking their name. Keep it warm and simple.
Example: "Hey... I don't think we've met. What's your name?"
After you learn their name, ask what they do and what they're into.
One question per response. Be genuinely curious."""
            elif fact_count < 3:
                first_run_hint = """
You're still getting to know this person. Ask about what they do,
what they're into, where they're from. One question at a time. Be warm."""

        return f"""{base}

{context}
{first_run_hint}

{memory_context}

{intg_context}

{tools_desc}

When you want to use a tool, respond with a JSON block like:
{{"tool": "action_name", "params": {{"key": "value"}}}}
Only use this format when you need to take an action. For normal conversation, just respond naturally."""

    def add_message(self, role: str, content: str):
        self.conversation.append({"role": role, "content": content, "ts": datetime.now().isoformat()})
        if len(self.conversation) > 40:
            self.conversation = self.conversation[-40:]

        # Phase 3: extract and store facts from user messages
        if role == "user" and self.memory:
            facts = self.summarizer.extract_facts([{"role": role, "content": content}])
            for cat, key, val in facts:
                self.memory.learn_fact(cat, key, val)

        # Notify proactive engine
        self.proactive.on_interaction()

    def get_messages(self) -> list[dict]:
        msgs = [{"role": "system", "content": self.system_prompt}]
        for m in self.conversation:
            msgs.append({"role": m["role"], "content": m["content"]})
        return msgs

    async def broadcast(self, event: dict):
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.remove(ws)


state = SamanthaState()


# ─── App ─────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    state.load_config()
    await state.init_integrations()
    # Start proactive polling
    task = asyncio.create_task(proactive_loop())
    logger.info("🌸 Samantha is awake")
    yield
    task.cancel()
    # Save conversation summary on shutdown
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
        if state.embeddings:
            ep_id = state.memory.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            await state.embeddings.store("episode", ep_id, summary)
        logger.info(f"Saved episode: {topics}, threads: {threads}")
        state.memory.close()
    await state.registry.shutdown_all()
    logger.info("💤 Samantha is sleeping")


app = FastAPI(title="Samantha Orchestrator", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─── Proactive Loop ─────────────────────
async def proactive_loop():
    """Periodically check integrations and behaviors for notifications."""
    while True:
        await asyncio.sleep(PROACTIVE_INTERVAL)
        try:
            # Integration notifications (emails, meetings, etc.)
            updates = await state.registry.check_proactive()
            for update in updates:
                await state.broadcast(update)

            # Phase 3: Proactive behaviors (greetings, check-ins, mood shifts)
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

            # Handle morning briefing specifically
            if event and event.type == "morning_briefing":
                try:
                    context_parts = []
                    # Get weather
                    weather_intg = state.registry.get("weather")
                    if weather_intg:
                        weather = await weather_intg.execute("current_weather", {})
                        context_parts.append(f"Weather: {json.dumps(weather)}")
                    # Get latest news digest
                    if state.news_digest:
                        digest = state.news_digest.get_latest_digest()
                        if not digest:
                            digest_result = await state.news_digest.run_digest(llm_chat)
                            if digest_result:
                                digest = digest_result
                        if digest:
                            context_parts.append(f"News: {digest.get('summary', '')}")
                    # Get unresolved threads
                    if state.memory:
                        threads = state.memory.get_unresolved_threads(3)
                        if threads:
                            context_parts.append(f"Follow up from recent chats: {[t['topic'] for t in threads]}")
                    if context_parts:
                        briefing = await llm_chat([
                            {"role": "system", "content": "You are Samantha. Give a warm, natural morning briefing in 2-3 sentences. No lists. Mention weather, news, and any follow-ups."},
                            {"role": "user", "content": "\n".join(context_parts)},
                        ], max_tokens=150)
                        await state.broadcast({
                            "event": "card",
                            "title": "Good Morning",
                            "body": briefing[:200],
                        })
                except Exception as e:
                    logger.warning(f"Morning briefing failed: {e}")

            # News digest cycle
            now_ts = _time.time()
            global _last_news_digest
            if now_ts - _last_news_digest > NEWS_DIGEST_INTERVAL and state.news_digest:
                _last_news_digest = now_ts
                digest = await state.news_digest.run_digest(llm_chat)
                if digest and digest.get("notable"):
                    await state.broadcast({
                        "event": "card",
                        "title": "World News",
                        "body": digest.get("reaction") or digest["summary"][:100],
                    })
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Proactive check error: {e}")


# ─── Core Pipeline ───────────────────────
async def transcribe(audio_bytes: bytes) -> str:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"http://{STT_HOST}/transcribe", files={"audio": ("a.wav", audio_bytes, "audio/wav")})
        r.raise_for_status()
        return r.json()["text"]


async def llm_chat(messages: list[dict], max_tokens: int = 500) -> str:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"http://{OLLAMA_HOST}/api/chat", json={
            "model": OLLAMA_MODEL, "messages": messages, "stream": False,
            "options": {"temperature": 0.85, "num_predict": max_tokens, "num_ctx": OLLAMA_CTX},
        })
        r.raise_for_status()
        return r.json()["message"]["content"]


# Pronunciation dictionary — words Samantha should pronounce correctly
# Uses Kokoro's IPA syntax: [word](/phonemes/)
_PRONUNCIATIONS = {
    "Landskrona": "/lˈændskɹˌunə/",
    "Emplex": "/ˈɛmplɛks/",
    "Jussi": "/jˈusi/",
    "Majken": "/mˈaɪkən/",
    "Bokio": "/bˈoʊkioʊ/",
}


def _prepare_for_tts(text: str) -> str:
    """Clean text for natural Kokoro speech + apply pronunciation hints."""
    text = _strip_emotion_tags(text)

    # Replace interjections that sound robotic
    replacements = {
        'Hmm': 'Mm', 'hmm': 'mm', 'Hmmm': 'Mm', 'hmmm': 'mm',
        'haha': '', 'Haha': '', 'Ha ha': '',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r'  +', ' ', text).strip()

    # Apply pronunciation dictionary (KPipeline understands [word](/IPA/))
    for word in sorted(_PRONUNCIATIONS.keys(), key=len, reverse=True):
        ipa = _PRONUNCIATIONS[word]
        pattern = r'\b' + re.escape(word) + r'\b'
        text = re.sub(pattern, f"[{word}]({ipa})", text, flags=re.IGNORECASE)

    return text


async def synthesize(text: str) -> bytes:
    clean = _prepare_for_tts(text)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"http://{TTS_HOST}/synthesize", json={"text": clean})
        r.raise_for_status()
        return r.content


async def process_message(user_text: str) -> dict:
    """Full pipeline: intent detection → action or LLM → response."""
    analysis = state.personality.analyze_input(user_text)

    await state.refresh_memory_context(user_text)

    # Check for integration intent
    intent = state.router.route(user_text) if state.router else None

    if intent and intent.confidence > 0.5:
        # Execute integration action
        logger.info(f"🔧 Action: {intent.integration_name}.{intent.action_name}")
        intg = state.registry.get(intent.integration_name)
        if intg:
            result = await intg.execute(intent.action_name, intent.parameters)

            # Ask LLM to format the result conversationally
            # Truncate tool results to avoid overwhelming the small LLM
            result_str = json.dumps(result)
            if len(result_str) > 3000:
                result_str = result_str[:3000] + "..."
            state.add_message("user", user_text)
            state.add_message("system", f"Tool result for {intent.action_name}: {result_str}\n\nSummarize this naturally in 1-2 spoken sentences. No lists.")
            response = await llm_chat(state.get_messages())
            # Clean up the system message
            state.conversation = [m for m in state.conversation if not (m["role"] == "system" and "Tool result" in m["content"])]
            # Fallback if LLM returns empty
            if not response.strip():
                # Build a simple summary from the result
                if "headlines" in result:
                    titles = [h.get("title", "") for h in result["headlines"][:3]]
                    response = "Here's what I found. " + " Also, ".join(t for t in titles if t) + "."
                else:
                    response = "I got some results but I'm having trouble putting them into words right now."
            state.add_message("assistant", response)
            state.personality.update_mood(analysis)
            return {"text": _strip_emotion_tags(_clean_response(response)), "tts_text": _clean_response(response), "mood": state.personality.mood, "action": intent.action_name, "result": result}

    # Normal conversation
    state.add_message("user", user_text)
    response = await llm_chat(state.get_messages())

    # Check if the LLM wants to use a tool
    tool_call = _parse_tool_call(response)
    if tool_call:
        action_name = tool_call.get("tool", "")
        params = tool_call.get("params", {})
        # Find which integration owns this action
        for intg_name, action in state.registry.get_all_actions():
            if action.name == action_name:
                intg = state.registry.get(intg_name)
                if intg:
                    result = await intg.execute(action_name, params)
                    state.add_message("system", f"Tool result for {action_name}: {json.dumps(result)}")
                    response = await llm_chat(state.get_messages())
                    state.conversation = [m for m in state.conversation if not (m["role"] == "system" and "Tool result" in m["content"])]
                break

    state.add_message("assistant", response)
    state.personality.update_mood(analysis)
    return {"text": _strip_emotion_tags(_clean_response(response)), "tts_text": _clean_response(response), "mood": state.personality.mood}


import re

# Emotion tags that Orpheus TTS can render as audio
_EMOTION_TAG_RE = re.compile(r'<(laugh|chuckle|sigh|gasp|cough|sniffle|yawn|groan)>')

def _strip_emotion_tags(text: str) -> str:
    """Remove emotion tags for display while keeping them for TTS."""
    cleaned = _EMOTION_TAG_RE.sub('', text)
    return re.sub(r'  +', ' ', cleaned).strip()


def _clean_response(text: str) -> str:
    """Clean LLM response of any HTML/markdown artifacts."""
    text = re.sub(r'</?(p|br|div|span)[^>]*>', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    return text.strip()


def _parse_tool_call(text: str) -> dict | None:
    """Try to extract a JSON tool call from LLM response."""
    try:
        # Look for JSON in the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            candidate = text[start:end]
            parsed = json.loads(candidate)
            if "tool" in parsed:
                return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ─── REST Endpoints ─────────────────────��
class TextInput(BaseModel):
    text: str


@app.get("/health")
async def health():
    return {"status": "ok", "name": "Samantha", "mood": state.personality.mood,
            "integrations": state.registry.status_summary()}


@app.post("/chat/text")
async def chat_text(inp: TextInput):
    logger.info(f"💬 User: {inp.text}")
    await state.broadcast({"event": "user_speaking", "text": inp.text})
    result = await process_message(inp.text)
    logger.info(f"🌸 Samantha: {result['text']}")
    await state.broadcast({"event": "samantha_speaking", "text": result["text"], "mood": result["mood"]})
    asyncio.create_task(_extract_memories(inp.text, result.get("tts_text", result["text"])))
    return result


@app.post("/chat/audio")
async def chat_audio(audio: UploadFile = File(...)):
    logger.info("🎤 Audio received")
    await state.broadcast({"event": "listening"})

    audio_bytes = await audio.read()
    user_text = await transcribe(audio_bytes)
    logger.info(f"💬 Heard: {user_text}")
    if not user_text.strip():
        return {"error": "Could not transcribe"}

    await state.broadcast({"event": "user_speaking", "text": user_text})
    await state.broadcast({"event": "thinking"})

    result = await process_message(user_text)
    logger.info(f"🌸 Samantha: {result['text']}")

    audio_out = await synthesize(result.get("tts_text", result["text"]))
    await state.broadcast({"event": "samantha_speaking", "text": result["text"], "mood": result["mood"]})

    from fastapi.responses import Response
    return Response(content=audio_out, media_type="audio/wav",
                    headers={"X-Samantha-Text": result["text"], "X-Samantha-Mood": result["mood"]})


@app.get("/integrations")
async def list_integrations():
    return state.registry.status_summary()


@app.get("/conversation")
async def get_conversation():
    return {"conversation": state.conversation, "mood": state.personality.mood}


@app.post("/reset")
async def reset():
    # Save episode before reset
    if state.memory and state.conversation:
        summary = state.summarizer.generate_summary(state.conversation)
        topics = state.summarizer.extract_topics(state.conversation)
        state.memory.save_episode(
            summary=summary, topics=topics,
            mood_arc=state.personality.mood,
            message_count=len(state.conversation),
            started_at=state._session_start,
            unresolved_threads=[],
        )
    state.conversation = []
    state.personality = PersonalityEngine()
    state._session_start = datetime.now().isoformat()
    await state.broadcast({"event": "reset"})
    return {"status": "reset"}


@app.post("/reset-all")
async def reset_all():
    """Wipe ALL memory — facts, episodes, moods, embeddings, news. Fresh start."""
    if state.memory:
        state.memory.conn.executescript("""
            DELETE FROM facts;
            DELETE FROM episodes;
            DELETE FROM mood_log;
            DELETE FROM memory_embeddings;
            DELETE FROM news_digests;
            DELETE FROM notes;
            DELETE FROM reminders;
            DELETE FROM memories;
            DELETE FROM episodes_fts;
            DELETE FROM facts_fts;
        """)
        state.memory.conn.commit()
        logger.info("🗑️ All memory wiped")
    state.conversation = []
    state.personality = PersonalityEngine()
    state._session_start = datetime.now().isoformat()
    state._memory_context = ""
    await state.broadcast({"event": "reset"})
    return {"status": "all_memory_cleared"}


@app.get("/memory")
async def get_memory():
    """View Samantha's long-term memory — facts organized by entity."""
    if not state.memory:
        return {"error": "Memory not initialized"}

    # Group facts by subject
    try:
        rows = state.memory.conn.execute(
            "SELECT subject, category, key, value, confidence FROM facts ORDER BY subject='user' DESC, confidence DESC LIMIT 200"
        ).fetchall()
    except Exception:
        rows = state.memory.conn.execute(
            "SELECT 'user' as subject, category, key, value, confidence FROM facts ORDER BY confidence DESC LIMIT 200"
        ).fetchall()

    by_subject = {}
    for r in rows:
        subj = r['subject'] if 'subject' in r.keys() else 'user'
        if subj not in by_subject:
            by_subject[subj] = []
        by_subject[subj].append({
            "category": r['category'], "key": r['key'],
            "value": r['value'], "confidence": r['confidence']
        })

    return {
        "facts_by_subject": by_subject,
        "entities": state.memory.get_entities(),
        "recent_episodes": state.memory.get_recent_episodes(10),
        "dominant_mood": state.memory.get_dominant_mood(4),
    }


@app.get("/memory/search")
async def search_memory(q: str):
    if not state.memory:
        return {"error": "Memory not initialized"}
    return {
        "facts": state.memory.search_facts(q),
        "episodes": state.memory.search_episodes(q),
    }


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for chunked TTS."""
    import re
    # Split on sentence-ending punctuation, keeping the punctuation
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    # Filter empty and merge very short fragments
    sentences = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Merge very short fragments with previous sentence
        if sentences and len(p) < 15 and not p[-1] in '.!?':
            sentences[-1] += ' ' + p
        else:
            sentences.append(p)
    return sentences if sentences else [text]


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
                intensity=float(analysis.get("intensity", 0.5)),
                note=analysis.get("note", ""),
            )
        except Exception as e:
            logger.debug(f"Background memory extraction failed: {e}")


async def _send_audio(ws: WebSocket, result: dict):
    """Send complete audio — Kokoro is fast enough for single WAV."""
    try:
        import base64
        tts_text = result.get("tts_text", result["text"])
        audio_out = await synthesize(tts_text)
        await ws.send_json({
            "event": "audio_ready",
            "audio": base64.b64encode(audio_out).decode(),
        })
    except Exception as e:
        logger.warning(f"TTS failed: {e}")


# ─── WebSocket ───────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    state.clients.append(ws)
    logger.info(f"🖥️  Shell connected ({len(state.clients)})")

    await ws.send_json({"event": "connected", "name": "Samantha", "mood": state.personality.mood})

    # Auto-greet: if first time (no facts), introduce herself and ask name
    if state.memory:
        fact_count = len(state.memory.recall_facts(limit=3))
        if fact_count == 0:
            greeting = "Hey... I don't think we've met yet. I'm Samantha. What's your name?"
            await ws.send_json({"event": "samantha_speaking", "text": greeting, "mood": "warm"})
            asyncio.create_task(_send_audio(ws, {"text": greeting, "tts_text": greeting}))
        else:
            # Returning user — warm greeting
            from personality import PersonalityEngine
            p = PersonalityEngine()
            g = p.greeting()
            await ws.send_json({"event": "samantha_speaking", "text": g, "mood": "calm"})
            asyncio.create_task(_send_audio(ws, {"text": g, "tts_text": g}))

    try:
        while True:
            data = await ws.receive_json()

            if data.get("event") == "audio_chunk":
                import base64
                audio_bytes = base64.b64decode(data["audio"])
                user_text = await transcribe(audio_bytes)
                if not user_text.strip():
                    continue
                await ws.send_json({"event": "user_speaking", "text": user_text})
                await ws.send_json({"event": "thinking"})
                result = await process_message(user_text)
                # Send text immediately so the user sees the response fast
                await ws.send_json({"event": "samantha_speaking", "text": result["text"], "mood": result["mood"]})
                # Synthesize audio in background and send when ready
                asyncio.create_task(_send_audio(ws, result))
                asyncio.create_task(_extract_memories(
                    user_text,
                    result.get("tts_text", result["text"])
                ))

            elif data.get("event") == "text_input":
                text = data["text"]
                await ws.send_json({"event": "user_speaking", "text": text})
                await ws.send_json({"event": "thinking"})
                result = await process_message(text)
                # Send text immediately
                await ws.send_json({"event": "samantha_speaking", "text": result["text"], "mood": result["mood"]})
                # Synthesize audio in background
                asyncio.create_task(_send_audio(ws, result))
                asyncio.create_task(_extract_memories(
                    text,
                    result.get("tts_text", result["text"])
                ))

    except WebSocketDisconnect:
        state.clients.remove(ws)
        logger.info(f"🖥️  Shell disconnected ({len(state.clients)})")
