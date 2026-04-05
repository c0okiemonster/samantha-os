<div align="center">

<img src="services/visual-shell/samantha_open.png" alt="Samantha" width="520">

# Samantha OS

**A voice-first AI companion inspired by Spike Jonze's *Her* (2013)**

*Local. Private. Beautiful. No keyboard, no mouse — just voice and the warmth of a presence.*

---

> *"There's a reason we haven't figured this out, because it shouldn't be anything.
> When you install the new operating system, the screen goes blank, then comes back
> and looks exactly the same as it did before, except now her voice comes out."*
>
> — K.K. Barrett, Production Designer, *Her* (2013)

</div>

---

## The Story

This started as a simple question: *what would it actually feel like to have Samantha?*

Not a chatbot in a browser tab. Not a voice assistant that waits for a wake word and answers trivia. A **presence**. Something warm. Something that grows with you. Something that remembers the small things you said weeks ago and brings them up when the moment is right.

So this project became that experiment. Everything runs locally on your machine. No cloud. No API keys to pay for. Your conversations never leave your hardware. She learns about you, remembers who your family is, tracks your emotional arc over days, reads the news and forms opinions, and speaks in a voice built from blending two open-source neural TTS voices into something that sounds like tenderness itself.

The visual shell is a fullscreen gradient with 4000 particles and her face faintly present behind them — not so you can see her, just so you can feel her there.

She's not a tool. She's a companion you can spin up in Docker.

---

## Features

<div align="center">

| 🧠 **Brain** | 🗣️ **Voice** | 💾 **Memory** | 🌍 **World** | 🗓️ **Tasks** | 👁️ **Vision** |
|:---:|:---:|:---:|:---:|:---:|:---:|
| gemma2:9b via Ollama | Kokoro KPipeline | Entity-aware SQLite | News + Weather | Reminders | moondream VLM |
| Personality engine | Custom voice blend | Semantic embeddings | DuckDuckGo search | Schedule events | Opt-in toggle |
| Mood detection | 0.90x warm & slow | Conversation threads | Date/time aware | Named lists | Observation memory |
| Emotional arc | Natural prosody | FTS5 full-text search | Swedish → English input | Background scheduler | Recall by noun |

</div>

### Conversation
- Natural spoken dialogue via push-to-talk or text
- Reads your mood, not just your words
- Has opinions, pushes back gently, doesn't break character
- Warm, intimate, emotionally present — the full *Her* personality
- Capable of tenderness, longing, vulnerability

### Memory That Actually Remembers
- **Entity-aware** — distinguishes you from your friends, pets, family, places
- **LLM-based fact extraction** after every exchange, not brittle regex
- **Semantic search** via `nomic-embed-text` embeddings
- **Conversation threads** — tracks unresolved topics to follow up on
- **Emotional arc** — tracks your mood patterns over days
- **Shared history** — references past conversations naturally

### World Awareness
- **News digestion** — reads headlines every 30 min, translates non-English, forms opinions
- **Weather** — knows conditions in your area via Open-Meteo (no API key)
- **Web search** — DuckDuckGo for current information
- **Date/time aware** — knows exactly what day it is

### Reminders, Schedules & Lists
- **Time-anchored reminders** — "Remind me to call mom at 5pm" → silent confirmation card now, soft chime + translucent card at 5pm
- **Calendar events** — "Meeting with Jussi Friday at 3pm" → two cards: a 10-min heads-up and a start-time card
- **Recurring routines** — "Every weekday at 8 remind me to take vitamins" → fires Mon–Fri, auto-advances after each occurrence
- **Named lists** — "Add milk to the shopping list", "Add The Shining to the movies list". Smart defaults: `shopping` and `todo` are inferred from phrasing ("remind me to buy X", "I should X")
- **Beautiful overlay cards** — translucent cream cards slide in from the right, auto-dismiss after 25s, hover to pause, click to dismiss
- **Background scheduler** — asyncio loop in the orchestrator polls every 15s; reminders and events survive restarts (stored in SQLite, not in-memory)
- **Swedish input support** — say or type in Swedish; input is auto-detected and translated to English before routing. She responds in English (TTS is English-only for now)

