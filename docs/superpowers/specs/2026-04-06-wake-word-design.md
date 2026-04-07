# Wake Word — Design

**Date:** 2026-04-06
**Status:** Approved, ready for planning
**Scope:** Opt-in "Hey Samantha" wake word mode alongside existing push-to-talk, using browser-side VAD + existing Faster-Whisper STT for keyword matching. Zero new dependencies.

---

## 1. Goal

Let the user say "Hey Samantha" to get her attention without pressing the space bar. When wake mode is toggled on, the browser continuously monitors the mic for speech via VAD (Voice Activity Detection on the existing `micAnalyser`). On detected speech, it auto-records, sends to the existing STT service, and the orchestrator checks whether the transcript starts with a "samantha" wake prefix. If yes: strip the prefix and process the command. If no: discard silently. Push-to-talk remains available at all times as a reliable fallback.

## 2. Non-goals

- Sub-200ms latency. VAD+Whisper is ~1-2s. Acceptable for a desktop companion, not a smart speaker.
- Custom wake phrase configuration ("Hey Jarvis" instead of "Hey Samantha"). Hardcoded to "samantha" variants in v1.
- Noise cancellation beyond the browser's built-in `echoCancellation` + `noiseSuppression` audio constraints.
- New Docker services, ML libraries, or external API keys.
- Continuous partial-transcript display while speaking.
- Safari/Firefox support (Chrome-first, same as existing mic path).
- Sensitivity slider UI. Three hardcoded levels (low/medium/high) selectable via a CSS dropdown or attribute on the toggle. v1 ships with medium only; the code accepts a configurable threshold.

## 3. Architecture

### 3.1 No new files on the backend

The entire backend change is ~20 lines in the existing WS handler in `services/orchestrator/main.py`. No new Python modules.

### 3.2 File layout

```
services/orchestrator/
└── main.py                          + wake_mode dict on SamanthaState,
                                     + wake_mode WS event handler,
                                     + wake-prefix detection + stripping in
                                       audio_chunk and text_input handlers

services/orchestrator/tests/
└── test_wake_prefix.py              unit tests for prefix detection logic

services/visual-shell/
└── index.html                       + WakeWord IIFE module (VAD monitor,
                                       auto startRec/stopRec),
                                     + #wake-toggle button (inline SVG),
                                     + CSS for the toggle,
                                     + localStorage persistence
```

### 3.3 Data flow — "Hey Samantha, what's the weather?"

```
visual shell (wake mode ON, mic stream open from initAudio)
  └── WakeWord.monitor() runs on requestAnimationFrame
      └── micAnalyser.getByteTimeDomainData → compute RMS
      └── RMS > threshold for 300ms → speaking = true → startRec()
      └── MediaRecorder collects chunks
      └── RMS < threshold for 1500ms → speaking = false → stopRec()
      └── onstop encodes audio as base64
      └── ws.send({event: 'audio_chunk', audio: b64})

orchestrator WS handler (existing audio_chunk path)
  └── transcribe(audio_bytes) → "Hey Samantha, what's the weather?"
  └── wake_mode[ws] is True
  └── lower.startswith("hey samantha") → matched
  └── strip prefix → remainder = "what's the weather?"
  └── process_message("what's the weather?")
  └── result flows back normally: samantha_speaking → TTS → audio_ready
```

### 3.4 Wake-prefix detection

A pure function (testable independently):

```python
WAKE_PREFIXES = [
    "hey samantha",
    "samantha",
    "okay samantha",
    "ok samantha",
    "hi samantha",
]

def detect_wake_prefix(text: str) -> tuple[str | None, str]:
    """Check if `text` starts with a wake prefix.
    Returns (matched_prefix, remainder). If no match: (None, text).
    Remainder has leading punctuation/whitespace stripped."""
    lower = text.lower().strip()
    for prefix in WAKE_PREFIXES:
        if lower.startswith(prefix):
            remainder = text[len(prefix):].lstrip(" ,.-!?")
            return prefix, remainder
    return None, text
```

Longest prefix first in the list ensures "hey samantha" matches before "samantha" so the stripping is correct.

### 3.5 State sync

The browser sends `{event: "wake_mode", enabled: true|false}` over WS when the toggle flips. The orchestrator stores this per-connection:

```python
# In SamanthaState.__init__:
self.wake_mode: dict = {}  # ws → bool

# In WS handler:
elif data.get("event") == "wake_mode":
    state.wake_mode[ws] = data.get("enabled", False)
    logger.info(f"🎤 Wake mode {'on' if data.get('enabled') else 'off'}")
```

On WS disconnect, the entry is cleaned up (del from dict).

## 4. Browser-side VAD logic

### 4.1 WakeWord module

