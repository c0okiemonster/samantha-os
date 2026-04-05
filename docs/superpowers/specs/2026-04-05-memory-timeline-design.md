# Memory Timeline UI — Design

**Date:** 2026-04-05
**Status:** Approved, ready for planning
**Scope:** Full-screen overlay that renders six types of Samantha's stored knowledge as a chronological timeline, with filter chips, day grouping, hover-to-delete, and undo.

---

## 1. Goal

Give the user a single surface to browse, audit, and prune what Samantha has learned. Equal parts memorybook (pretty, scrollable, enjoyable) and audit tool (spot the hallucinated facts that leak in through edge cases and delete them). One click or one keystroke opens the panel; one hover-click forgets anything that shouldn't be there.

## 2. Non-goals

- Editing entries in place. Only delete in v1; the user rewrites by talking to her again.
- Search within the timeline. The existing `/memory/search` endpoint stays separate; a search box in the timeline is a v2 nice-to-have.
- Hard deletion of soft-deleted rows. Rows live on disk forever in v1 with `deleted_at` set; a future cleanup task can purge past a retention window.
- Surfacing reminders, schedule events, or list items — those have their own overlay-card UIs already.
- Voice triggers ("show me what you remember"). Keyboard + click are sufficient for v1.
- Multi-user anything.

## 3. Architecture

### 3.1 File layout

```
services/orchestrator/
├── memory/
│   ├── __init__.py                  + ALTER TABLE migration adding deleted_at
│   │                                  to facts, entities, episodes, mood_log,
│   │                                  news_digests (observations already has it)
│   └── timeline.py                  NEW: pure functions — build_timeline,
│                                    soft_delete_entry, restore_entry
├── main.py                          + GET  /memory/timeline
│                                    + DELETE /memory/entry/{entry_type}/{entry_id}
│                                    + POST   /memory/entry/{entry_type}/{entry_id}/restore
└── tests/memory/
    ├── __init__.py                  (empty package marker)
    ├── test_timeline_query.py       build_timeline against in-memory sqlite
    ├── test_timeline_delete.py      soft_delete_entry across all 6 types
    └── test_timeline_migration.py   ALTER TABLE idempotency

services/visual-shell/
└── index.html                       + timeline toggle icon next to vision eye,
                                     + #timeline-panel overlay markup + CSS,
                                     + Timeline IIFE module
                                     + keyboard shortcut Cmd+K / Ctrl+K
```

### 3.2 Module boundaries

- **`memory/timeline.py`** — pure sync functions operating on a `sqlite3.Connection`. Three functions:
  - `build_timeline(conn, types: set[str], limit: int, before: Optional[datetime]) -> TimelineResult` — runs one `SELECT` per requested type, normalizes rows into the unified entry dict, merge-sorts by `ts DESC`, applies `limit+1` trimming, returns entries plus pagination cursor.
  - `soft_delete_entry(conn, entry_type: str, entry_id: int) -> bool` — sets `deleted_at = CURRENT_TIMESTAMP`. Raises `ValueError` for unknown type. Returns `True` if a row was affected, `False` if not (missing row is a no-op success).
  - `restore_entry(conn, entry_type: str, entry_id: int) -> bool` — sets `deleted_at = NULL`. Same semantics.
- **`main.py` endpoints** — thin HTTP adapters. Zero business logic; parse path/query, call `timeline.py`, return JSON. All three endpoints guard on `state.memory is not None`.
- **Visual shell `Timeline` IIFE** — self-contained JS module: `open()`, `close()`, `toggle()`, `load(types, before)`, `render(entries)`, `deleteEntry(entry)`, `restoreEntry(entry)`, `showUndo(entry)`. Internal state: `enabled` (bool), `selectedTypes` (set), `entries` (array), `nextBefore` (timestamp or null), `pendingDeletes` (map of entry_id → timeout handle).

### 3.3 Data flow — open + render + delete