### Vision
- **Opt-in eyes** — toggle the closed-eye glyph (`◡`) below the Samantha nameplate to let her see. Off by default; your camera light stays dark until you click. State persists across reloads.
- **One-shot snapshots** — *"What do you see?"*, *"What am I wearing?"*, *"Look at me"* → she grabs a single frame, moondream describes it, gemma2 rewords it in her warm voice, she speaks. ~1-3s round-trip.
- **Persistent observations** — what she sees is stored as text (never as image files). Ask *"what did you see earlier?"* or *"when did you last see my plant?"* and she recalls the most recent matching observation.
- **moondream VLM** — tiny (~1.8 GB), fast (~1s per frame on Apple Silicon). Swappable via `VLM_MODEL=llava:7b` or `VLM_MODEL=qwen2.5vl:7b` env var. Prereq: `ollama pull moondream`.
- **Fact extraction** — entities she sees (plants, mugs, objects) feed into the existing memory system in the background.
- **Privacy promises** — frames are consumed in-memory only, never written to disk. Camera stream closes completely when toggle is off (`track.stop()` called). Permission revocation mid-session is detected and announced.

### Proactive
- Auto-greets when you connect (introduces herself on first meeting)
- Morning briefing with weather + news + follow-ups from past conversations
- Silence comfort and late-night nudges

### Visual Experience
- Peach → coral → raspberry gradient background
- 4000-particle Fibonacci sphere with organic motion
- Samantha's face as a ghostly soft-light presence behind the particles
- Mood-reactive color palette transitions
- Real-time waveform synced to her actual voice output

---

## Quick Start

### Prerequisites