```js
const WakeWord = (() => {
  let enabled = false;
  let speaking = false;
  let silenceStart = 0;
  let speechStart = 0;
  let animFrame = null;

  const THRESHOLD = 15;    // RMS amplitude 0-128 from analyser byte data
  const SPEECH_MS = 300;   // speech must exceed threshold for this long before recording starts
  const SILENCE_MS = 1500; // silence must persist this long before recording stops

  function monitor() {
    if (!enabled || !micAnalyser) return;
    const data = new Uint8Array(micAnalyser.fftSize);
    micAnalyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / data.length) * 128;

    if (rms > THRESHOLD) {
      silenceStart = 0;
      if (!speaking) {
        if (!speechStart) speechStart = Date.now();
        if (Date.now() - speechStart > SPEECH_MS) {
          speaking = true;
          startRec();
        }
      }
    } else {
      speechStart = 0;
      if (speaking) {
        if (!silenceStart) silenceStart = Date.now();
        if (Date.now() - silenceStart > SILENCE_MS) {
          speaking = false;
          silenceStart = 0;
          stopRec();
        }
      }
    }
    animFrame = requestAnimationFrame(monitor);
  }

  async function enable() {
    if (enabled) return;
    if (!micAnalyser) await initAudio();
    if (!micAnalyser) return;
    enabled = true;
    speaking = false;
    speechStart = 0;
    silenceStart = 0;
    monitor();
    localStorage.setItem('samantha.wake.enabled', 'true');
    ws.send(JSON.stringify({event: 'wake_mode', enabled: true}));
  }

  function disable() {
    enabled = false;
    speaking = false;
    if (animFrame) { cancelAnimationFrame(animFrame); animFrame = null; }
    localStorage.setItem('samantha.wake.enabled', 'false');
    if (ws && ws.readyState === 1) {
      ws.send(JSON.stringify({event: 'wake_mode', enabled: false}));
    }
  }

  function isEnabled() { return enabled; }

  async function restoreFromStorage() {
    if (localStorage.getItem('samantha.wake.enabled') === 'true') {
      await enable();
    }
  }

  return { enable, disable, isEnabled, restoreFromStorage };
})();
```

### 4.2 Interaction with PTT

PTT (space bar) calls `startRec()` / `stopRec()` directly. Wake word's VAD also calls them. Both paths use the same `MediaRecorder` → `audio_chunk` → STT pipeline. The `recording` flag prevents double-starts: `startRec` checks `if (recording) return;`.

When wake mode is on AND the user presses space:
- Space takes priority. The user's keydown fires `startRec()` immediately (no VAD delay). When they release space, `stopRec()` fires. The audio is sent, transcribed, and processed WITHOUT wake-prefix filtering (because PTT is an intentional action — no "samantha" prefix needed).

This means the orchestrator needs to know whether the audio_chunk came from PTT or wake-VAD. Two options:
1. Send a flag: `{event: 'audio_chunk', audio: b64, source: 'wake'}` vs `source: 'ptt'`
2. Always check for wake prefix when `wake_mode[ws]` is True, even on PTT

**Choice: option 1.** PTT audio carries `source: 'ptt'` and skips prefix filtering. Wake audio carries `source: 'wake'` and requires the prefix. This prevents the annoyance of needing to say "Hey Samantha" after pressing space.

The existing PTT path already sends `{event: 'audio_chunk', audio: b64}` without a `source` field. We default missing `source` to `'ptt'` for backward compatibility.

### 4.3 Preventing feedback loops

When Samantha speaks (TTS audio plays through the speakers), the mic picks it up. With wake mode on, this could trigger a recording of her own voice → STT transcribes it → if she says "samantha" in her response, it wake-triggers again → infinite loop.

**Mitigation:** suppress the VAD monitor while Samantha is speaking. The visual shell already tracks speaking state via the `setMood('speaking')` / `setMood('idle')` calls. The monitor function checks:

```js
if (currentMood === 'speaking') { speechStart = 0; return; }
```

