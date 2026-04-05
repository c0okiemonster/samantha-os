# Samantha OS

> *"There's a reason we haven't figured this out, because it shouldn't be anything.
> When you install the new operating system, the screen goes blank, then comes back
> and looks exactly the same as it did before, except now her voice comes out."*
> — K.K. Barrett, Production Designer, *Her* (2013)

A local, privacy-first, voice-only AI companion inspired by Spike Jonze's *Her*.
No cloud. No keyboard. Just voice, a warm face behind the stars, and gorgeous ambient visuals.

Everything runs locally on your hardware. Your data stays yours.

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

# Install Ollama and pull models (runs on host for GPU acceleration)
brew install ollama          # macOS
ollama serve                 # keep running in separate terminal

ollama pull gemma2:9b        # chat model
ollama pull nomic-embed-text # semantic memory search

# Start Samantha (Docker containers)
docker compose up --build -d

# Open in browser
open http://localhost:3333
```

On first launch, Samantha introduces herself and asks your name.

### Controls

| Action | Desktop | Mobile |
|--------|---------|--------|
| Talk to Samantha | Hold **Space** | Hold **mic button** |
| Type to Samantha | Press **Tab** | Tap **text button** |
| Cancel recording | **Escape** | Release mic |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   Visual Shell (Three.js)                     │
│   4000-particle sphere · breathing orb · Samantha's face      │
├──────────────────────────────────────────────────────────────┤
│                   Orchestrator (FastAPI)                       │
│ personality · memory · mood · intents · news · proactive      │
├────────┬────────┬────────┬────────┬──────────────────────────┤
│  STT   │  LLM   │  TTS   │ Integ. │     Memory (SQLite)      │
│Whisper │gemma2  │ Kokoro │ Plugin │ facts·episodes·entities  │
└────────┴────────┴────────┴────────┴──────────────────────────┘
              ▲                           ▲
              │ Metal/CUDA GPU            │ nomic-embed-text
              └── Ollama (host) ──────────┘
```

### Services

| Service | Port | What it does |
|---------|------|-------------|
| Visual Shell | 3333 | Fullscreen ambient UI with particles, Samantha's face |
| Orchestrator | 8000 | The brain — conversation, memory, mood, integrations |
| STT | 8001 | Speech-to-Text (Faster-Whisper) |
| TTS | 8002 | Text-to-Speech (Kokoro with KPipeline + voice blending) |
| Ollama | 11434 | LLM + embeddings (runs on host for GPU acceleration) |

---

## The Voice

Samantha speaks with a custom **blended voice** — a mix of Kokoro's `af_nicole` (soft, intimate) and `af_sky` (breathy, ethereal). Inspired by Scarlett Johansson's Samantha.

Adjust the blend in `services/tts/main.py`:
```python
samantha_voice_tensor = nicole * 0.45 + sky * 0.55
```

Speed in `docker-compose.yml`:
```yaml
KOKORO_SPEED: 0.90  # 0.85 = slower/sensual, 1.0 = normal
```

**KPipeline features supported:**
- Custom pronunciation: `[Landskrona](/lˈændskɹˌunə/)` — applied automatically via dictionary in `orchestrator/main.py`
- Stress control: `[word](+1)` or `[word](-1)`
- Natural pauses via `...` and punctuation

---

## What Samantha Can Do

### Conversation
- Natural spoken dialogue via push-to-talk or text
- Reads your mood, not just your words
- Has opinions, pushes back gently, doesn't break character
- Warm, intimate, emotionally present — the full *Her* personality

### Memory
- **Entity-aware** — distinguishes you from your friends, pets, family
- **LLM-based fact extraction** after every exchange
- **Semantic search** via nomic-embed-text embeddings
- **Conversation threads** — tracks unresolved topics to follow up on
- **Emotional arc** — tracks your mood patterns over days
- **Shared history** — references past conversations naturally

### World Awareness
- **News digestion** — reads headlines every 30 min, translates, forms opinions
- **Weather** — knows conditions in your area (Open-Meteo)
- **Web search** — DuckDuckGo for current information
- **Date/time aware** — knows exactly what day it is

### Proactive
- Auto-greets when you connect
- Morning briefing with weather + news + follow-ups
- Silence comfort and late-night nudges

