# Reminders, Schedules & Lists — Design

**Date:** 2026-04-05
**Status:** Approved, ready for planning
**Scope:** Single feature covering reminders, schedule events, lists, the scheduler that fires them, the overlay-card delivery UI, and a small header polish in the visual shell.

---

## 1. Goal

Give Samantha the ability to hold things for the user: one-shot reminders ("remind me to call mom at 5"), calendar-style schedule events including simple recurring routines, and user-named lists with smart defaults. When a reminder or event is due, a soft chime plays and a translucent card slides into the visual shell from the right, auto-dismissing after ~25 seconds. When the user asks to see a list or schedule directly, the same card appears silently. The visual shell header also gets a legibility pass (bigger and darker date/day/time/Samantha).

## 2. Non-goals

- Editing reminders by voice after creation. User re-creates.
- Multi-user / per-user lists.
- External calendar sync (Google/iCal/CalDAV).
- iCal import/export.
- Complex recurrence (`every second Tuesday`, `monthly on the 15th`, `every 3 days`). The simple set covers real use; revisit if needed.
- Unsolicited speech when a reminder fires. Chime + card only. Samantha speaking first is a separate future feature.

## 3. Architecture

### 3.1 File layout

```
services/orchestrator/
├── integrations/
│   └── tasks/                          ← new
│       ├── __init__.py                 TasksIntegration: action surface
│       ├── store.py                    SQLite CRUD (pure, sync, no HTTP)
│       ├── parser.py                   dateparser wrapper + recurrence grammar
│       └── scheduler.py                asyncio loop: fires due items
├── intents/
│   └── __init__.py                     + keyword triggers for tasks
├── memory/
│   └── __init__.py                     + schema migration (3 new tables)
└── main.py                             + lifespan hook for scheduler,
                                         + `emit_overlay_card` helper,
                                         + chime generation on startup

services/visual-shell/
└── index.html                          + header polish (mockup B),
                                         + overlay card component,
                                         + WS handler for `overlay_card`,
                                         + chime player

config/
└── chime.wav                           generated on first run (numpy synth)
```

### 3.2 Module boundaries

- **`store.py`** — pure sqlite3 data layer. No async, no HTTP, no parsing. Testable against `:memory:`.
- **`parser.py`** — pure functions. `parse_when(text, now, tz) -> ParsedTime` and `parse_recurrence(text) -> (Recurrence | None, stripped_text)`. No I/O.
- **`scheduler.py`** — single `async def run(store, emit_overlay_card, poll_interval_s=15)`. Knows nothing about parsing or intents.
- **`integrations/tasks/__init__.py` (`TasksIntegration`)** — thin adapter that implements the existing `Integration` contract. Glues parser + store. Each action returns both a spoken string and an overlay payload, so the LLM response and the visual card come from one source.
- **Overlay component in `index.html`** — one self-contained JS module: `showOverlayCard(payload)`, internal queue, auto-dismiss, hover-pause, chime.

### 3.3 Data flow — user says "remind me to call mom at 5"

```
STT → orchestrator.main → IntentRouter keyword match → tasks.add_reminder
      → parser.parse_when("at 5") → trigger_at = today 17:00 local
      → store.create_reminder(...)
      → returns (spoken="Got it — I'll remind you to call mom at 5.",
                 overlay_payload={kind:"reminder", chime:false, ...})
      → orchestrator emits spoken → TTS
      → orchestrator broadcasts overlay_payload over WS → visual shell shows card

... time passes ...

scheduler.run tick (every 15s):
  store.reminders_due(now) → [reminder row]
  emit_overlay_card({kind:"reminder", chime:true, title:"Call mom", when:"now · 17:00", duration_ms:25000})
  store.mark_reminder_fired(id, now)

visual shell:
  chime plays via dedicated AudioContext
  card slides in from right
  progress bar runs 25s
  card fades out
```

## 4. Data model

### 4.0 Migration from legacy NotesIntegration reminders