```
user presses Cmd+K (or clicks 📖)
  → Timeline.toggle() → Timeline.open()
  → panel element fades in (CSS transition)
  → fetch('/memory/timeline?types=fact,observation,episode,mood&limit=100')
  → orchestrator builds timeline, returns JSON
  → Timeline.render(entries)
  → entries appear in day-grouped buckets, newest first

user hovers an entry
  → × icon appears via :hover CSS

user clicks ×
  → entry fades out (opacity 0, 0.3s)
  → fetch('/memory/entry/fact/17', { method: 'DELETE' })
  → 204 No Content
  → undo toast appears bottom-center for 5s
  → setTimeout(() => removeEntryFromArray(entry), 5000)

if user clicks undo within 5s:
  → fetch('/memory/entry/fact/17/restore', { method: 'POST' })
  → entry fades back in
  → toast disappears
  → pendingDeletes timeout is cancelled
```

### 3.4 Pagination

Cursor-based via `before`:

```
GET /memory/timeline?types=fact,observation&limit=100
  → returns { entries: [...100 newest...], has_more: true, next_before: "2026-04-01T..." }

GET /memory/timeline?types=fact,observation&limit=100&before=2026-04-01T...
  → returns the next 100 older entries
```

Frontend triggers the next page automatically when the scroll position is within 200px of the bottom. State tracks `nextBefore` and `loading` (debounce to avoid duplicate requests).

## 4. Data model

### 4.1 Migration

One block added to `ConversationMemory._create_tables` after the existing migrations:

```python
# Timeline: add deleted_at to tables that don't have it
for table in ("facts", "entities", "episodes", "mood_log", "news_digests"):
    try:
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN deleted_at TIMESTAMP")
        self.conn.commit()
    except Exception:
        pass  # column already exists
```

`observations` already has `deleted_at` from the vision feature. `reminders`, `schedule_events`, `list_items` have their own soft-delete columns (`cancelled_at`, `done_at`) but they are not timelined so they don't need `deleted_at`.

### 4.2 Unified entry shape

Every row from every source table is normalized into this dict:

```python
{
    "id": "observation:42",        # "<type>:<numeric_id>"
    "type": "observation",          # one of: fact, entity, observation, episode, mood, news
    "ts": "2026-04-05T18:49:56+00:00",  # ISO 8601 UTC, used for sorting
    "title": "What she saw",        # short uppercase-ish label
    "body": "a small potted plant on a wooden windowsill",  # main display text
    "meta": {                        # type-specific fields, dict of primitives
        "spoken_text": "Mmm, I see your plant.",
        "user_trigger": "what do you see?"
    }
}
```

### 4.3 Type-specific projections

Each of the six types gets a mapping from table columns to the unified shape. All queries filter `WHERE deleted_at IS NULL`.

| Type | Table | `ts` source | `title` | `body` | `meta` |
|---|---|---|---|---|---|
| `fact` | `facts` | `learned_at` | `{subject} · {category} · {key}` | `value` | `{subject, category, confidence, source}` |
| `entity` | `entities` | `first_mentioned` | `{type}{" · " + relation if relation else ""}` | `name` | `{aliases, last_mentioned}` |
| `observation` | `observations` | `created_at` | `"What she saw"` | `raw_description` | `{spoken_text, user_trigger}` |
| `episode` | `episodes` | `ended_at` | `{topics_truncated}` | `summary` | `{mood_arc, message_count, unresolved_threads}` |
| `mood` | `mood_log` | `timestamp` | `"{user_mood} → {samantha_mood}"` | `trigger or ""` | `{sentiment, intensity, note}` |
| `news` | `news_digests` | `created_at` | `"News digest"` | `summary` | `{sentiment, reaction, sources}` |

All title/body/meta builders live in `timeline.py` as small helper functions, one per type.

### 4.4 Query structure

`build_timeline(conn, types, limit, before=None)` runs N queries (one per requested type) in the shape:

```sql
SELECT id, <other_cols>
FROM <table>
WHERE deleted_at IS NULL
  AND (? IS NULL OR <ts_col> < ?)
ORDER BY <ts_col> DESC
LIMIT ?
```