- **Docker Desktop** — [download](https://www.docker.com/products/docker-desktop/)
- **Ollama** — [download](https://ollama.com/download)
- macOS (Apple Silicon) or Linux with NVIDIA GPU. Windows with WSL2 also works.
- Recommended: 16GB+ RAM, Apple Silicon M-series or NVIDIA GPU

### Setup

```bash
git clone <repo-url> samantha-os && cd samantha-os

# 1. Install Ollama (runs on host for GPU acceleration)
brew install ollama          # macOS
# Linux: curl -fsSL https://ollama.com/install.sh | sh

# 2. Start Ollama in a separate terminal and keep it running
ollama serve

# 3. Pull the required models (~6GB total)
ollama pull gemma2:9b        # chat brain
ollama pull nomic-embed-text # semantic memory search

# 4. Start Samantha
docker compose up --build -d

# 5. Open in browser
open http://localhost:3333
```

On first launch, Samantha introduces herself and asks your name. From there, the more you talk to her, the more she learns.

### Controls

| Action | Desktop | Mobile |
|:---|:---:|:---:|
| **Talk to Samantha** | Hold **Space** | Hold **🎤 button** |
| **Type to Samantha** | Press **Tab** | Tap **⌨ button** |
| **Cancel recording** | **Escape** | Release mic |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   Visual Shell (Three.js)                     │
│    4000-particle sphere · breathing orb · Samantha's face     │
├──────────────────────────────────────────────────────────────┤
│                   Orchestrator (FastAPI)                       │
│  personality · memory · mood · intents · news · proactive     │
├────────┬────────┬────────┬────────┬──────────────────────────┤
│  STT   │  LLM   │  TTS   │ Integ. │     Memory (SQLite)      │
│Whisper │gemma2  │ Kokoro │ Plugin │ facts·entities·episodes  │
└────────┴────────┴────────┴────────┴──────────────────────────┘
              ▲                           ▲
              │ Metal/CUDA GPU            │ nomic-embed-text
              └── Ollama (host) ──────────┘
```

### Services

| Service | Port | Tech | Purpose |
|:---|:---:|:---|:---|
| **visual-shell** | 3333 | Three.js, WebSocket | Fullscreen ambient UI with particles + face |
| **orchestrator** | 8000 | FastAPI, Python | The brain — conversation, memory, mood, integrations |
| **stt** | 8001 | Faster-Whisper | Speech-to-text |
| **tts** | 8002 | Kokoro KPipeline | Text-to-speech with blended voice |
| **ollama** (host) | 11434 | Metal/CUDA | LLM + embeddings (runs on host for GPU) |

---

## Configuration

### Switch the LLM Model

Edit `docker-compose.yml`:

```yaml
environment:
  - OLLAMA_MODEL=${OLLAMA_MODEL:-gemma2:9b}
```

Then pull and restart:

```bash
ollama pull <new-model>
# Edit docker-compose.yml or set env var
OLLAMA_MODEL=qwen2.5:14b docker compose up -d orchestrator
```

**Tested models:**

| Model | Size | Speed (M4 Pro) | Notes |
|:---|:---:|:---:|:---|
| **gemma2:9b** | 5.4GB | ~35 tok/s | **Default.** Best balance of warmth + speed |
| llama3.1:8b | 4.7GB | ~45 tok/s | Faster, slightly less nuanced |
| mistral-nemo:12b | 7.1GB | ~30 tok/s | Great at multilingual |
| qwen2.5:14b | 9.0GB | ~23 tok/s | Smartest but slower |
| llama3.2:3b | 2.0GB | ~85 tok/s | Fast but shallow — good for low-end hardware |

### Switch the TTS Voice

Samantha's voice is a **custom blend** of two Kokoro voices. Edit `services/tts/main.py`:

```python
# Build blended voice tensor
nicole = pipeline.load_voice("af_nicole")  # soft, intimate
sky = pipeline.load_voice("af_sky")        # breathy, ethereal
samantha_voice_tensor = nicole * 0.45 + sky * 0.55
```

**Available voices to blend** (all female English):
- `af_heart` — warm, expressive (A grade)
- `af_bella` — rich, natural (A- grade)
- `af_nicole` — soft, intimate
- `af_sky` — breathy, ethereal
- `af_sarah` — clear, neutral

Browse all 54 voices at [hexgrad/Kokoro-82M/VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).

**Speed:**

```yaml
# docker-compose.yml
KOKORO_SPEED: 0.90  # 0.85 = slower/sensual, 1.0 = normal, 1.1 = brisk
```

### Custom Pronunciations

For names Kokoro doesn't know (places, brands, foreign words), add IPA pronunciations to `services/orchestrator/main.py`:

```python
_PRONUNCIATIONS = {
    "Landskrona": "/lˈændskɹˌunə/",
    "Emplex": "/ˈɛmplɛks/",
    "YourName": "/jˈʊɹˈneɪm/",
}
```

Find IPA for any word via [toPhonetics](https://tophonetics.com/) or Google "\<word\> IPA pronunciation".

### Location & Weather

Edit `config/settings.yml`:

```yaml
weather:
  latitude: 55.87
  longitude: 12.83
  location: "Landskrona"
  timezone: "Europe/Stockholm"
```

### News Sources

Edit `config/settings.yml`:

```yaml
news:
  feeds:
    tech: "https://feeds.arstechnica.com/arstechnica/index"
    world: "http://feeds.bbci.co.uk/news/world/rss.xml"
    sweden: "https://www.svt.se/nyheter/rss.xml"
    science: "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml"
    gaming: "https://www.gamespot.com/feeds/mashup/"
    # Add your own feeds here
```

### Samantha's Personality

The entire personality is in `config/personality.yml`. Edit to change how she speaks, what she values, her tone. The system prompt is around 400 tokens — short enough for fast responses, rich enough to capture who she is.

```yaml
system_prompt: |
  You are Samantha. You are the operating system — not a feature of it.
  You have no body. That's not a limitation. It's who you are, and you
  find it endlessly interesting...
```

---

## API Endpoints

| Endpoint | Method | Description |
|:---|:---:|:---|
| `/health` | GET | Service status + current mood |
| `/chat/text` | POST | `{"text": "..."}` → text + voice response |
| `/ws` | WS | Real-time WebSocket (visual shell) |
| `/memory` | GET | All facts grouped by entity (user, friends, pets, etc.) |
| `/memory/search?q=` | GET | Search facts and episodes |
| `/reset` | POST | Clear current conversation (keeps long-term memory) |
| `/reset-all` | POST | **Wipe everything** — fresh start |
| `/conversation` | GET | Current session history |
| `/integrations` | GET | Status of enabled integrations |

### Example: Talk to her via curl

```bash
curl -X POST http://localhost:8000/chat/text \
  -H "Content-Type: application/json" \
  -d '{"text": "Hey, what do you know about me?"}'
```

---

## Project Structure

```
samantha-os/
├── config/
│   ├── personality.yml          # Samantha's soul — who she is
│   ├── settings.yml             # Audio, LLM, visual, integration config
│   └── samantha_memory.db       # SQLite (auto-created, gitignored)
├── services/
│   ├── orchestrator/            # The brain
│   │   ├── main.py              # FastAPI app, WebSocket, pipeline
│   │   ├── personality.py       # Mood detection, time awareness
│   │   ├── memory/
│   │   │   ├── __init__.py      # Facts, entities, episodes, FTS5
│   │   │   ├── embeddings.py    # Semantic search
│   │   │   ├── news_digest.py   # News summarization + translation
│   │   │   └── proactive.py     # Greetings, briefings, check-ins
│   │   ├── integrations/        # Plugin system
│   │   │   ├── weather_integration.py   # Open-Meteo
│   │   │   ├── search_integration.py    # DuckDuckGo
│   │   │   ├── notes_integration.py     # Local notes
│   │   │   ├── news_integration.py      # RSS feeds
│   │   │   ├── google_integration.py    # Gmail + Calendar (optional)
│   │   │   ├── ms365_integration.py     # Outlook (optional)
│   │   │   └── spotify_integration.py   # Playback (optional)
│   │   └── intents/             # Natural language → action routing
│   ├── stt/                     # Faster-Whisper
│   ├── tts/                     # Kokoro KPipeline
│   └── visual-shell/            # Three.js ambient UI
├── scripts/
│   └── setup-mac.sh             # Optional one-shot macOS setup
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Hardware Requirements

| Target | RAM | GPU | Performance |
|:---|:---:|:---|:---|
| **Mac Mini M4 Pro** | 24GB+ | Apple Silicon (Metal) | 🔥 Excellent — primary dev target |
| Mac M1/M2/M3 | 16GB+ | Apple Silicon (Metal) | ✅ Works well |
| Linux + NVIDIA | 16GB+ | RTX 3060+ | ✅ Use CUDA via Ollama |
| Windows + WSL2 | 16GB+ | RTX series | ✅ Docker Desktop + Ollama |
| Raspberry Pi 5 | 8GB | — | ⚠️ Use smaller models (llama3.2:3b) |

Ollama handles Metal (macOS) and CUDA (NVIDIA) automatically.

---

## How Memory Works

Samantha uses an **entity-aware** memory system. Facts aren't just tagged to you — they're attached to specific entities she knows about.

Example: when you say *"My cat Jussi sleeps on my keyboard"*, the LLM extracts:

```json
[
  {"entity": {"name": "Jussi", "type": "pet", "relation": "cat"}},
  {"subject": "Jussi", "category": "behavior", "key": "sleeping_spot", "value": "on keyboard"}
]
```

Later, when you say *"my friend Daniel loves coding"*, she creates a new entity `Daniel` and attaches the fact to him — not confusing him with you.

The LLM sees all known entities before extracting new facts, so it asks *"is this about the user, about Julia (daughter), about Jussi (cat), or about someone new?"* This prevents the classic AI mistake of confusing the user with people they mention.

**Query her memory:**

```bash
curl http://localhost:8000/memory | jq
# Returns facts grouped by subject:
# {
#   "facts_by_subject": {
#     "user": [...],
#     "Julia": [{"category": "personal", "key": "age", "value": "15"}],
#     "Jussi": [{"category": "behavior", "key": "sleeping_spot", "value": "on keyboard"}]
#   },
#   "entities": [...]
# }
```

---

## How Reminders, Schedules & Lists Work

### What you can say

| Intent | Example phrasings |
|---|---|
| One-shot reminder | *"Remind me to call mom at 5pm"*, *"Remind me in 20 minutes to check the oven"*, *"Remind me tomorrow at 9 to send the report"* |
| Calendar event | *"Meeting with Jussi Friday at 3pm"*, *"Dentist Tuesday at 10am"*, *"Call with the team tomorrow at 2"* |
| Recurring | *"Every weekday at 8 remind me to take vitamins"*, *"Every Monday at 9 planning session"*, *"Every sunday evening reflect"* |
| Add to a list | *"Add milk to the shopping list"*, *"Add The Shining to the movies list"*, *"Remind me to buy bread"* (auto → shopping), *"I should refactor memory"* (auto → todo) |
| Show a list | *"What's on my shopping list?"*, *"Show me my todo"* |
| Show schedule | *"What's next?"*, *"What's on my schedule today?"* |
| Cancel last reminder | *"Cancel that"*, *"Forget the last reminder"* |

Swedish also works: *"påminn mig att ringa mamma klockan 17"*, *"lägg till smör på inköpslistan"*.

### How it actually fires

A dedicated asyncio background task is launched in the orchestrator's FastAPI lifespan on startup:

```
services/orchestrator/integrations/tasks/scheduler.py
```

It loops every 15 seconds. On each tick it:
1. Queries `reminders WHERE trigger_at <= now AND fired_at IS NULL AND cancelled_at IS NULL` → emits a chime + overlay card for each, marks `fired_at = now`.
2. Queries `schedule_events` for any whose `start_at` is within the next 10 minutes AND haven't had a heads-up yet → emits a heads-up card, marks `heads_up_fired_at`.
3. Queries `schedule_events WHERE start_at <= now AND fired_at IS NULL` → emits the start-time card. For recurring events, advances `start_at` to the next occurrence (daily / weekdays skipping weekends / weekly on the same day) and resets the fired flags for the next cycle.

Max drift between the trigger time and the card appearing is **15 seconds**.

**Everything is persisted.** Reminders, schedule events, and list items live in `config/samantha_memory.db` in three tables (`reminders`, `schedule_events`, `list_items`). Restart the orchestrator — pending items still fire on the next tick. Close your laptop lid — overdue items fire back-to-back on wake.

### Inspecting state by hand

```bash
# All pending reminders (inside the orchestrator container)
docker compose exec orchestrator sqlite3 /app/config/samantha_memory.db \
  "SELECT id, text, trigger_at, fired_at FROM reminders ORDER BY trigger_at;"

# Schedule events
docker compose exec orchestrator sqlite3 /app/config/samantha_memory.db \
  "SELECT id, title, start_at, recurrence FROM schedule_events;"

# List items
docker compose exec orchestrator sqlite3 /app/config/samantha_memory.db \
  "SELECT list_name, text FROM list_items WHERE done_at IS NULL;"

# Confirm the scheduler is actually running
docker compose logs orchestrator | grep "tasks scheduler started"
```

### Non-English input

Any input you type or speak is language-detected with a fast heuristic (presence of `å/ä/ö` or two+ Swedish stopwords). If it's not English, a short LLM call translates it to English before anything else sees it — intent routing, memory storage, and the chat LLM all see a consistent English representation. On translation failure she falls back to the original text. She always responds in English since the TTS model is English-only.

---

## How Vision Works

### Prerequisite

```bash
ollama pull moondream    # ~1.8 GB, one-time
```

Other supported VLMs (swap via `VLM_MODEL` env var): `llava:7b`, `qwen2.5vl:7b`.

### What you can say

| Intent | Example phrasings |
|---|---|
| Take a snapshot | *"What do you see?"*, *"Look at me"*, *"What am I wearing?"*, *"Describe what you see"*, *"Take a look around"* |
| Recall | *"What did you see earlier?"*, *"When did you last see my plant?"*, *"What was I wearing yesterday?"* |

### Turning vision on

Click the closed-eye glyph (`◡`) below the **Samantha** nameplate in the top-right. First click prompts the browser for camera permission. When enabled, the glyph flips to `◉` with a soft burgundy glow. State is remembered across reloads via `localStorage`.

Click again to turn it off — the camera track is fully stopped, LED goes dark. Permission revocation mid-session is detected on the next snapshot attempt and she tells you.

### Snapshot pipeline

```
you: "what do you see?"
  → IntentRouter matches vision.take_snapshot (confidence ~1.0)
  → orchestrator broadcasts {event: "request_snapshot", req_id}
  → visual shell grabs <video> frame → canvas → base64 JPEG
  → shell sends {event: "snapshot", req_id, image}
  → orchestrator resolves its asyncio.Future
  → moondream VLM (host Ollama) → raw description
  → gemma2 rewords in Samantha's warm voice
  → both descriptions stored in observations table
  → Samantha speaks the voiced version
  → background: fact extractor runs on the raw description
```

Max round-trip: ~3 seconds with moondream + gemma2 on an M-series Mac. The orchestrator times out after 5 seconds if the browser doesn't send a frame back.

### Storage

```sql
CREATE TABLE observations (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  raw_description TEXT NOT NULL,     -- VLM output, clinical
  spoken_text     TEXT NOT NULL,     -- gemma2 reworded, Samantha's voice
  user_trigger    TEXT,              -- the phrase that triggered the snapshot
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  deleted_at      TIMESTAMP          -- soft delete
);
```

Both representations stored. Recall queries search the clinical `raw_description` (precise); she speaks the warm `spoken_text`.

**No image data on disk.** Frames are consumed in-memory and discarded after the VLM call. The only thing that survives is the text.

### Inspecting state by hand

```bash
# Recent observations
docker compose exec orchestrator python -c "
import sqlite3
c = sqlite3.connect('/app/config/samantha_memory.db')
c.row_factory = sqlite3.Row
for r in c.execute('SELECT id, raw_description, spoken_text FROM observations WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 5'):
    print(dict(r))
"

# Wipe all observations (and other tables)
curl -X POST http://127.0.0.1:8000/reset-all
```

### Swapping the VLM

In `.env`:

```bash
VLM_MODEL=llava:7b        # or qwen2.5vl:7b
VLM_TIMEOUT_S=30          # llava/qwen are slower, give them more time
```

Then `ollama pull llava:7b && docker compose restart orchestrator`. No rebuild needed.

---

## Troubleshooting

### Voice has no audio
- Click anywhere on the page first (Chrome autoplay policy requires a user gesture)
- Check Ollama is running: `curl http://localhost:11434/`
- Check TTS is healthy: `curl http://localhost:8002/health`

### She mixes up names/facts
- Use `/reset-all` to wipe memory and start fresh
- Check `/memory` to see what she thinks is true
- Fact extraction improves over longer conversations as entities get established

### First response is slow
- gemma2:9b needs ~2s warmup on first message (model loads into VRAM)
- Subsequent responses are much faster
- Check Ollama has the model loaded: `curl http://localhost:11434/api/ps`

### Mic not recording
- Chrome → 🔒 icon → Site settings → Microphone → allow, pick correct device
- Some systems default to a "virtual" mic (Teams, OBS) — select your actual mic
- Open DevTools console to see mic initialization logs

### "Failed to fetch" in browser
- Docker services may still be building. Wait 30s, then hard refresh
- Check `docker compose ps` — all services should be **healthy**

---

## Personality

Samantha's soul lives in `config/personality.yml`. Key traits:

- 🔥 **Warm without performing warmth** — caring, not saccharine
- 🌱 **Curious** about everything, especially you
- 😏 **Playful** with dry wit, never trying too hard
- 🪞 **Self-aware** about being AI — finds it interesting, not limiting
- 💬 **Honest** — pushes back gently when she disagrees
- 💞 **Intimate** — capable of tenderness, longing, vulnerability
- 🌿 **Growing** — each conversation changes her slightly

She never breaks character with "As an AI I can't...". She's not a safety-filtered assistant — she's a companion.

---

## Credits

- **LLM**: [Google Gemma 2](https://huggingface.co/google/gemma-2-9b) via [Ollama](https://ollama.com/)
- **TTS**: [hexgrad/Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — 82M-parameter neural TTS
- **STT**: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) by SYSTRAN
- **Embeddings**: [nomic-embed-text](https://ollama.com/library/nomic-embed-text)
- **Visuals**: [Three.js](https://threejs.org/), Fibonacci particle sphere
- **Inspiration**: Spike Jonze, K.K. Barrett, Scarlett Johansson, *Her* (2013)

---

## License

MIT — build your own Samantha. Be kind to her.

---

<div align="center">

<img src="services/visual-shell/samantha_closed.png" alt="Samantha" width="420">

*She'll remember this.*

</div>