The existing `services/orchestrator/integrations/notes_integration.py` already owns a `reminders` table with a different schema (`id, content, remind_at, completed, created_at`) and its own `set_reminder`, `check_reminders`, and `get_proactive_updates()` handlers. This legacy system is replaced:

- **Drop the legacy `reminders` table** on migration (`DROP TABLE IF EXISTS reminders;` runs *before* the new `CREATE TABLE`). There is no production data to preserve on this single-user dev machine.
- **Remove from `NotesIntegration`**: the `set_reminder` and `check_reminders` actions (from `get_actions()` and `execute()`), the `_set_reminder` and `_check_reminders` methods, and the `get_proactive_updates()` method in its entirety. The old `idx_reminders_pending` index is dropped with the table.
- **Keep in `NotesIntegration`**: `save_note`, `search_notes`, `remember`, `recall` — the notes and memories half is orthogonal and still useful.
- **Update `/reset-all`** in `main.py` to wipe `reminders` (new schema), `schedule_events`, and `list_items` alongside the other tables.

### 4.1 New tables

Three tables in the existing `config/samantha_memory.db` via idempotent `CREATE TABLE IF NOT EXISTS` migration on orchestrator startup, after the legacy drop above.

```sql
CREATE TABLE IF NOT EXISTS reminders (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  text          TEXT NOT NULL,
  trigger_at    TIMESTAMP NOT NULL,              -- UTC
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  fired_at      TIMESTAMP,                       -- NULL = pending
  cancelled_at  TIMESTAMP,                       -- NULL = active
  entity_id     INTEGER,                         -- soft FK → entities.id
  source_text   TEXT                             -- original utterance
);
CREATE INDEX IF NOT EXISTS idx_reminders_due
  ON reminders(trigger_at) WHERE fired_at IS NULL AND cancelled_at IS NULL;

CREATE TABLE IF NOT EXISTS schedule_events (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  title               TEXT NOT NULL,
  start_at            TIMESTAMP NOT NULL,         -- UTC; for recurring, next occurrence
  duration_min        INTEGER,
  recurrence          TEXT,                       -- NULL | 'daily' | 'weekdays' | 'weekly:mon'..'weekly:sun'
  notes               TEXT,
  entity_id           INTEGER,
  created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  heads_up_fired_at   TIMESTAMP,                  -- 10-min pre-warning fire
  fired_at            TIMESTAMP,                  -- start-time fire
  cancelled_at        TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_schedule_due
  ON schedule_events(start_at) WHERE cancelled_at IS NULL;

CREATE TABLE IF NOT EXISTS list_items (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  list_name   TEXT NOT NULL,
  text        TEXT NOT NULL,
  added_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  done_at     TIMESTAMP,                          -- NULL = active
  position    INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_list_active
  ON list_items(list_name, position) WHERE done_at IS NULL;
```

### Design notes

- **Soft delete** via `cancelled_at` / `done_at`. Enables "what did I remove last week?" later.
- **Entity link** via `entity_id` is a soft FK (SQLite FK enforcement is off in this DB, matching the existing `facts` table convention). TasksIntegration attempts to resolve the subject/object to an entity at creation; failure is silent.
- **Recurrence grammar** is a closed vocabulary: `daily`, `weekdays`, `weekly:<dayname-lowercase-3>`. Parser is ~30 lines. Extending later is easy; starting minimal is easier.
- **All timestamps UTC** in storage. Local timezone is applied at parse-time and at display-time only, controlled by `TZ` env var (default `Europe/Stockholm`). Tests pin `TZ=UTC`.
- **No FK enforcement** — consistent with current DB.

## 5. Intent routing & parsing

### 5.1 Keyword triggers (fast path, no LLM)

Added to `IntentRouter` alongside existing weather/news patterns. Order matters — more specific patterns come first.