This is imperfect (there's a delay between TTS audio ending and the mood flipping back to idle), but the 1.5s silence window provides enough buffer. If the user talks over Samantha, PTT is always available as a guaranteed path.

## 5. Orchestrator-side changes

### 5.1 New state slot

```python
self.wake_mode: dict = {}  # WebSocket → bool, default False
```

### 5.2 WS handler additions

Three small additions to the existing WS handler's `while True` loop:

**1. Handle `wake_mode` event:**

```python
elif data.get("event") == "wake_mode":
    state.wake_mode[ws] = data.get("enabled", False)
    logger.info(f"🎤 Wake mode {'on' if data.get('enabled') else 'off'}")
```

**2. In the `audio_chunk` handler, after `user_text = await transcribe(audio_bytes)`:**

```python
source = data.get("source", "ptt")
if source == "wake" and state.wake_mode.get(ws, False):
    prefix, remainder = detect_wake_prefix(user_text)
    if prefix is None:
        logger.debug(f"🎤 Wake: discarded (no prefix): {user_text[:60]}")
        continue
    if not remainder:
        # Wake-only — warm acknowledgment
        ack = "Mm?"
        await ws.send_json({"event": "samantha_speaking", "text": ack, "mood": "calm"})
        asyncio.create_task(_send_audio(ws, {"text": ack, "tts_text": ack}))
        continue
    user_text = remainder
```

**3. Cleanup on disconnect:**

```python
except WebSocketDisconnect:
    state.clients.remove(ws)
    state.wake_mode.pop(ws, None)  # ← add this line
    ...
```

### 5.3 `detect_wake_prefix` function

A small pure function, either at the top of `main.py` or in a tiny `wake.py` module:

```python
WAKE_PREFIXES = [
    "hey samantha",
    "okay samantha",
    "ok samantha",
    "hi samantha",
    "samantha",
]

def detect_wake_prefix(text: str) -> tuple[str | None, str]:
    lower = text.lower().strip()
    for prefix in WAKE_PREFIXES:
        if lower.startswith(prefix):
            remainder = text[len(prefix):].lstrip(" ,.-!?")
            return prefix, remainder
    return None, text
```

Longest prefixes first so "hey samantha" matches before bare "samantha".

## 6. Visual shell — toggle button

### 6.1 Placement & styling

A new pill button to the LEFT of the timeline toggle. Position: `top: 3.8rem; right: 10rem`. Same size, shape, and styling pattern as vision + timeline toggles. Same `toggleGlow` keyframe when active.

### 6.2 Icon

Inline SVG matching the existing line-art language — a microphone with small radiating arcs (indicating "always listening"):

```html
<button id="wake-toggle" type="button" title="Wake word off — click to enable" aria-label="Toggle wake word">
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
    <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
    <line x1="12" y1="19" x2="12" y2="23"/>
    <path d="M1 8a15 15 0 0 0 4 3" opacity="0.5"/>
    <path d="M23 8a15 15 0 0 1-4 3" opacity="0.5"/>
  </svg>
</button>
```

### 6.3 localStorage persistence

Same pattern as vision and timeline: `samantha.wake.enabled`. On page load, `WakeWord.restoreFromStorage()` re-enables if previously on. On re-enable, it sends `{event: 'wake_mode', enabled: true}` over WS.

## 7. Error handling

| Situation | Behavior |
|---|---|
| Mic not initialized when wake toggled on | `enable()` calls `initAudio()` first. If mic init fails, toggle stays off. |
| VAD triggers on ambient noise (false positive) | Audio sent to STT, transcribed, no "samantha" prefix → discarded silently. User never sees it. |
| VAD misses quiet speech (false negative) | User falls back to space bar PTT. |
| STT returns empty transcript | Discarded, same as existing behavior. |
| "Samantha" appears mid-sentence ("tell samantha...") | `startswith` check fails → discarded correctly. |
| Samantha's own TTS triggers VAD | Monitor is suppressed during `speaking` mood state. 1.5s silence buffer provides additional protection. |
| User presses space while wake-VAD is recording | `startRec()` checks `if (recording) return;` → PTT keydown is a no-op. User releases space → `stopRec()` fires normally. The ongoing VAD-triggered recording completes. |
| User presses space while VAD is idle | Normal PTT path, audio sent with `source: 'ptt'`, no wake-prefix filtering. |
| WS disconnects while wake is on | `state.wake_mode.pop(ws, None)` in the disconnect handler cleans up. |

## 8. Testing

| Target | Tests | Approach |
|---|---|---|
| `detect_wake_prefix` | ~8 | Unit tests: "hey samantha what time is it" → ("hey samantha", "what time is it"); "samantha" alone → ("samantha", ""); "hey what's up" → (None, "hey what's up"); case insensitive; trailing punctuation stripped; "okay samantha, look" works; "tell samantha" → no match (not a prefix); empty string |
| WS wake_mode event | ~2 | Send `{event: 'wake_mode', enabled: true}`, verify `state.wake_mode[ws]` is True. Send false, verify it's False. |
| Audio chunk with source=wake + no prefix | ~1 | Verify the audio is discarded (no `process_message` call). |
| Audio chunk with source=wake + prefix + command | ~1 | Verify `process_message` receives the stripped remainder. |
| Audio chunk with source=wake + prefix only | ~1 | Verify "Mm?" acknowledgment is sent. |
| Audio chunk with source=ptt (or missing source) | ~1 | Verify no prefix filtering applied, full text passes through. |
| Visual shell | manual checklist | Toggle on/off, localStorage persistence, VAD triggers recording on speech, stops on silence, PTT still works, Samantha's voice doesn't re-trigger, feedback loop doesn't occur. |

~14 automated tests.

## 9. Acceptance criteria

1. New mic-with-arcs toggle in the header. Click enables wake mode. State persists via localStorage + syncs to orchestrator via WS.
2. With wake mode **on**, saying "Hey Samantha, what's the weather?" auto-records, sends to STT, orchestrator strips the prefix, processes "what's the weather?" normally.
3. Saying "Samantha" or "Hey Samantha" alone (no following command) → she responds with "Mm?" or a warm acknowledgment.
4. Saying something without "Samantha" at the start → silently discarded, no response.
5. Space bar PTT works regardless of wake mode — audio sent with `source: 'ptt'`, no prefix filtering.
6. With wake mode **off**, no continuous VAD monitoring happens; existing PTT behavior is unchanged.
7. Samantha's own TTS voice does not re-trigger the wake word (VAD suppressed during speaking state).
8. Toggle coexists visually with vision eye and timeline book in the header, using the shared `toggleGlow` animation.
9. All ~14 automated tests pass.
10. WS disconnect cleans up `wake_mode` state.