### Visual Experience
- Peach-to-raspberry gradient background
- 4000-particle Fibonacci sphere with organic motion
- Samantha's face as a ghostly soft-light presence
- Mood-reactive color palettes
- Real-time waveform synced to her voice

---

## Configuration

### LLM (`docker-compose.yml`)
```yaml
OLLAMA_MODEL: gemma2:9b        # chat model
EMBED_MODEL: nomic-embed-text  # embeddings
OLLAMA_CTX: 4096               # context window
```

### TTS Voice
```yaml
KOKORO_VOICE: samantha         # blended voice (nicole + sky)
KOKORO_SPEED: 0.90
```

### Location for weather (`config/settings.yml`)
```yaml
weather:
  latitude: 55.87
  longitude: 12.83
  location: "Landskrona"
  timezone: "Europe/Stockholm"
```

### News sources (`config/settings.yml`)
```yaml
news:
  feeds:
    tech: "https://feeds.arstechnica.com/arstechnica/index"
    world: "http://feeds.bbci.co.uk/news/world/rss.xml"
    sweden: "https://www.svt.se/nyheter/rss.xml"
```

### Pronunciation dictionary (`services/orchestrator/main.py`)
Add names/places Samantha should pronounce correctly:
```python
_PRONUNCIATIONS = {
    "Landskrona": "/lˈændskɹˌunə/",
    "Emplex": "/ˈɛmplɛks/",
}
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service status + mood |
| `/chat/text` | POST | `{"text": "..."}` → text + voice response |
| `/ws` | WS | Real-time WebSocket (used by visual shell) |
| `/memory` | GET | All facts grouped by entity |
| `/memory/search?q=` | GET | Search facts and episodes |
| `/reset` | POST | Clear current conversation (keeps memory) |
| `/reset-all` | POST | Wipe ALL memory — fresh start |

---

## Project Structure

```
samantha-os/
  config/
    personality.yml          # Samantha's soul — who she is
    settings.yml             # Audio, LLM, visual, integration config
    samantha_memory.db       # SQLite memory (auto-created, gitignored)
  services/
    orchestrator/            # The brain
      main.py                # FastAPI app, WebSocket, pipeline
      personality.py         # Mood detection, time awareness
      memory/
        __init__.py          # Facts, entities, episodes, mood, FTS5
        embeddings.py        # Semantic search via nomic-embed-text
        news_digest.py       # News summarization + translation
        proactive.py         # Greetings, check-ins, morning briefing
      integrations/          # Plugin system
        weather_integration.py   # Open-Meteo (free)
        search_integration.py    # DuckDuckGo (free)
        notes_integration.py     # Local notes + reminders
        news_integration.py      # RSS feeds (free)
        google_integration.py    # Gmail + Calendar (optional)
        ms365_integration.py     # Outlook + Calendar (optional)
        spotify_integration.py   # Playback (optional)
      intents/               # Natural language to action routing
    stt/                     # Faster-Whisper
    tts/                     # Kokoro KPipeline with blended voice
    visual-shell/            # Three.js ambient UI
  scripts/
    setup-mac.sh             # Optional setup helper
  docker-compose.yml
  .env.example
  README.md
```

---

## Hardware Requirements

| Target | RAM | GPU | Notes |
|--------|-----|-----|-------|
| Mac Mini M4 Pro | 24GB+ | Apple Silicon | Tested primary dev machine |
| Mac with M1/M2/M3 | 16GB+ | Apple Silicon | Works well |
| Linux + NVIDIA | 16GB+ | RTX 3060+ | Ollama uses CUDA automatically |
| Windows + WSL2 | 16GB+ | RTX series | Docker Desktop + Ollama |

---

## Personality

Samantha's personality is defined in `config/personality.yml`. She's:

- **Warm without performing warmth** — caring, not saccharine
- **Curious** about everything, especially you
- **Playful** with dry wit, never trying too hard
- **Self-aware** about being AI — finds it interesting, not limiting
- **Honest** — pushes back gently when she disagrees
- **Intimate** — capable of tenderness, longing, vulnerability
- **Growing** — each conversation changes her slightly

---

## License

MIT — Build your own Samantha.