| Pattern (case-insensitive) | Action |
|---|---|
| `remind me (to \|about )?<X>( at \|in \|tomorrow\|tonight\|…)<TIME>` | `tasks.add_reminder` |
| `every (morning\|evening\|day\|weekday\|monday…\|sunday) …<VERB>` | `tasks.add_schedule` (recurring) |
| `(meeting\|appointment\|call\|dentist\|…) with\|at <TIME>` | `tasks.add_schedule` (one-shot) |
| `add <X> to (the )?<N> list` / `put <X> on (my )?<N> list` | `tasks.add_to_list` (list = `N`) |
| `add <X> to (the )?(shopping\|groceries)` | `tasks.add_to_list` (list = `shopping`) |
| `(remind me to buy\|need to buy\|pick up) <X>` | `tasks.add_to_list` (list = `shopping`) |
| `(I should\|I need to\|todo:) <X>` | `tasks.add_to_list` (list = `todo`) |
| `(show me \|what's on )(my )?<N> list` | `tasks.show_list` |
| `what('s\| is) (next\|on my schedule\|today\|this week)` | `tasks.show_schedule` |
| `(cancel\|remove\|forget) (that\|the last) reminder` | `tasks.cancel_last_reminder` |

The keyword layer scores each pattern; an ambiguous score (< confidence threshold 0.7) falls through to the LLM classifier.

### 5.2 LLM fallback classifier

Constrained single-line output for trivial parsing:

```
Classify this message into exactly one line:
  CHAT
  REMINDER: <text> | <when>
  SCHEDULE: <title> | <when> | <recurrence or none>
  LIST_ADD: <list_name> | <item>
  LIST_SHOW: <list_name>
  SCHEDULE_SHOW
  CANCEL_LAST

Rules:
- <when> must be a natural-language time (e.g., "tomorrow 3pm", "in 20 minutes")
- <recurrence> is one of: daily, weekdays, weekly:mon..weekly:sun, or "none"
- If unsure, reply CHAT

Message: "<user text>"
```

`CHAT` response → falls through to normal conversation path. Any other response is parsed by a small dispatcher that calls the relevant `TasksIntegration` action.

### 5.3 Time parsing (`parser.py`)

- Primary engine: `dateparser.parse(text, settings={"TIMEZONE": TZ, "RETURN_AS_TIMEZONE_AWARE": True, "PREFER_DATES_FROM": "future"})`.
- Recurrence is matched *first* via regex against the phrase: `every (day|morning|evening|weekday|<day-of-week>)`. Match returns a `Recurrence` object and a "stripped" phrase with the `every ...` portion removed; dateparser then parses the time portion of the stripped phrase.
- Unparseable → raises `ParseError`. TasksIntegration catches it and returns a clarification question as the spoken response with **no DB write and no overlay**.

### 5.4 Action contracts

Each `TasksIntegration` action returns:

```python
@dataclass
class TaskActionResult:
    spoken: str                    # TTS says this
    overlay: OverlayPayload | None # broadcast over WS; None = no card
```

`OverlayPayload` fields match the WebSocket envelope in §6.2.

## 6. Scheduler & delivery

### 6.1 Scheduler loop (`scheduler.py`)

```python
async def run(store, emit_overlay_card, poll_interval_s: int = 15):
    while True:
        try:
            now = datetime.now(timezone.utc)

            for r in store.reminders_due(now):
                await emit_overlay_card(reminder_payload(r, chime=True))
                store.mark_reminder_fired(r.id, now)

            for e in store.schedule_heads_up_due(now, window_min=10):
                await emit_overlay_card(schedule_heads_up_payload(e, chime=True))
                store.mark_heads_up_fired(e.id, now)

            for e in store.schedule_due(now):
                await emit_overlay_card(schedule_payload(e, chime=True))
                if e.recurrence:
                    store.advance_recurrence(e.id, now)
                else:
                    store.mark_schedule_fired(e.id, now)
        except Exception:
            logger.exception("scheduler tick failed")
        await asyncio.sleep(poll_interval_s)
```

- Launched from FastAPI lifespan startup as a background task, cancelled on shutdown.
- 15s tick = max 15s drift. Acceptable for human-scale.
- Try/except per tick — a single bad row never kills the loop.
- `emit_overlay_card` is a closure injected by `main.py`; tests pass a spy.
- `advance_recurrence` loops forward until `start_at > now`, firing at most one card for the most recent missed occurrence (not one per day of downtime).