Bind `before` twice (NULL on first page), and `limit+1` as the limit. Collect results from each query, map to unified dicts via the per-type projection, merge-sort by `ts` desc, take first `limit`, set `has_more = len > limit` and `next_before = last.ts if has_more else None`.

6 queries × ~100 rows each is microseconds on SQLite with existing indexes. No special tuning needed.

## 5. HTTP endpoints

All new endpoints live in `main.py` alongside the existing `/memory` endpoints.

### 5.1 `GET /memory/timeline`

Query params:
- `types` (comma-separated, required, at least one) — e.g. `fact,observation,episode,mood`
- `limit` (integer, optional, default `100`, max `500`)
- `before` (ISO 8601 timestamp, optional) — cursor for pagination

Response `200`:
```json
{
  "entries": [ { "id": "fact:17", "type": "fact", "ts": "...", "title": "...", "body": "...", "meta": {...} }, ... ],
  "has_more": true,
  "next_before": "2026-04-05T10:00:00+00:00"
}
```

Response `400` on invalid type name or malformed `before`.

### 5.2 `DELETE /memory/entry/{entry_type}/{entry_id}`

Path params:
- `entry_type` — one of the six types
- `entry_id` — integer row id

Response `204 No Content` on success (including the idempotent case where the row doesn't exist or is already soft-deleted).
Response `400` on unknown type.

### 5.3 `POST /memory/entry/{entry_type}/{entry_id}/restore`

Path params: same as DELETE.
Response `204 No Content` on success or idempotent no-op.
Response `400` on unknown type.

## 6. Visual shell — panel & UI

### 6.1 Toggle placement & styling

A new pill button mirroring `#vision-toggle`, placed to the LEFT of the vision toggle:

- `position: fixed; top: 3.8rem; right: 6rem;` (2.4rem width + ~1rem gap from vision toggle at `right: 2rem`)
- Same size, same cream frosted-glass background, same border/padding conventions
- Tooltip off: *"Memory — click to open"*, on: *"Memory — click to close"*
- `.active` class mirrors the vision glow exactly (reuse the same `visionGlow` keyframes — rename it to `toggleGlow` so it can be shared, and apply it on both `.active` states)

**Icon: inline SVG in the existing line-art style** (matching `#btn-mic` and `#btn-text` — see lines 499-510 of `index.html`). Same `viewBox="0 0 24 24"`, `stroke="currentColor"`, `stroke-width="1.5"`, `stroke-linecap="round"`, `stroke-linejoin="round"`, no fill. The emoji glyphs are **NOT used** — they break the visual language.

**Memory toggle icon** — a simple clock-with-book or layered-pages glyph. Recommendation: three stacked horizontal lines with a circle at one end (a timeline motif):

```html
<button id="timeline-toggle" type="button" title="Memory — click to open" aria-label="Toggle memory">
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="5" cy="6" r="1.5"/>
    <line x1="9" y1="6" x2="20" y2="6"/>
    <circle cx="5" cy="12" r="1.5"/>
    <line x1="9" y1="12" x2="20" y2="12"/>
    <circle cx="5" cy="18" r="1.5"/>
    <line x1="9" y1="18" x2="20" y2="18"/>
  </svg>
</button>
```

This reads as a timeline / list of moments and matches the mic/text icons tonally.

**Vision toggle icon** — same-style open-eye line art (replacing the 👁 emoji currently in production):

```html
<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
  <circle cx="12" cy="12" r="3"/>
</svg>
```

The vision icon swap is a small fix to the already-shipped vision feature and is done at the top of the implementation plan, before the memory timeline tasks start.

### 6.2 Panel markup

```html
<div id="timeline-panel" role="dialog" aria-label="Samantha's Memory">
  <div class="timeline-inner">
    <header class="timeline-header">
      <h2>Samantha's Memory</h2>
      <button class="timeline-close" aria-label="Close">×</button>
    </header>
    <div class="timeline-filters">
      <button class="chip active" data-type="fact">Facts</button>
      <button class="chip active" data-type="observation">Observations</button>
      <button class="chip active" data-type="episode">Episodes</button>
      <button class="chip active" data-type="mood">Moods</button>
      <button class="chip" data-type="entity">Entities</button>
      <button class="chip" data-type="news">News</button>
    </div>
    <div class="timeline-scroll">
      <!-- day buckets rendered by JS -->
    </div>
  </div>
  <div class="timeline-toast"></div>
</div>
```

### 6.3 CSS styling

- `#timeline-panel` — `position: fixed; inset: 0; z-index: 60; opacity: 0; pointer-events: none; background: rgba(254,245,237,0.94); backdrop-filter: blur(30px);` — fade in via `opacity: 1; pointer-events: auto;` on `.visible` class
- `.timeline-inner` — `max-width: 720px; margin: 5rem auto; padding: 2rem 2.5rem;`
- `.timeline-header h2` — Cormorant Garamond serif, 1.8rem, italic, burgundy
- `.timeline-close` — small × button, top-right of the inner container
- `.timeline-filters` — horizontal flex, small gap, Cormorant Garamond chips with burgundy text, translucent cream fill, `.active` = solid burgundy fill with cream text
- `.day-bucket` — margin between buckets, small uppercase Outfit kicker header (TODAY, YESTERDAY, THIS WEEK, LAST WEEK, EARLIER)
- `.entry` — two-line compact row. First line: small Outfit uppercase kicker (6 chars type code: `FACT`, `OBS`, `EP`, `MOOD`, `ENT`, `NEWS`) + title in Cormorant. Second line: body in Cormorant, slightly darker. Hover: background brightens, `.entry-delete` becomes visible
- `.entry-delete` — `opacity: 0` by default, `opacity: 0.6` on entry hover, small × button at the right, positioned absolutely
- `.timeline-toast` — `position: fixed; bottom: 2rem; left: 50%; transform: translateX(-50%);` — fade in/out, cream background, burgundy text, "Forgot this. Undo?" with an undo link

### 6.4 Day grouping logic

```js
function bucketFor(ts) {
  const d = new Date(ts);
  const now = new Date();
  const msPerDay = 86400000;
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return 'Today';
  const yesterday = new Date(now - msPerDay);
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  if (now - d < 7 * msPerDay) return 'This week';
  if (now - d < 14 * msPerDay) return 'Last week';
  return 'Earlier';
}
```

Bucket order in the render: Today → Yesterday → This week → Last week → Earlier. Within each bucket, entries are already sorted desc by `ts` from the API response.

### 6.5 Keyboard shortcut

Document-level `keydown` listener:

```js
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
    e.preventDefault();
    Timeline.toggle();
  }
  if (e.key === 'Escape' && Timeline.isOpen()) {
    e.preventDefault();
    Timeline.close();
  }
});
```

**Cmd+M is taken by macOS** (window minimize), so we use **Cmd+K / Ctrl+K** which is conventionally a command palette / browse shortcut and unused by Chrome, Safari, or Firefox.

### 6.6 Delete + undo flow

```js
function deleteEntry(entry) {
  const row = getRowEl(entry.id);
  row.style.opacity = '0';
  fetch(`/memory/entry/${entry.type}/${numericId(entry.id)}`, { method: 'DELETE' })
    .catch(() => {
      row.style.opacity = '1';
      showError('Couldn't forget that — try again');
    });
  showUndo(entry);
  const handle = setTimeout(() => {
    removeFromArray(entry);
    row.remove();
    pendingDeletes.delete(entry.id);
  }, 5000);
  pendingDeletes.set(entry.id, handle);
}

function undoDelete(entry) {
  const handle = pendingDeletes.get(entry.id);
  if (handle) clearTimeout(handle);
  pendingDeletes.delete(entry.id);
  fetch(`/memory/entry/${entry.type}/${numericId(entry.id)}/restore`, { method: 'POST' });
  const row = getRowEl(entry.id);
  if (row) row.style.opacity = '1';
  hideToast();
}
```

## 7. Error handling

| Situation | Behavior |
|---|---|
| `/memory/timeline` returns 500 | Panel shows centered *"Something slipped. Close and try again."* |
| `/memory/timeline` returns empty array on first page | Panel shows empty state *"Nothing here yet. Keep talking to me."* |
| `DELETE` fails (network, 500) | Entry fades back in, small inline error *"Couldn't forget that — try again"* |
| `DELETE` returns 400 (unknown type) | Frontend bug surfaces as console error; user sees *"That didn't work — refresh?"* |
| `POST restore` fails | Toast updates: *"Too late — it's gone"*; entry stays removed |
| Panel opened while orchestrator is down | Fetch fails, panel shows *"Can't reach memory right now"* |
| Rapid toggle spam (open/close/open) | CSS transition handles it; `load()` is guarded by `if (loading) return` |
| Filter chips with zero selected types | Disable the fetch; show empty state *"Pick a filter above"* |
| Scroll reaches bottom but `has_more` is false | No more fetches; small italic *"That's everything."* footer |
| ALTER TABLE migration fails (column exists) | Swallowed silently, same pattern as existing migrations |
| Old DB without `deleted_at` on new tables | Migration runs on first boot, backfills the column, no data loss |

## 8. Testing strategy

| Target | Tests | Approach |
|---|---|---|
| `timeline.py` migration | ~1 | Run `_create_tables` twice against a fresh in-memory DB, verify columns exist both times, no exception. |
| `timeline.py` `build_timeline` | ~8 | Seed rows across all 6 tables, verify: type filtering, sort order (merge across types), `deleted_at IS NULL` exclusion, limit trimming, `has_more` flag, cursor pagination via `before`, empty result, single-type query. |
| `timeline.py` `soft_delete_entry` | ~6 | Each of 6 types: delete a row → `build_timeline` excludes it. Invalid type → `ValueError`. Non-existent id → `False` return, no error. Idempotent: delete twice is safe. |
| `timeline.py` `restore_entry` | ~3 | Restore after delete → row reappears. Restore non-deleted row → no-op. Invalid type → `ValueError`. |
| `/memory/timeline` endpoint | ~4 | FastAPI TestClient. Happy path, filter query, pagination query, invalid type returns 400. |
| `DELETE /memory/entry/{type}/{id}` | ~3 | Happy path 204, invalid type 400, missing id 204 (idempotent). |
| `POST /memory/entry/{type}/{id}/restore` | ~2 | Happy path 204, non-deleted row idempotent 204. |
| Visual shell | manual checklist | Toggle opens/closes, Cmd+K toggles, Escape closes, filter chips toggle, scroll loads more, hover reveals ×, delete fades entry, undo restores within 5s, undo ignored after 5s, empty state renders. |

~27 automated tests. Under 3s. TDD per task.

## 9. Acceptance criteria

1. New **📖** toggle appears in the top-right, to the left of the vision eye. Click opens the Memory panel. Escape or Cmd+K closes it.
2. Panel renders entries from `facts`, `observations`, `episodes`, `mood_log` by default. Entities and News chips are available but off.
3. Entries are grouped into `Today / Yesterday / This week / Last week / Earlier` buckets, newest first within each bucket.
4. Filter chips toggle which types are included; the panel re-fetches when a chip changes.
5. Hovering an entry reveals a × delete icon. Click triggers a soft delete + 5-second undo toast.
6. Undo within 5s restores the entry. After 5s, the row stays `deleted_at != NULL` in the DB.
7. Scrolling near the bottom auto-loads the next page until the DB is exhausted. Footer shows *"That's everything."* when done.
8. Empty state shows a friendly message when filters match zero rows or when nothing has been learned yet.
9. Hallucinated facts from earlier testing sessions can be surfaced and deleted. This is the primary audit success criterion.
10. All ~27 automated tests pass.
11. `GET /memory/timeline?types=fact,observation,episode,mood&limit=100` returns the expected JSON shape in a live docker stack.
12. `DELETE /memory/entry/fact/17` then `GET /memory/timeline?types=fact` confirms the fact no longer appears.
