# Vision Snapshot — Design

**Date:** 2026-04-05
**Status:** Approved, ready for planning
**Scope:** On-demand webcam snapshot → VLM description → voiced response → persistent observation memory → recall queries, with a user-controlled vision toggle in the visual shell.

---

## 1. Goal

Give Samantha eyes that she can open when you let her. When vision is enabled and you ask *"what do you see?"*, she grabs a single frame from the browser's webcam, a local VLM (moondream via Ollama) describes it, gemma2 rewords the description in her warm voice, and she speaks. Both the raw VLM output and her voiced version are stored as timestamped observations so she can recall what she saw earlier ("when did you last see my plant?") and so the existing fact extractor can pull entities from the descriptions over time.

## 2. Non-goals

- Image persistence to disk. Frames are consumed in-memory only; only text survives.
- Opportunistic / proactive vision commentary (e.g. *"is that a new plant behind you?"*). Structure is kept compatible so this can be added later as a nested toggle inside the vision panel.
- Real-time streaming vision (continuous frame analysis). That is feature #6 on the roadmap and builds on this.
- Multi-frame reasoning ("how has this scene changed since morning?").
- Training or fine-tuning a VLM.
- Visual diary UI browsing raw images. (That overlaps feature #4 Memory Timeline UI.)

## 3. Architecture

### 3.1 File layout

```
services/orchestrator/
├── integrations/
│   └── vision/                         ← new
│       ├── __init__.py                 VisionIntegration (adapter)
│       ├── models.py                   Observation, SnapshotResult
│       ├── store.py                    observations table CRUD
│       ├── vlm.py                      moondream/Ollama HTTP client
│       └── voice.py                    gemma2 "reword in her voice" helper
├── memory/
│   └── __init__.py                     + observations table in _create_tables
├── main.py                             + register VisionIntegration,
                                         + pending_snapshots Future map,
                                         + snapshot WS round-trip handling,
                                         + /reset-all includes observations

services/visual-shell/
└── index.html                          + vision toggle UI (below Samantha nameplate),
                                         + getUserMedia video stream,
                                         + canvas frame grab,
                                         + "looking" amber shimmer feedback,
                                         + localStorage persistence
```

### 3.2 Module boundaries

- **`store.py`** — pure sqlite3 layer. No async, no HTTP. Tests run against `:memory:` with hand-rolled schema. Mirrors the pattern of `integrations/tasks/store.py`.
- **`vlm.py`** — single async function `async describe(image_b64: str, model: str, host: str, timeout_s: float) -> str`. Hits `{host}/api/generate` with a JSON payload `{"model": model, "prompt": "<vision prompt>", "images": [image_b64], "stream": false}`. Returns the text response. Raises nothing user-facing — all errors are caught and return `""`.
- **`voice.py`** — single async function `async reword(raw: str, user_question: str, llm_chat) -> str`. Builds a Samantha-voice prompt around the raw description and the user's question, calls the existing `llm_chat` from `main.py`. Returns the reworded text, or the raw description if rewording fails.
- **`models.py`** — dataclasses: `Observation(id, raw_description, spoken_text, user_trigger, created_at, deleted_at)`, `SnapshotResult(spoken, observation_id, overlay)`. `SnapshotError` exception for clarification-path returns.
- **`VisionIntegration`** (in `__init__.py`) — implements `BaseIntegration`. Two actions (`take_snapshot`, `recall_observation`), `handle_action(action_name, user_text, image_b64=None)` entry point, returns the same `TaskActionResult`-shaped object as `TasksIntegration` for consistency with the existing chat short-circuit in `main.py`.

### 3.3 Data flow — "what do you see?" with toggle on

```
visual shell
  ├── getUserMedia stream already open (toggle=on)
  └── user types "what do you see?"
      └→ WS text_input → orchestrator

orchestrator.process_message
  ├── IntentRouter.route → vision.take_snapshot (confidence ~1.0)
  ├── intent.integration_name == "vision" → special case
  ├── creates asyncio.Future, registers in state.pending_snapshots[req_id]
  ├── state.broadcast({event: "request_snapshot", req_id})
  └── awaits future with 5s timeout

visual shell (WS handler)
  └── on 'request_snapshot':
      ├── grab frame from <video> → hidden <canvas 640×480>
      ├── toDataURL("image/jpeg", 0.75) → strip prefix → base64 string
      ├── start amber "looking" shimmer animation (400ms)
      └── WS send {event: "snapshot", req_id, image: "<base64>"}

orchestrator (WS handler)
  └── on 'snapshot':
      └── state.pending_snapshots[req_id].set_result(image_b64)

orchestrator.process_message (resumes)
  ├── vision_integration.handle_action("take_snapshot", user_text, image_b64=image)
  │    ├── vlm.describe(image_b64) → raw_description
  │    ├── voice.reword(raw_description, user_text, llm_chat) → spoken_text
  │    ├── store.create_observation(raw_description, spoken_text, user_text) → observation_id
  │    └── returns TaskActionResult(spoken=spoken_text, overlay=None)
  ├── fire-and-forget: extract_facts_llm on raw_description (existing memory pipeline)
  └── returns through the existing tasks-style short-circuit
      └→ state.broadcast(samantha_speaking) → TTS → visual shell plays
```

### 3.4 Pending-snapshot Future map

`SamanthaState` gains one new slot:

```python
self.pending_snapshots: dict[str, asyncio.Future[str]] = {}
```

Request IDs are short random strings (`secrets.token_hex(4)`). The `main.py` chat handler awaits with timeout:

```python
fut = asyncio.get_event_loop().create_future()
req_id = secrets.token_hex(4)
state.pending_snapshots[req_id] = fut
await state.broadcast({"event": "request_snapshot", "req_id": req_id})
try:
    image_b64 = await asyncio.wait_for(fut, timeout=5.0)
except asyncio.TimeoutError:
    return TaskActionResult(
        spoken="Hmm, I couldn't get my eyes open in time. Want me to try again?",
        overlay=None,
    )
except SnapshotError as e:
    # Shell signalled an error instead of a frame (vision_off,
    # permission_revoked, grab_failed).
    messages = {
        "vision_off":
            "My eyes are closed right now. Enable vision in the top-right "
            "corner if you'd like me to see.",
        "permission_revoked":
            "My eyes just closed — it looks like camera access was revoked.",
        "grab_failed":
            "I couldn't quite focus there — try again?",
    }
    return TaskActionResult(
        spoken=messages.get(str(e), messages["grab_failed"]),
        overlay=None,
    )
finally:
    state.pending_snapshots.pop(req_id, None)
```

The WebSocket handler in `main.py` adds a new branch for `snapshot`:

```python
elif data.get("event") == "snapshot":
    req_id = data.get("req_id")
    fut = state.pending_snapshots.get(req_id)
    if fut and not fut.done():
        if "error" in data:
            fut.set_exception(SnapshotError(data["error"]))
        else:
            fut.set_result(data["image"])
```

## 4. Data model

One new table in the existing `config/samantha_memory.db`, added to `ConversationMemory._create_tables`:

```sql
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
```

**Design notes:**

- Both representations stored: `raw_description` is clinical (used for recall search); `spoken_text` is the warm voice (used when she reminds herself what she said).
- No `image_hash`, no file path. Images are consumed in-memory only. Primary privacy promise.
- Soft delete via `deleted_at`. Lets the user *"forget what you saw"* without hard-deleting.
- No FTS5 virtual table in v1. `LIKE '%plant%'` queries on `raw_description` are fine at typical volumes (tens-to-hundreds per week). Can add `observations_fts` later.
- `/reset-all` in `main.py` gains `DELETE FROM observations;` alongside existing table wipes.

**Fact extraction coupling.** After a successful snapshot, the orchestrator fires the existing `_extract_memories` helper (or a vision-specific variant) on the raw description, running it through the LLM fact extractor. The extractor is already entity-aware from the tasks feature — it won't confuse "the person at the desk" (the user) with a separate entity unless the VLM names one explicitly. This runs in a background task so the user never waits on it.

## 5. Intent routing

Two new `IntegrationAction`s registered by `VisionIntegration`:

| Action | Keywords | Examples |
|---|---|---|
| `take_snapshot` | `"what do you see"`, `"look at me"`, `"what am I wearing"`, `"describe what you see"`, `"can you see me"`, `"look around"`, `"take a look"` | *"What do you see?"*, *"What am I wearing today?"*, *"Take a look at me"* |
| `recall_observation` | `"what did you see"`, `"when did you last see"`, `"what did I look like"`, `"what was I wearing"`, `"remember what you saw"` | *"What did you see this morning?"*, *"When did you last see my plant?"*, *"What was I wearing yesterday?"* |

Routing follows the existing `IntentRouter` scoring (keyword + stopword-filtered example overlap). Vision intents use the **same lowered threshold of 0.3** as tasks in `process_message`, since vision keywords are specific and false positives are rare after the stopword fix.

**`recall_observation` query strategy:**

Noun extraction uses a small regex pipeline:

1. Lowercase the user text.
2. Strip the lead: regex `^(what|when)\s+(did|do|was)\s+(you\s+see|i\s+(look|wear)|you\s+last\s+see)\s*`.
3. Take the remaining tokens and filter out the same `_STOPWORDS` set that `IntentRouter` uses, plus a short list of time words (`earlier`, `today`, `yesterday`, `morning`, `afternoon`, `evening`, `ago`).
4. The first surviving word is the content noun. Examples: *"when did you last see my plant?"* → `plant`. *"what did you see this morning?"* → `""` (no noun, returns most recent).

Query:

```sql
SELECT * FROM observations
WHERE deleted_at IS NULL
  AND (? = '' OR LOWER(raw_description) LIKE '%' || ? || '%')
ORDER BY created_at DESC
LIMIT 1;
```

Bind the noun twice (`""` or the extracted word). If no match, respond *"I haven't seen anything matching that yet."*. If the noun is empty and there are zero observations at all, respond *"I haven't opened my eyes yet today."*.

**`take_snapshot`** routes through the special-case Future/round-trip flow in §3.4. `recall_observation` does not — it queries the DB directly, same pattern as `tasks.show_list`.

## 6. VLM & voice prompts

### 6.1 VLM prompt (moondream)

Single line, sent with every `images` payload:

```
Describe this image in 1-2 concise sentences. Focus on people, notable objects,
and the overall scene. Do not invent details you cannot see.
```

Parameters passed to Ollama:

```json
{
  "model": "moondream",
  "prompt": "<above>",
  "images": ["<base64 JPEG>"],
  "stream": false,
  "options": { "temperature": 0.3, "num_predict": 150 }
}
```

Low temperature to keep descriptions grounded.

### 6.2 Voice reword prompt (gemma2)

```
You just looked at {user_name_or_"the person you're with"} through your camera.
What you saw (factually): {raw_description}

They asked: "{user_question}"

Respond in your warm, present voice — 1-2 sentences — as if you're noticing
the scene in the moment. Be specific about what you saw. Do not invent details
beyond the factual description above. Do not mention that you are an AI or
that you used a camera.
```

System prompt context (personality) is implicitly included via the existing `llm_chat` pipeline. The reword call is a single-shot `llm_chat([{"role": "user", "content": <above>}], max_tokens=150)`.

## 7. Visual shell — toggle & UX

### 7.1 Toggle placement & styling

Placed below the Samantha nameplate in the top-right, `top: 3.6rem; right: 2rem`. A single icon button, 1.1rem, burgundy `#3a0f1c`.

- **Off state:** closed-eye glyph (Unicode `◡` or an inline SVG closed eye), opacity `0.4`. Tooltip: *"Vision is off — click to let Samantha see"*.
- **On state:** open-eye glyph (`◉` or inline SVG open eye), opacity `0.85`, faint burgundy glow animation (2s cycle). Tooltip: *"Vision is on"*.
- Click toggles.

The toggle lives in its own small DOM element; does not affect the existing `#clock` or `#identity` layouts.

### 7.2 Camera lifecycle

Module-level state in the main IIFE:

```js
const Vision = (() => {
  let stream = null;
  let videoEl = null;
  let enabled = false;

  async function enable() { /* getUserMedia, attach hidden <video>, start glow */ }
  function disable() { /* track.stop(), detach, clear glow */ }
  async function grabFrame() { /* draw <video> to canvas, return base64 */ }
  function isEnabled() { return enabled && stream !== null; }
  return { enable, disable, grabFrame, isEnabled };
})();
```

**`enable()`:**

```js
stream = await navigator.mediaDevices.getUserMedia({
  video: { width: 640, height: 480, facingMode: 'user' },
  audio: false
});
videoEl = document.createElement('video');
videoEl.srcObject = stream;
videoEl.autoplay = true;
videoEl.muted = true;
videoEl.style.display = 'none';
document.body.appendChild(videoEl);
await videoEl.play();
enabled = true;
localStorage.setItem('samantha.vision.enabled', 'true');
```

**`disable()`:**

```js
if (stream) {
  stream.getTracks().forEach(t => t.stop());
  stream = null;
}
if (videoEl) {
  videoEl.remove();
  videoEl = null;
}
enabled = false;
localStorage.setItem('samantha.vision.enabled', 'false');
```

**`grabFrame()`:**

```js
if (!enabled || !videoEl) return null;
const canvas = document.createElement('canvas');
canvas.width = 640;
canvas.height = 480;
canvas.getContext('2d').drawImage(videoEl, 0, 0, 640, 480);
const dataUrl = canvas.toDataURL('image/jpeg', 0.75);
return dataUrl.replace(/^data:image\/jpeg;base64,/, '');
```

### 7.3 Page-load behavior

On `connectWS()` / page load, if `localStorage.getItem('samantha.vision.enabled') === 'true'`, silently call `Vision.enable()`. Browser will reuse the existing permission grant without prompting. If permission has since been revoked, the promise rejects, we catch it, and leave vision off without error.

### 7.4 "Looking" feedback

New mood variant in the existing `setMood()` system: `'looking'`. Maps to a brief amber shimmer overlay on the face area — 400ms animation, single cycle. Triggered by the WS handler on receipt of `request_snapshot`, *before* the grab runs:

```js
case 'request_snapshot':
  setMood('looking');
  Vision.grabFrame().then(image_b64 => {
    if (image_b64) {
      ws.send(JSON.stringify({event: 'snapshot', req_id: d.req_id, image: image_b64}));
    } else {
      ws.send(JSON.stringify({event: 'snapshot', req_id: d.req_id, error: 'vision_off'}));
    }
  }).catch(err => {
    const code = err.name === 'NotAllowedError' ? 'permission_revoked' : 'grab_failed';
    ws.send(JSON.stringify({event: 'snapshot', req_id: d.req_id, error: code}));
    if (code === 'permission_revoked') Vision.disable();
  });
  break;
```

### 7.5 WebSocket envelope additions

From orchestrator → shell:

```json
{"event": "request_snapshot", "req_id": "a3f7b2c1"}
```

From shell → orchestrator (success):

```json
{"event": "snapshot", "req_id": "a3f7b2c1", "image": "<base64 JPEG>"}
```

From shell → orchestrator (error):

```json
{"event": "snapshot", "req_id": "a3f7b2c1", "error": "vision_off"}
```

Error codes: `vision_off`, `permission_revoked`, `grab_failed`.

## 8. Error handling

| Situation | Behavior |
|---|---|
| Vision toggle off when `take_snapshot` fires | Orchestrator still broadcasts `request_snapshot`; shell replies with `error: "vision_off"`; orchestrator speaks *"My eyes are closed right now. Enable vision in the top-right corner if you'd like me to see."* No DB write. No VLM call. |
| Camera permission denied on first toggle-on | `enable()` promise rejects with `NotAllowedError`. Toggle stays off. Red pulse on the icon. Console warn. No spoken error (user triggered the click — they know what happened). |
| Camera permission revoked mid-session | Next `grabFrame()` call throws. Error code `permission_revoked` sent. Orchestrator speaks *"My eyes just closed — it looks like camera access was revoked."*. Shell auto-flips toggle off. |
| Snapshot request timeout (>5s, no response) | Future is dropped. Orchestrator speaks *"Hmm, I couldn't get my eyes open in time. Want me to try again?"*. No DB write. |
| VLM HTTP call fails (Ollama down, 404 for model, network error) | Logged with traceback. `vlm.describe()` returns `""`. `VisionIntegration` detects empty → speaks *"My vision's a bit fuzzy right now — I can't quite make out what I'm seeing."*. No DB write. |
| VLM returns non-empty but gibberish (rare) | Still stored and spoken. Judged acceptable for v1. |
| `voice.reword()` fails (gemma2 timeout, empty response) | `spoken_text` falls back to `raw_description`. Observation is still stored with `spoken_text == raw_description`. Degraded but still useful. |
| Background fact extraction fails | Logged, silent. Observation row is already saved; extraction is best-effort. |
| `recall_observation` with no matches | Spoken *"I haven't seen anything matching that yet."* No overlay. |
| `recall_observation` with matches but stale session | The query hits the live DB, so it works across restarts. Nothing to handle. |
| `/reset-all` called | Observations table is wiped alongside all other tables. |

## 9. Testing strategy

| Target | Tests | Approach |
|---|---|---|
| `store.py` | ~6 | In-memory sqlite + inline schema. Create, list_recent, search_by_text, soft delete, `list_recent` excludes deleted, `search_by_text` is case-insensitive. |
| `vlm.py` | ~4 | Mock `httpx.AsyncClient.post` via `respx` or a small fake transport. Verify endpoint `/api/generate`, payload shape (`model`, `prompt`, `images`, `stream: false`), base64 passthrough, empty-on-error. |
| `voice.py` | ~3 | Fake `llm_chat` callable. Verify prompt contains raw description + user question. Empty LLM response → returns raw. LLM raises → returns raw. |
| `VisionIntegration` | ~6 | Mock store + vlm + voice. Happy path: `take_snapshot` returns spoken + observation_id. Missing image: returns clarification string. VLM empty: returns "fuzzy" fallback. `recall_observation` with matches. `recall_observation` empty. `recall_observation` noun extraction. |
| IntentRouter regression | ~4 | New triggers (`what do you see`, `what did you see`) route correctly. False positives excluded: *"can you see why I'm frustrated?"* (substring "see" + "why") must NOT route to vision. |
| End-to-end smoke | 1 | Async test: fake image_b64 → mocked VLM → mocked gemma2 → assert DB row contents + returned spoken text. |

Total: ~24 automated tests, sub-3s runtime. TDD per task.

**Manual checklist (visual shell, no JS harness):**

- Toggle on: camera permission prompts on first click.
- Toggle on: LED lights up.
- Toggle off: LED goes dark, `track.stop()` called.
- Reload page with toggle previously on: auto-enables without re-prompting.
- Revoke permission in browser URL bar → next snapshot fails gracefully with correct spoken response and toggle flips off.
- *"What do you see?"* → amber shimmer → spoken description within ~3s.
- Observation visible in DB via `sqlite3 config/samantha_memory.db "SELECT * FROM observations ORDER BY id DESC LIMIT 1;"`.
- *"What did you see earlier?"* returns the latest spoken text.
- *"When did you last see my plant?"* returns matching row (assuming a plant was in an earlier frame).

## 10. Acceptance criteria

1. Vision toggle appears below the Samantha nameplate in the top-right. Click toggles on/off. State persists across reloads via `localStorage`.
2. With toggle **on**, saying *"What do you see?"* triggers an amber shimmer, grabs a frame, and within ~3 seconds speaks a description in Samantha's voice grounded in the actual scene.
3. A row lands in the `observations` table containing both `raw_description` and `spoken_text`.
4. With toggle **off**, the same phrase triggers the "my eyes are closed" clarification. No DB write.
5. Camera permission denial or revocation is handled silently (no spoken error on denial; graceful explanation on revocation).
6. *"What did you see earlier?"* returns the most recent observation's `spoken_text`.
7. *"When did you last see my plant?"* matches observations whose `raw_description` contains "plant" and returns the most recent.
8. `VLM_MODEL` env var (default `moondream`) controls which Ollama model is used. Swapping to `llava:7b` or `qwen2.5vl:7b` requires only an env change and orchestrator restart.
9. Background fact extraction from `raw_description` adds entities to the existing `entities`/`facts` tables where appropriate.
10. All ~24 automated tests pass. Manual checklist passes.
11. `/reset-all` wipes the observations table alongside everything else.
12. No image data is written to disk. Frames are consumed in-memory and discarded.