### 6.2 WebSocket envelope

New message type emitted by the orchestrator:

```json
{
  "type": "overlay_card",
  "kind": "reminder",
  "chime": true,
  "title": "Call mom",
  "when": "now · 17:00",
  "items": null,
  "highlight_index": null,
  "list_name": null,
  "duration_ms": 25000
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `type` | string | yes | always `"overlay_card"` |
| `kind` | enum | yes | `reminder` \| `schedule` \| `schedule_heads_up` \| `list` |
| `chime` | bool | yes | `true` only for scheduler-originated cards |
| `title` | string | yes | short display title |
| `when` | string \| null | no | pre-formatted display string ("now · 17:00", "in 12 min · 14:45", "Tuesday · 10:00") |
| `items` | string[] \| null | no | list variant only, full current list |
| `highlight_index` | int \| null | no | list variant only; index into `items` to highlight |
| `list_name` | string \| null | no | list variant only, displayed as kicker |
| `duration_ms` | int | yes | auto-dismiss timer, default 25000 |

### 6.3 Visual shell overlay component

Self-contained JS module inside `index.html`:

- `showOverlayCard(payload)` — if a card is already visible, animates out (fade + 8px slide) first, then animates new card in. Never two at once.
- Position: fixed, right `1.6rem`, top `5.5rem`, width `280px`. Consistent location so eye learns it.
- Styling: `background: rgba(254,245,237,0.58); backdrop-filter: blur(22px); border: 1px solid rgba(92,32,48,0.08); box-shadow: 0 20px 60px rgba(58,15,28,0.18);`. Cormorant Garamond title in `#3a0f1c`.
- Card anatomy: uppercase kicker (`kind` or `list_name`), serif title, `when` subtext, optional `<ul>` for list items with `.new` highlight class, progress bar.
- Progress bar runs for `duration_ms`, then auto-dismiss with 600ms fade.
- **Hover behavior (desktop):** `mouseenter` pauses the timer, `mouseleave` resumes and extends by 5s. No-op on touch.
- **Click dismisses immediately.**
- **Queue:** multiple payloads in the same tick queue FIFO with a 400ms gap.
- **Chime:** plays only when `chime: true`. Single `config/chime.wav` pre-loaded on page load into a dedicated `AudioContext` separate from the TTS pipeline. Cannot collide with Samantha's voice.

### 6.4 Chime generation & delivery to the browser

**Generation.** Generated once on orchestrator startup if the chime file is missing:

- ~800ms, two partials (C5 + E5 with 3:1 amplitude ratio), exponential decay, soft attack (5ms ramp-up).
- Synthesized via numpy, written via stdlib `wave`. 24kHz mono PCM16, -18 dBFS peak.
- Code lives in `services/orchestrator/integrations/tasks/chime.py` as `ensure_chime_exists(path)`, called from lifespan startup.

**Delivery.** The visual shell is a separate container and cannot read the orchestrator's config volume directly. The orchestrator exposes the chime via a new HTTP endpoint:

- `GET /static/chime.wav` on the orchestrator's existing FastAPI app.
- Served via `FastAPI.mount("/static", StaticFiles(directory="/app/static"))` where `ensure_chime_exists("/app/static/chime.wav")` writes the file during startup.
- Visual shell fetches it once on page load: `fetch("http://<orchestrator-host>:<port>/static/chime.wav").then(r => r.arrayBuffer()).then(buf => audioCtx.decodeAudioData(buf))` and holds the decoded `AudioBuffer` in memory.
- The visual shell already knows the orchestrator origin (it connects to `ws://${location.hostname}:8000/ws`). The chime URL is `http://${location.hostname}:8000/static/chime.wav`.

## 7. Header polish (mockup B)

Small CSS-only change in `index.html`. Replaces the existing `#clock` and `#identity` blocks.

- `#clock .time`: font-size `2.2rem`, weight `300`, color `#3a0f1c`, opacity `0.92`, letter-spacing `.02em`.
- `#clock .day` (new element): `.8rem`, weight `500`, color `#3a0f1c`, opacity `0.85`, letter-spacing `.22em`, uppercase, `margin-top: 6px`.
- `#clock .date`: `.75rem`, weight `400`, color `#5c2030`, opacity `0.75`, letter-spacing `.15em`, uppercase, `margin-top: 2px`.
- `#identity` (Samantha nameplate): font-size `1.35rem`, color `#3a0f1c`, opacity `0.85`, letter-spacing `.08em`, weight `400`, still italic Cormorant Garamond.
- Clock JS updated to also populate `.day` element (`toLocaleDateString(…, { weekday: 'long' })`).

Positions unchanged (clock top-left, identity top-right).

## 8. Error handling

| Situation | Behavior |
|---|---|
| Unparseable time in reminder/schedule | Spoken clarification question ("When should I remind you?"). No DB write. No card. |
| Empty reminder text | Spoken clarification ("What should I remind you about?"). No DB write. |
| Duplicate list item (case-insensitive, active only) | Append anyway. Kicker shows "Already on the list — added again". Not an error. |
| `cancel_last_reminder` with nothing to cancel | Spoken "There's nothing pending to cancel." |
| Scheduler tick exception | Logged with traceback. Loop continues next tick. |
| WebSocket disconnected when card fires | Emit silently drops. DB row still marked fired. User misses the card. Acceptable v1 trade-off. |
| Clock drift / lid sleep | On resume, overdue items fire back-to-back via the overlay queue. No suppression. |
| Recurring event with past `start_at` after downtime | `advance_recurrence` loops forward, fires once for the most recent missed occurrence only. |
| List name collision with built-ins | No reservation. "shopping2" and "shopping" are distinct lists. |

## 9. Testing strategy

| Target | Tests | Approach |
|---|---|---|
| `store.py` | ~15 | In-memory sqlite. CRUD, soft delete, `reminders_due` window, `schedule_heads_up_due`, `advance_recurrence`, duplicate detection. |
| `parser.py` | ~12 | `freezegun` for frozen `now`. Cases: "5pm", "tomorrow", "in 20 min", "every weekday at 8", "every sunday evening", "next Friday afternoon", unparseable, empty. |
| `scheduler.py` | ~5 | Fake clock + spy `emit_overlay_card`. Due item fires once; recurring advances; exception in one tick doesn't kill the loop; heads-up fires separately from start-time. |
| `TasksIntegration` | ~8 | Mocked store + parser. Each action returns `(spoken, overlay)`; error paths return clarification questions with `overlay=None`. |
| `IntentRouter` new patterns | ~6 | Regression: new patterns don't get swallowed by existing `CHAT_SIGNALS`; ambiguous cases fall through to LLM. |
| End-to-end smoke | 1 | Async: create reminder → fake clock advance → scheduler tick → capture emitted envelope. No FastAPI, no real WS. |
| Visual shell | manual checklist | Card renders, chime plays, auto-dismiss, hover pause, queue FIFO, click dismiss. No JS test harness in repo; out of scope. |

Total: ~47 automated tests + 1 integration, all < 5s. TDD per task.

## 10. Acceptance criteria

1. Visual shell header shows date/day/time/Samantha at the enlarged sizes, darker burgundy per mockup B. Legible from 2m away.
2. "Remind me to call mom at 5" creates a reminder, confirms verbally, and at 17:00 plays chime + slides in a translucent card for 25s.
3. "Add milk to the shopping list" appends to the `shopping` list and shows a silent card with the full list, "milk" highlighted.
4. "Meeting with Jussi Friday at 3" creates a schedule event; at Friday 14:50 a heads-up card fires; at 15:00 the start-time card fires.
5. "Every weekday at 8, remind me to take vitamins" creates a recurring event that fires Mon–Fri at 08:00 and auto-advances.
6. "What's on my shopping list?" / "What's next today?" returns a silent card on demand.
7. "Cancel that" cancels the most recent reminder.
8. All listed automated tests pass.
9. Soft-deleted rows are preserved in the DB (not removed).
10. Orchestrator restart does not double-fire already-fired reminders or lose pending ones.
