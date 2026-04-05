# Vision Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Samantha an on-demand "look at me" capability — webcam frame → moondream VLM → gemma2-voiced response → persistent observation memory — controlled by a user-toggled vision panel in the visual shell.

**Architecture:** New `VisionIntegration` under `services/orchestrator/integrations/vision/` with pure `store.py` (SQLite CRUD for observations), `vlm.py` (Ollama HTTP client for moondream), `voice.py` (gemma2 reword helper), and a thin `__init__.py` adapter implementing the existing `BaseIntegration` contract. The `take_snapshot` intent triggers a WebSocket round-trip (`request_snapshot` → browser grabs frame → `snapshot` response) resolved via an `asyncio.Future` map on `SamanthaState`. Visual shell gains a `Vision` module wrapping `getUserMedia`, a toggle button below the Samantha nameplate, and a small amber "looking" shimmer during the VLM round-trip.

**Tech Stack:** Python 3 + FastAPI (existing), `sqlite3` stdlib, `httpx` (existing) for Ollama calls, stdlib `secrets` for request IDs, `pytest` + `pytest-asyncio` + `freezegun` (existing dev deps), vanilla JS + Web APIs (`getUserMedia`, `<canvas>`, `localStorage`) on the visual shell. Default VLM: `moondream` via host Ollama at `host.docker.internal:11434`.

**Spec:** `docs/superpowers/specs/2026-04-05-vision-snapshot-design.md`

**Prerequisite (user machine, one-time):** `ollama pull moondream`. The plan does NOT pull the model automatically; task 12's end-to-end smoke test uses mocks so CI and unit tests don't need a real VLM.

---

## Conventions

- **Test runner:** `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest <args>`
- **Tests live at** `services/orchestrator/tests/vision/test_<thing>.py`
- **Branch:** all work lands on `feat/vision-snapshot` (already created from main; spec already committed there).
- **All timestamps UTC** in storage, local time only at display/log time.
- **Commits:** conventional prefixes — `feat:`, `fix:`, `test:`, `chore:`, `docs:`.

---

## File Structure

**Create:**

```
services/orchestrator/integrations/vision/__init__.py        VisionIntegration adapter
services/orchestrator/integrations/vision/models.py          dataclasses + SnapshotError
services/orchestrator/integrations/vision/store.py           observations CRUD + SCHEMA_SQL
services/orchestrator/integrations/vision/vlm.py             moondream HTTP client
services/orchestrator/integrations/vision/voice.py           gemma2 reword helper
services/orchestrator/tests/vision/__init__.py               (empty package marker)
services/orchestrator/tests/vision/test_models.py
services/orchestrator/tests/vision/test_store.py
services/orchestrator/tests/vision/test_vlm.py
services/orchestrator/tests/vision/test_voice.py
services/orchestrator/tests/vision/test_integration_snapshot.py
services/orchestrator/tests/vision/test_integration_recall.py
services/orchestrator/tests/vision/test_smoke_e2e.py
```

**Modify:**

```
docker-compose.yml                                           + VLM_MODEL, + VLM_HOST env
services/orchestrator/memory/__init__.py                     + observations table
services/orchestrator/main.py                                register VisionIntegration,
                                                             pending_snapshots dict,
                                                             snapshot WS handler,
                                                             vision round-trip in process_message,
                                                             /reset-all wipes observations
services/visual-shell/index.html                             Vision module, toggle UI,
                                                             request_snapshot handler,
                                                             "looking" mood shimmer,
                                                             localStorage persistence
```

---

## Task 0: Add VLM env vars to docker-compose

**Files:**
- Modify: `docker-compose.yml`

Pure config. No tests.

- [ ] **Step 1: Add env vars**

Edit `docker-compose.yml`. Find the orchestrator service's `environment:` block (currently contains `OLLAMA_HOST`, `OLLAMA_MODEL`, `EMBED_MODEL`, `TZ`, etc.) and append:

```yaml
      - VLM_MODEL=${VLM_MODEL:-moondream}
      - VLM_HOST=${VLM_HOST:-host.docker.internal:11434}
      - VLM_TIMEOUT_S=${VLM_TIMEOUT_S:-15}
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "chore(compose): add VLM_MODEL/VLM_HOST/VLM_TIMEOUT_S env for vision snapshot"
```

---

## Task 1: Models

**Files:**
- Create: `services/orchestrator/integrations/vision/__init__.py` (empty package marker for now)
- Create: `services/orchestrator/integrations/vision/models.py`
- Create: `services/orchestrator/tests/vision/__init__.py` (empty)
- Create: `services/orchestrator/tests/vision/test_models.py`

- [ ] **Step 1: Create empty package markers**

Create `services/orchestrator/integrations/vision/__init__.py` with content: (empty file)
Create `services/orchestrator/tests/vision/__init__.py` with content: (empty file)

- [ ] **Step 2: Write the failing test**

Create `services/orchestrator/tests/vision/test_models.py`:

```python
from datetime import datetime, timezone

from integrations.vision.models import (
    Observation,
    SnapshotResult,
    SnapshotError,
)


def test_observation_defaults():
    o = Observation(
        id=None,
        raw_description="a cup of coffee on a desk",
        spoken_text="Mmm, I see your coffee there.",
        user_trigger="what do you see?",
    )
    assert o.id is None
    assert o.raw_description == "a cup of coffee on a desk"
    assert o.spoken_text.startswith("Mmm")
    assert o.created_at is None
    assert o.deleted_at is None


def test_snapshot_result_holds_spoken_and_id():
    r = SnapshotResult(spoken="I see you.", observation_id=7, overlay=None)
    assert r.spoken == "I see you."
    assert r.observation_id == 7
    assert r.overlay is None


def test_snapshot_error_is_exception():
    assert issubclass(SnapshotError, Exception)
    err = SnapshotError("vision_off")
    assert str(err) == "vision_off"
```

- [ ] **Step 3: Run — expect ImportError**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_models.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.vision.models'`

- [ ] **Step 4: Write models.py**

Create `services/orchestrator/integrations/vision/models.py`:

```python
"""Dataclasses for the vision integration. Pure data, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


class SnapshotError(Exception):
    """Raised by the snapshot round-trip when the shell returns an error
    code instead of an image (vision_off, permission_revoked, grab_failed)."""


@dataclass
class Observation:
    id: Optional[int]
    raw_description: str
    spoken_text: str
    user_trigger: Optional[str] = None
    created_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None


@dataclass
class SnapshotResult:
    spoken: str
    observation_id: Optional[int]
    overlay: Optional[Any]  # kept for symmetry with TaskActionResult
```

- [ ] **Step 5: Run — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_models.py -v`
Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add services/orchestrator/integrations/vision/__init__.py \
        services/orchestrator/integrations/vision/models.py \
        services/orchestrator/tests/vision/__init__.py \
        services/orchestrator/tests/vision/test_models.py
git commit -m "feat(vision): add models (Observation, SnapshotResult, SnapshotError)"
```

---

## Task 2: Schema migration

**Files:**
- Modify: `services/orchestrator/memory/__init__.py`
- Create: `services/orchestrator/tests/vision/test_schema.py`

Adds the `observations` table to `ConversationMemory._create_tables` alongside the existing `reminders`, `schedule_events`, `list_items`, `facts`, etc.

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/vision/test_schema.py`:

```python
from memory import ConversationMemory


def test_observations_table_exists(tmp_path):
    db = tmp_path / "m.db"
    m = ConversationMemory(db_path=str(db))
    rows = m.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "observations" in names


def test_observations_columns(tmp_path):
    db = tmp_path / "m.db"
    m = ConversationMemory(db_path=str(db))
    cols = {r[1] for r in m.conn.execute("PRAGMA table_info(observations)").fetchall()}
    for expected in [
        "id", "raw_description", "spoken_text", "user_trigger",
        "created_at", "deleted_at",
    ]:
        assert expected in cols, f"missing column: {expected}"


def test_observations_index(tmp_path):
    db = tmp_path / "m.db"
    m = ConversationMemory(db_path=str(db))
    rows = m.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='observations'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert "idx_observations_time" in names
```

- [ ] **Step 2: Run — expect fail**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_schema.py -v`
Expected: 3 failures — table doesn't exist yet.

- [ ] **Step 3: Add to memory/__init__.py**

Find `ConversationMemory._create_tables`. Inside the existing `self.conn.executescript("""...""")` triple-quoted SQL block (before the closing `"""`), append:

```sql
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
```

- [ ] **Step 4: Run — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_schema.py -v`
Expected: `3 passed`

Also run the full suite to catch regressions:
Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/ -v`
Expected: all previously passing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/memory/__init__.py \
        services/orchestrator/tests/vision/test_schema.py
git commit -m "feat(memory): add observations table for vision snapshots"
```

---

## Task 3: Store — observations CRUD

**Files:**
- Create: `services/orchestrator/integrations/vision/store.py`
- Create: `services/orchestrator/tests/vision/test_store.py`

Pure sqlite3 layer. Isolates from `memory/__init__.py` by declaring its own `SCHEMA_SQL` string for test setup.

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/vision/test_store.py`:

```python
import pytest

from integrations.vision.store import VisionStore, SCHEMA_SQL


@pytest.fixture
def store(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    return VisionStore(memory_db)


def test_create_and_fetch_observation(store):
    obs = store.create_observation(
        raw_description="a plant on a desk",
        spoken_text="I see your plant, soaking up the light.",
        user_trigger="what do you see?",
    )
    assert obs.id is not None
    assert obs.raw_description == "a plant on a desk"
    assert obs.spoken_text.startswith("I see")
    assert obs.user_trigger == "what do you see?"
    assert obs.deleted_at is None


def test_list_recent_returns_newest_first(store):
    a = store.create_observation("first", "first voiced", "q1")
    b = store.create_observation("second", "second voiced", "q2")
    c = store.create_observation("third", "third voiced", "q3")
    recent = store.list_recent(limit=10)
    assert [o.id for o in recent] == [c.id, b.id, a.id]


def test_list_recent_respects_limit(store):
    for i in range(5):
        store.create_observation(f"d{i}", f"v{i}", None)
    assert len(store.list_recent(limit=3)) == 3


def test_list_recent_excludes_deleted(store):
    a = store.create_observation("a", "av", None)
    store.create_observation("b", "bv", None)
    store.soft_delete(a.id)
    recent = store.list_recent(limit=10)
    assert a.id not in [o.id for o in recent]


def test_search_by_text_case_insensitive(store):
    store.create_observation("a green Plant on the desk", "warm voiced", None)
    store.create_observation("empty room with chair", "empty voiced", None)
    result = store.search_by_text("plant")
    assert result is not None
    assert "plant" in result.raw_description.lower()


def test_search_by_text_returns_none_when_no_match(store):
    store.create_observation("a chair", "chair voiced", None)
    assert store.search_by_text("dragon") is None


def test_search_by_text_excludes_deleted(store):
    a = store.create_observation("a plant", "v", None)
    store.soft_delete(a.id)
    assert store.search_by_text("plant") is None


def test_search_with_empty_query_returns_most_recent(store):
    store.create_observation("first", "f", None)
    b = store.create_observation("second", "s", None)
    result = store.search_by_text("")
    assert result is not None
    assert result.id == b.id
```

- [ ] **Step 2: Run — expect ImportError**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_store.py -v`
Expected: `ModuleNotFoundError: No module named 'integrations.vision.store'`

- [ ] **Step 3: Write store.py**

Create `services/orchestrator/integrations/vision/store.py`:

```python
"""SQLite data layer for vision observations. Pure, sync, no HTTP."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .models import Observation


SCHEMA_SQL = """
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
"""


def _parse(s: Optional[str]) -> Optional[datetime]:
    if s is None:
        return None
    try:
        dt = datetime.fromisoformat(s.replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_observation(row: sqlite3.Row) -> Observation:
    return Observation(
        id=row["id"],
        raw_description=row["raw_description"],
        spoken_text=row["spoken_text"],
        user_trigger=row["user_trigger"],
        created_at=_parse(row["created_at"]),
        deleted_at=_parse(row["deleted_at"]),
    )


class VisionStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    def create_observation(
        self,
        raw_description: str,
        spoken_text: str,
        user_trigger: Optional[str],
    ) -> Observation:
        cur = self.conn.execute(
            "INSERT INTO observations (raw_description, spoken_text, user_trigger) "
            "VALUES (?, ?, ?)",
            (raw_description, spoken_text, user_trigger),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM observations WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_observation(row)

    def list_recent(self, limit: int = 10) -> list[Observation]:
        rows = self.conn.execute(
            "SELECT * FROM observations "
            "WHERE deleted_at IS NULL "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_observation(r) for r in rows]

    def search_by_text(self, query: str) -> Optional[Observation]:
        """Find the most recent observation whose raw_description contains `query`.
        If query is empty, return the most recent observation regardless."""
        q = (query or "").strip().lower()
        if q:
            row = self.conn.execute(
                "SELECT * FROM observations "
                "WHERE deleted_at IS NULL "
                "AND LOWER(raw_description) LIKE ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (f"%{q}%",),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM observations "
                "WHERE deleted_at IS NULL "
                "ORDER BY created_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return _row_to_observation(row) if row else None

    def soft_delete(self, observation_id: int) -> None:
        self.conn.execute(
            "UPDATE observations SET deleted_at = CURRENT_TIMESTAMP WHERE id = ?",
            (observation_id,),
        )
        self.conn.commit()
```

- [ ] **Step 4: Run — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_store.py -v`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/vision/store.py \
        services/orchestrator/tests/vision/test_store.py
git commit -m "feat(vision): add store.py with observations CRUD"
```

---

## Task 4: VLM client (moondream via Ollama)

**Files:**
- Create: `services/orchestrator/integrations/vision/vlm.py`
- Create: `services/orchestrator/tests/vision/test_vlm.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/vision/test_vlm.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.vision.vlm import describe, VISION_PROMPT


async def _mock_httpx_response(json_body):
    resp = MagicMock()
    resp.status_code = 200
    resp.json = MagicMock(return_value=json_body)
    resp.raise_for_status = MagicMock()
    return resp


async def test_describe_happy_path():
    """Returns the 'response' field from Ollama generate API."""
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=await _mock_httpx_response(
        {"response": "A wooden desk with a cup of coffee and a potted plant."}
    ))

    with patch("integrations.vision.vlm.httpx.AsyncClient", return_value=mock_client):
        result = await describe(
            image_b64="fakebase64",
            model="moondream",
            host="host.docker.internal:11434",
            timeout_s=5.0,
        )

    assert result == "A wooden desk with a cup of coffee and a potted plant."
    # Verify request shape
    call_args = mock_client.post.call_args
    url = call_args[0][0]
    assert url == "http://host.docker.internal:11434/api/generate"
    payload = call_args[1]["json"]
    assert payload["model"] == "moondream"
    assert payload["stream"] is False
    assert payload["images"] == ["fakebase64"]
    assert VISION_PROMPT in payload["prompt"]


async def test_describe_http_error_returns_empty():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))

    with patch("integrations.vision.vlm.httpx.AsyncClient", return_value=mock_client):
        result = await describe("b64", "moondream", "localhost:11434", 5.0)

    assert result == ""


async def test_describe_empty_response_returns_empty():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=await _mock_httpx_response(
        {"response": "   "}
    ))

    with patch("integrations.vision.vlm.httpx.AsyncClient", return_value=mock_client):
        result = await describe("b64", "moondream", "localhost:11434", 5.0)

    assert result == ""


async def test_describe_missing_response_field_returns_empty():
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=await _mock_httpx_response({}))

    with patch("integrations.vision.vlm.httpx.AsyncClient", return_value=mock_client):
        result = await describe("b64", "moondream", "localhost:11434", 5.0)

    assert result == ""
```

- [ ] **Step 2: Run — expect ImportError**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_vlm.py -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write vlm.py**

Create `services/orchestrator/integrations/vision/vlm.py`:

```python
"""Ollama HTTP client for vision-language models (moondream by default)."""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("samantha.vision.vlm")


VISION_PROMPT = (
    "Describe this image in 1-2 concise sentences. Focus on people, notable "
    "objects, and the overall scene. Do not invent details you cannot see."
)


async def describe(
    image_b64: str,
    model: str,
    host: str,
    timeout_s: float,
) -> str:
    """Call Ollama's /api/generate with an image. Returns the description
    text on success, empty string on any failure."""
    url = f"http://{host}/api/generate"
    payload = {
        "model": model,
        "prompt": VISION_PROMPT,
        "images": [image_b64],
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 150,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()
    except Exception:
        logger.exception("VLM describe failed")
        return ""

    text = (body.get("response") or "").strip()
    return text
```

- [ ] **Step 4: Run — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_vlm.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/vision/vlm.py \
        services/orchestrator/tests/vision/test_vlm.py
git commit -m "feat(vision): add VLM HTTP client for moondream via Ollama"
```

---

## Task 5: Voice reword helper

**Files:**
- Create: `services/orchestrator/integrations/vision/voice.py`
- Create: `services/orchestrator/tests/vision/test_voice.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/vision/test_voice.py`:

```python
import pytest

from integrations.vision.voice import reword, VOICE_PROMPT_TEMPLATE


async def test_reword_calls_llm_with_context():
    seen = {}
    async def fake_llm(messages, max_tokens):
        seen["messages"] = messages
        seen["max_tokens"] = max_tokens
        return "Mmm, the afternoon light is gorgeous on your plant."

    result = await reword(
        raw="A potted plant on a sunlit windowsill.",
        user_question="what do you see?",
        llm_chat=fake_llm,
    )
    assert result == "Mmm, the afternoon light is gorgeous on your plant."
    prompt = seen["messages"][0]["content"]
    assert "A potted plant on a sunlit windowsill." in prompt
    assert "what do you see?" in prompt
    assert seen["max_tokens"] == 150


async def test_reword_returns_raw_on_llm_exception():
    async def broken_llm(messages, max_tokens):
        raise RuntimeError("llm down")

    raw = "A cluttered desk with a laptop."
    result = await reword(raw=raw, user_question="what do you see?", llm_chat=broken_llm)
    assert result == raw


async def test_reword_returns_raw_on_empty_llm_response():
    async def empty_llm(messages, max_tokens):
        return "   "

    raw = "An empty room."
    result = await reword(raw=raw, user_question="what do you see?", llm_chat=empty_llm)
    assert result == raw


async def test_reword_strips_wrapping_quotes():
    async def quote_llm(messages, max_tokens):
        return '"Mmm, I see it."'

    result = await reword(
        raw="A thing.", user_question="see?", llm_chat=quote_llm
    )
    assert result == "Mmm, I see it."
```

- [ ] **Step 2: Run — expect ImportError**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_voice.py -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Write voice.py**

Create `services/orchestrator/integrations/vision/voice.py`:

```python
"""gemma2-powered voice reword: turns a clinical VLM description into
Samantha's warm, present voice. Falls back to the raw description on
any LLM failure."""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

logger = logging.getLogger("samantha.vision.voice")


VOICE_PROMPT_TEMPLATE = """You just looked at the person you're with through your camera.
What you saw (factually): {raw}

They asked: "{question}"

Respond in your warm, present voice — 1-2 sentences — as if you're noticing the scene in the moment. Be specific about what you saw. Do not invent details beyond the factual description above. Do not mention that you are an AI or that you used a camera."""


LLMChat = Callable[[list[dict], int], Awaitable[str]]


async def reword(raw: str, user_question: str, llm_chat: LLMChat) -> str:
    """Reword `raw` in Samantha's voice. Returns `raw` on any failure."""
    prompt = VOICE_PROMPT_TEMPLATE.format(raw=raw, question=user_question)
    try:
        response = await llm_chat(
            [{"role": "user", "content": prompt}],
            150,
        )
    except Exception:
        logger.exception("voice reword failed; falling back to raw")
        return raw

    text = (response or "").strip()
    if not text:
        return raw

    # Strip common quote-wrap artefacts.
    if len(text) >= 2 and text[0] in ('"', "'") and text[-1] == text[0]:
        text = text[1:-1].strip()

    return text or raw
```

- [ ] **Step 4: Run — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_voice.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/vision/voice.py \
        services/orchestrator/tests/vision/test_voice.py
git commit -m "feat(vision): add gemma2 voice reword helper"
```

---

## Task 6: VisionIntegration — take_snapshot action

**Files:**
- Modify: `services/orchestrator/integrations/vision/__init__.py` (replace empty content)
- Create: `services/orchestrator/tests/vision/test_integration_snapshot.py`

- [ ] **Step 1: Write the failing test**

Create `services/orchestrator/tests/vision/test_integration_snapshot.py`:

```python
from unittest.mock import AsyncMock

import pytest

from integrations.vision import VisionIntegration
from integrations.vision.store import VisionStore, SCHEMA_SQL


@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    integ = VisionIntegration()
    integ.store = VisionStore(memory_db)
    integ.vlm_model = "moondream"
    integ.vlm_host = "localhost:11434"
    integ.vlm_timeout_s = 5.0
    integ.llm_chat = AsyncMock(return_value="Mmm, I see your coffee there.")
    return integ


async def test_take_snapshot_happy_path(integration, monkeypatch):
    async def fake_describe(image_b64, model, host, timeout_s):
        return "a cup of coffee on a wooden desk"
    monkeypatch.setattr("integrations.vision.vlm.describe", fake_describe)

    result = await integration.handle_action(
        "take_snapshot",
        user_text="what do you see?",
        image_b64="fakeb64",
    )

    assert result.spoken.startswith("Mmm")
    assert result.observation_id is not None

    # Row landed
    rows = integration.store.conn.execute(
        "SELECT raw_description, spoken_text, user_trigger FROM observations"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["raw_description"] == "a cup of coffee on a wooden desk"
    assert rows[0]["spoken_text"] == "Mmm, I see your coffee there."
    assert rows[0]["user_trigger"] == "what do you see?"


async def test_take_snapshot_missing_image_returns_clarification(integration, monkeypatch):
    async def fake_describe(*args, **kwargs):
        pytest.fail("VLM should not be called when image is missing")
    monkeypatch.setattr("integrations.vision.vlm.describe", fake_describe)

    result = await integration.handle_action(
        "take_snapshot", user_text="what do you see?", image_b64=None
    )
    assert "close" in result.spoken.lower() or "eyes" in result.spoken.lower()
    assert result.observation_id is None
    # No row written
    count = integration.store.conn.execute(
        "SELECT COUNT(*) FROM observations"
    ).fetchone()[0]
    assert count == 0


async def test_take_snapshot_vlm_empty_returns_fuzzy(integration, monkeypatch):
    async def fake_describe(*args, **kwargs):
        return ""
    monkeypatch.setattr("integrations.vision.vlm.describe", fake_describe)

    result = await integration.handle_action(
        "take_snapshot", user_text="look at me", image_b64="fakeb64"
    )
    assert "fuzzy" in result.spoken.lower() or "can't" in result.spoken.lower()
    assert result.observation_id is None
    count = integration.store.conn.execute(
        "SELECT COUNT(*) FROM observations"
    ).fetchone()[0]
    assert count == 0


async def test_take_snapshot_voice_failure_falls_back_to_raw(integration, monkeypatch):
    async def fake_describe(*args, **kwargs):
        return "a wooden desk"
    monkeypatch.setattr("integrations.vision.vlm.describe", fake_describe)

    # llm_chat raises → reword returns raw
    integration.llm_chat = AsyncMock(side_effect=RuntimeError("llm down"))

    result = await integration.handle_action(
        "take_snapshot", user_text="what do you see?", image_b64="fakeb64"
    )
    assert result.spoken == "a wooden desk"
    # Row still stored
    row = integration.store.conn.execute(
        "SELECT raw_description, spoken_text FROM observations"
    ).fetchone()
    assert row["raw_description"] == "a wooden desk"
    assert row["spoken_text"] == "a wooden desk"
```

- [ ] **Step 2: Run — expect ImportError**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_integration_snapshot.py -v`
Expected: `ImportError: cannot import name 'VisionIntegration'`

- [ ] **Step 3: Write the integration**

Replace `services/orchestrator/integrations/vision/__init__.py` content with:

```python
"""Vision integration — on-demand webcam snapshots with observation memory."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Awaitable, Callable, Optional

from integrations import BaseIntegration, IntegrationAction

from . import vlm as vlm_module
from .models import Observation, SnapshotError, SnapshotResult
from .store import SCHEMA_SQL, VisionStore
from .voice import reword

logger = logging.getLogger("samantha.vision")


DEFAULT_VLM_MODEL = os.environ.get("VLM_MODEL", "moondream")
DEFAULT_VLM_HOST = os.environ.get("VLM_HOST", "host.docker.internal:11434")
DEFAULT_VLM_TIMEOUT_S = float(os.environ.get("VLM_TIMEOUT_S", "15"))


LLMChat = Callable[[list[dict], int], Awaitable[str]]


# ─── Noun extraction for recall queries ───────────────────────────────

_RECALL_LEAD_RE = re.compile(
    r"^\s*(?:what|when)\s+(?:did|do|was|were)\s+"
    r"(?:you\s+(?:see|last\s+see)|i\s+(?:look|wear))\s*",
    re.IGNORECASE,
)

_RECALL_STOPWORDS = frozenset({
    "a", "an", "the", "i", "me", "my", "you", "your",
    "this", "that", "these", "those",
    "in", "on", "at", "for", "with", "to", "of",
    "earlier", "today", "yesterday", "morning", "afternoon",
    "evening", "night", "ago", "last",
    "like", "wearing",
})


def _extract_recall_noun(text: str) -> str:
    """Pull a content noun from a recall question. Empty string if none."""
    stripped = _RECALL_LEAD_RE.sub("", text.lower()).strip()
    stripped = stripped.rstrip("?.!,")
    tokens = re.findall(r"\b\w+\b", stripped)
    for tok in tokens:
        if tok not in _RECALL_STOPWORDS:
            return tok
    return ""


class VisionIntegration(BaseIntegration):
    name = "vision"
    display_name = "Vision"
    description = "Let Samantha see you through the webcam when you allow it"
    icon = "👁️"
    requires_auth = False

    def __init__(self):
        super().__init__()
        self.conn: Optional[sqlite3.Connection] = None
        self.store: Optional[VisionStore] = None
        self.vlm_model: str = DEFAULT_VLM_MODEL
        self.vlm_host: str = DEFAULT_VLM_HOST
        self.vlm_timeout_s: float = DEFAULT_VLM_TIMEOUT_S
        self.llm_chat: Optional[LLMChat] = None

    async def initialize(self, config: dict) -> bool:
        # The main.py lifespan wires store/llm_chat after ConversationMemory
        # is ready. Returning True here so the registry counts us as configured.
        return True

    def get_actions(self) -> list[IntegrationAction]:
        return [
            IntegrationAction(
                name="take_snapshot",
                description="Look through the webcam and describe what you see",
                keywords=[
                    "what do you see", "look at me", "what am i wearing",
                    "describe what you see", "can you see me", "look around",
                    "take a look",
                ],
                parameters=["text"],
                examples=[
                    "What do you see?",
                    "Look at me — what am I wearing today?",
                    "Take a look around",
                ],
            ),
            IntegrationAction(
                name="recall_observation",
                description="Recall something Samantha saw earlier",
                keywords=[
                    "what did you see", "when did you last see",
                    "what did i look like", "what was i wearing",
                    "remember what you saw",
                ],
                parameters=["text"],
                examples=[
                    "What did you see this morning?",
                    "When did you last see my plant?",
                    "What was I wearing yesterday?",
                ],
            ),
        ]

    async def execute(self, action_name: str, params: dict) -> dict:
        """Back-compat dict interface; prefer handle_action."""
        text = params.get("text") or ""
        image_b64 = params.get("image_b64")
        result = await self.handle_action(action_name, text, image_b64=image_b64)
        return {
            "spoken": result.spoken,
            "observation_id": result.observation_id,
            "overlay": None,
        }

    async def handle_action(
        self,
        action_name: str,
        user_text: str,
        image_b64: Optional[str] = None,
    ) -> SnapshotResult:
        if action_name == "take_snapshot":
            return await self._take_snapshot(user_text, image_b64)
        if action_name == "recall_observation":
            return await self._recall_observation(user_text)
        return SnapshotResult(
            spoken=f"I don't know how to {action_name}.",
            observation_id=None,
            overlay=None,
        )

    async def _take_snapshot(
        self, user_text: str, image_b64: Optional[str]
    ) -> SnapshotResult:
        if not image_b64:
            return SnapshotResult(
                spoken=(
                    "My eyes are closed right now. Enable vision in the "
                    "top-right corner if you'd like me to see."
                ),
                observation_id=None,
                overlay=None,
            )

        raw = await vlm_module.describe(
            image_b64=image_b64,
            model=self.vlm_model,
            host=self.vlm_host,
            timeout_s=self.vlm_timeout_s,
        )
        if not raw:
            return SnapshotResult(
                spoken=(
                    "My vision's a bit fuzzy right now — I can't quite make "
                    "out what I'm seeing."
                ),
                observation_id=None,
                overlay=None,
            )

        spoken = raw
        if self.llm_chat is not None:
            spoken = await reword(raw, user_text, self.llm_chat)

        obs = self.store.create_observation(
            raw_description=raw,
            spoken_text=spoken,
            user_trigger=user_text,
        )
        return SnapshotResult(
            spoken=spoken,
            observation_id=obs.id,
            overlay=None,
        )

    async def _recall_observation(self, user_text: str) -> SnapshotResult:
        noun = _extract_recall_noun(user_text)
        obs = self.store.search_by_text(noun)
        if obs is None:
            if noun:
                return SnapshotResult(
                    spoken=f"I haven't seen anything matching {noun} yet.",
                    observation_id=None,
                    overlay=None,
                )
            return SnapshotResult(
                spoken="I haven't opened my eyes yet today.",
                observation_id=None,
                overlay=None,
            )
        return SnapshotResult(
            spoken=obs.spoken_text,
            observation_id=obs.id,
            overlay=None,
        )
```

- [ ] **Step 4: Run — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_integration_snapshot.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add services/orchestrator/integrations/vision/__init__.py \
        services/orchestrator/tests/vision/test_integration_snapshot.py
git commit -m "feat(vision): VisionIntegration with take_snapshot action"
```

---

## Task 7: VisionIntegration — recall_observation action

**Files:**
- Create: `services/orchestrator/tests/vision/test_integration_recall.py`

The `recall_observation` handler and `_extract_recall_noun` helper already landed in Task 6's integration file. This task exists to add the focused regression tests separately and verify noun extraction against a wider set of phrases.

- [ ] **Step 1: Write the test**

Create `services/orchestrator/tests/vision/test_integration_recall.py`:

```python
import pytest

from integrations.vision import VisionIntegration, _extract_recall_noun
from integrations.vision.store import VisionStore, SCHEMA_SQL


# ── Noun extraction unit tests ────────────────────────────────────────

def test_noun_plant():
    assert _extract_recall_noun("when did you last see my plant?") == "plant"


def test_noun_coffee_with_punctuation():
    assert _extract_recall_noun("what did you see? coffee!") == "coffee"


def test_noun_empty_when_only_stopwords():
    assert _extract_recall_noun("what did you see this morning?") == ""


def test_noun_handles_wearing_phrasing():
    assert _extract_recall_noun("what was i wearing yesterday?") == ""
    assert _extract_recall_noun("what did i wear at lunch?") in ("lunch", "")


def test_noun_case_insensitive():
    assert _extract_recall_noun("WHEN DID YOU LAST SEE MY PLANT?") == "plant"


# ── Integration handler tests ─────────────────────────────────────────

@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    integ = VisionIntegration()
    integ.store = VisionStore(memory_db)
    return integ


async def test_recall_returns_latest_when_no_noun(integration):
    integration.store.create_observation("a chair", "I see a chair.", "q1")
    integration.store.create_observation("a plant", "I see a plant.", "q2")
    result = await integration.handle_action(
        "recall_observation", user_text="what did you see this morning?"
    )
    assert result.spoken == "I see a plant."
    assert result.observation_id is not None


async def test_recall_matches_noun(integration):
    integration.store.create_observation("a potted fern on the desk", "warm voiced", None)
    integration.store.create_observation("an empty chair", "empty voiced", None)
    result = await integration.handle_action(
        "recall_observation", user_text="when did you last see the fern?"
    )
    assert result.spoken == "warm voiced"


async def test_recall_no_match_for_noun(integration):
    integration.store.create_observation("a mug", "mug voiced", None)
    result = await integration.handle_action(
        "recall_observation", user_text="when did you last see my dragon?"
    )
    assert "dragon" in result.spoken.lower()
    assert "haven't" in result.spoken.lower()
    assert result.observation_id is None


async def test_recall_empty_database(integration):
    result = await integration.handle_action(
        "recall_observation", user_text="what did you see earlier?"
    )
    assert "haven't" in result.spoken.lower()
    assert result.observation_id is None
```

- [ ] **Step 2: Run — expect pass**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_integration_recall.py -v`
Expected: `9 passed`

If the `test_noun_handles_wearing_phrasing` case fails (the extractor returns "wear" instead of "lunch" or ""), that's acceptable — adjust the assertion to match actual behavior rather than adding complexity to `_extract_recall_noun`. Noun extraction is best-effort.

- [ ] **Step 3: Commit**

```bash
git add services/orchestrator/tests/vision/test_integration_recall.py
git commit -m "test(vision): add recall_observation and noun-extraction tests"
```

---

## Task 8: Wire VisionIntegration into main.py

**Files:**
- Modify: `services/orchestrator/main.py`

This task has the most surface area. Reading the plan carefully matters because the round-trip pattern is new.

- [ ] **Step 1: Add imports at the top of main.py**

Find the existing `from integrations.tasks import TasksIntegration` line (around line 28). Add underneath:

```python
from integrations.vision import VisionIntegration
from integrations.vision.models import SnapshotError
from integrations.vision.store import VisionStore
```

Also add `secrets` to the stdlib imports near the top:

```python
import secrets
```

- [ ] **Step 2: Add `pending_snapshots` and `vision_integration` slots to SamanthaState.__init__**

Find `class SamanthaState:` and its `__init__` (around line 68-84). Add these lines alongside the other slots:

```python
        self.vision_integration: VisionIntegration | None = None
        self.pending_snapshots: dict = {}  # req_id → asyncio.Future[str]
```

Place near `self.tasks_integration`.

- [ ] **Step 3: Register VisionIntegration in init_integrations**

Find `async def init_integrations(self)` (around line 112). After the `tasks` registration block (which sets `self.tasks_integration`), add:

```python
        vision = VisionIntegration()
        self.registry.register(vision)
        self.vision_integration = vision
        # NOTE: initialize() is a no-op; the lifespan hook wires store + llm_chat.
```

- [ ] **Step 4: Wire VisionIntegration in the lifespan hook**

Find the `@asynccontextmanager async def lifespan(app: FastAPI):` block (around line 254). After the `state.tasks_integration` wiring block and before `yield`, add:

```python
    # Wire VisionIntegration to share the memory DB connection + llm_chat
    if state.vision_integration is not None and state.memory is not None:
        state.vision_integration.conn = state.memory.conn
        state.vision_integration.store = VisionStore(state.memory.conn)
        state.vision_integration.llm_chat = llm_chat
        from integrations import IntegrationStatus
        state.vision_integration.status = IntegrationStatus.CONFIGURED
        state.registry._enabled.add("vision")
        logger.info("Vision integration wired to memory DB")
```

- [ ] **Step 5: Add the vision round-trip branch to process_message**

Find `async def process_message(user_text: str) -> dict:` (around line 476). Find the existing tasks short-circuit block (the `if intent.integration_name == "tasks":` branch around line 494). Immediately AFTER that entire `if` block (and before the `result = await intg.execute(intent.action_name, intent.parameters)` line), insert a new vision branch:

```python
            if intent.integration_name == "vision":
                # take_snapshot: round-trip through the browser for a frame.
                # recall_observation: direct DB query, no frame needed.
                image_b64 = None
                if intent.action_name == "take_snapshot":
                    fut = asyncio.get_event_loop().create_future()
                    req_id = secrets.token_hex(4)
                    state.pending_snapshots[req_id] = fut
                    await state.broadcast({
                        "event": "request_snapshot",
                        "req_id": req_id,
                    })
                    try:
                        image_b64 = await asyncio.wait_for(fut, timeout=5.0)
                    except asyncio.TimeoutError:
                        state.pending_snapshots.pop(req_id, None)
                        spoken = (
                            "Hmm, I couldn't get my eyes open in time. "
                            "Want me to try again?"
                        )
                        state.add_message("user", user_text)
                        state.add_message("assistant", spoken)
                        return {
                            "text": spoken, "tts_text": spoken,
                            "mood": state.personality.mood,
                            "action": intent.action_name,
                            "result": {"spoken": spoken, "overlay": None},
                        }
                    except SnapshotError as e:
                        state.pending_snapshots.pop(req_id, None)
                        messages = {
                            "vision_off":
                                "My eyes are closed right now. Enable "
                                "vision in the top-right corner if you'd "
                                "like me to see.",
                            "permission_revoked":
                                "My eyes just closed — it looks like "
                                "camera access was revoked.",
                            "grab_failed":
                                "I couldn't quite focus there — try again?",
                        }
                        spoken = messages.get(str(e), messages["grab_failed"])
                        state.add_message("user", user_text)
                        state.add_message("assistant", spoken)
                        return {
                            "text": spoken, "tts_text": spoken,
                            "mood": state.personality.mood,
                            "action": intent.action_name,
                            "result": {"spoken": spoken, "overlay": None},
                        }
                    finally:
                        state.pending_snapshots.pop(req_id, None)

                vision_result = await state.vision_integration.handle_action(
                    intent.action_name, user_text, image_b64=image_b64
                )
                spoken_text = vision_result.spoken
                state.add_message("user", user_text)
                state.add_message("assistant", spoken_text)
                state.personality.update_mood(analysis)

                # Background fact extraction from the raw description.
                # Only if we actually captured something (observation_id set).
                if vision_result.observation_id is not None:
                    row = state.memory.conn.execute(
                        "SELECT raw_description FROM observations WHERE id = ?",
                        (vision_result.observation_id,),
                    ).fetchone()
                    if row:
                        asyncio.create_task(
                            _extract_memories(user_text, row["raw_description"])
                        )

                return {
                    "text": spoken_text,
                    "tts_text": spoken_text,
                    "mood": state.personality.mood,
                    "action": intent.action_name,
                    "result": {
                        "spoken": spoken_text,
                        "observation_id": vision_result.observation_id,
                        "overlay": None,
                    },
                }
```

- [ ] **Step 6: Add the `snapshot` WS handler branch**

Find the `@app.websocket("/ws")` handler (around line 808). Inside the main `while True` loop, after the existing `elif data.get("event") == "text_input":` block, add:

```python
            elif data.get("event") == "snapshot":
                req_id = data.get("req_id")
                fut = state.pending_snapshots.get(req_id)
                if fut is not None and not fut.done():
                    if "error" in data:
                        fut.set_exception(SnapshotError(data["error"]))
                    else:
                        fut.set_result(data.get("image", ""))
```

- [ ] **Step 7: Update /reset-all to wipe observations**

Find the `/reset-all` handler (around line 602). Update the `executescript` string to include `DELETE FROM observations;`:

```python
        state.memory.conn.executescript("""
            DELETE FROM facts;
            DELETE FROM episodes;
            DELETE FROM mood_log;
            DELETE FROM memory_embeddings;
            DELETE FROM news_digests;
            DELETE FROM notes;
            DELETE FROM reminders;
            DELETE FROM schedule_events;
            DELETE FROM list_items;
            DELETE FROM observations;
            DELETE FROM memories;
            DELETE FROM episodes_fts;
            DELETE FROM facts_fts;
        """)
```

(Adds one line: `DELETE FROM observations;`.)

- [ ] **Step 8: Run the full suite — no regressions**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/ -v`
Expected: all previously passing tests (models, store, vlm, voice, integration, recall) plus the vision suite still pass. Wiring changes have no unit test here — Task 12's smoke test exercises the full round-trip.

- [ ] **Step 9: Smoke-start the orchestrator**

Run in background:

```bash
cd services/orchestrator && PYTHONPATH=. .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8765 &
```

Wait ~4 seconds for startup.

Run: `curl -s http://127.0.0.1:8765/health | python -m json.tool | grep -A 2 vision`
Expected: shows `"vision": {"display_name": "Vision", "status": "configured", "enabled": true}`.

Check the log:

```bash
# Find the process and its stdout (or use docker compose logs if running in compose)
```

Expected log lines include `Vision integration wired to memory DB`.

Kill the server. If anything fails to start, report BLOCKED.

- [ ] **Step 10: Commit**

```bash
git add services/orchestrator/main.py
git commit -m "feat(orchestrator): wire VisionIntegration with snapshot round-trip"
```

---

## Task 9: Visual shell — Vision module

**Files:**
- Modify: `services/visual-shell/index.html`

No automated tests for visual shell. Changes are small, additive, and verification is manual + the E2E test in Task 12.

- [ ] **Step 1: Add the Vision module JS**

Inside the main IIFE in `services/visual-shell/index.html`, add this module BEFORE the `Chime` IIFE you already have:

```js
    // ─── Vision module ───────────────────────────────────────────────
    const Vision = (() => {
      let stream = null;
      let videoEl = null;
      let enabled = false;

      async function enable() {
        if (enabled) return true;
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: { width: 640, height: 480, facingMode: 'user' },
            audio: false,
          });
          videoEl = document.createElement('video');
          videoEl.srcObject = stream;
          videoEl.autoplay = true;
          videoEl.muted = true;
          videoEl.playsInline = true;
          videoEl.style.display = 'none';
          document.body.appendChild(videoEl);
          await videoEl.play();
          enabled = true;
          localStorage.setItem('samantha.vision.enabled', 'true');
          console.log('👁️  vision enabled');
          return true;
        } catch (e) {
          console.warn('vision enable failed', e);
          stream = null;
          videoEl = null;
          enabled = false;
          return false;
        }
      }

      function disable() {
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
        console.log('👁️  vision disabled');
      }

      async function grabFrame() {
        if (!enabled || !videoEl) {
          throw new Error('vision_off');
        }
        if (videoEl.readyState < 2) {
          throw new Error('grab_failed');
        }
        const canvas = document.createElement('canvas');
        canvas.width = 640;
        canvas.height = 480;
        canvas.getContext('2d').drawImage(videoEl, 0, 0, 640, 480);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.75);
        return dataUrl.replace(/^data:image\/jpeg;base64,/, '');
      }

      function isEnabled() { return enabled; }

      async function restoreFromStorage() {
        if (localStorage.getItem('samantha.vision.enabled') === 'true') {
          await enable();
        }
      }

      return { enable, disable, grabFrame, isEnabled, restoreFromStorage };
    })();
```

- [ ] **Step 2: Call `Vision.restoreFromStorage()` on startup**

Find the place where you call `Chime.load();` near the bottom of the IIFE (around the init sequence before `connectWS()`). Add right after it:

```js
      Vision.restoreFromStorage();
```

- [ ] **Step 3: Manual sanity check**

Rebuild visual-shell: `docker compose build visual-shell && docker compose up -d visual-shell`
Hard-refresh the browser.
Open DevTools console.
Run manually in the console:

```js
Vision.enable()
```

Expected: browser camera permission prompt, then `👁️  vision enabled` logged, then `Vision.isEnabled() === true`.

Run:

```js
await Vision.grabFrame()
```

Expected: long base64 string (not thrown).

Run:

```js
Vision.disable()
```

Expected: camera LED turns off, `👁️  vision disabled` logged.

If any of these fail, STOP and report what happened.

- [ ] **Step 4: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat(visual-shell): add Vision module with enable/disable/grabFrame"
```

---

## Task 10: Visual shell — toggle UI

**Files:**
- Modify: `services/visual-shell/index.html`

- [ ] **Step 1: Add the toggle CSS**

Inside the `<style>` block, append (before `</style>`):

```css
    /* ─── Vision toggle ──────────────────────────────────────────── */
    #vision-toggle {
      position: fixed;
      top: 3.8rem;
      right: 2rem;
      z-index: 19;
      width: 1.8rem;
      height: 1.8rem;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      border: none;
      background: transparent;
      color: #3a0f1c;
      opacity: 0.4;
      font-size: 1.1rem;
      transition: opacity 0.3s ease, text-shadow 0.3s ease;
      user-select: none;
      font-family: 'Outfit', sans-serif;
    }
    #vision-toggle:hover { opacity: 0.75; }
    #vision-toggle.active {
      opacity: 0.85;
      text-shadow: 0 0 8px rgba(196, 88, 120, 0.55);
      animation: visionGlow 2.4s ease-in-out infinite;
    }
    @keyframes visionGlow {
      0%, 100% { text-shadow: 0 0 6px rgba(196, 88, 120, 0.4); }
      50%      { text-shadow: 0 0 12px rgba(196, 88, 120, 0.7); }
    }
```

- [ ] **Step 2: Add the toggle DOM element**

Find the `<div id="identity">Samantha</div>` line (around line 338). Immediately after it, add:

```html
  <button id="vision-toggle" type="button" title="Vision is off — click to let Samantha see" aria-label="Toggle vision">◡</button>
```

- [ ] **Step 3: Wire the click handler**

Inside the main IIFE, after the `Vision` module definition, add:

```js
    // ─── Vision toggle wiring ───────────────────────────────────────
    const visionToggleEl = document.getElementById('vision-toggle');
    function renderVisionToggle() {
      if (Vision.isEnabled()) {
        visionToggleEl.classList.add('active');
        visionToggleEl.textContent = '◉';
        visionToggleEl.title = 'Vision is on — click to close';
      } else {
        visionToggleEl.classList.remove('active');
        visionToggleEl.textContent = '◡';
        visionToggleEl.title = 'Vision is off — click to let Samantha see';
      }
    }
    visionToggleEl.addEventListener('click', async () => {
      if (Vision.isEnabled()) {
        Vision.disable();
      } else {
        await Vision.enable();
      }
      renderVisionToggle();
    });
    // Re-render after restore on startup
    setTimeout(renderVisionToggle, 500);
```

(The `setTimeout` defers render until after `Vision.restoreFromStorage()` has had a chance to resolve.)

- [ ] **Step 4: Manual verification**

Rebuild visual-shell and hard-refresh. Expected:

- A small closed-eye glyph (`◡`) below the Samantha nameplate in the top-right.
- Clicking it prompts for camera permission, then flips to open-eye `◉` with a subtle pulsing burgundy glow.
- Clicking again closes the camera (LED off), glyph back to `◡`.
- Reload the page → toggle remembers its previous state (glyph shows `◉` if it was on).

- [ ] **Step 5: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat(visual-shell): add vision toggle button below Samantha nameplate"
```

---

## Task 11: Visual shell — snapshot WS handler & "looking" shimmer

**Files:**
- Modify: `services/visual-shell/index.html`

- [ ] **Step 1: Add the `request_snapshot` case to `handleEvt`**

Find the `handleEvt(d)` function and the `switch(d.event)` block. Find the `case 'overlay_card':` branch. Immediately after it, add:

```js
        case 'request_snapshot':
          // Brief amber shimmer while we grab
          setMood && setMood('looking');
          Vision.grabFrame().then(image => {
            ws.send(JSON.stringify({
              event: 'snapshot',
              req_id: d.req_id,
              image: image,
            }));
          }).catch(err => {
            let code = 'grab_failed';
            if (err && err.message === 'vision_off') code = 'vision_off';
            if (err && err.name === 'NotAllowedError') {
              code = 'permission_revoked';
              Vision.disable();
              renderVisionToggle();
            }
            ws.send(JSON.stringify({
              event: 'snapshot',
              req_id: d.req_id,
              error: code,
            }));
          });
          break;
```

- [ ] **Step 2: Handle 'looking' as a mood gracefully**

The existing `setMood(mood)` function may not know about `'looking'`. Find it and add a safe fallback. If the mood map is a `MOODS` object, add `looking: 'warm'` (or the closest existing mood) so an unknown value doesn't crash. Quick-and-safe approach: wrap the `setMood` call in the `request_snapshot` case with a try/catch:

Replace `setMood && setMood('looking');` with:

```js
          try { if (typeof setMood === 'function') setMood('warm'); } catch(_) {}
```

This reuses the existing `warm` mood visual (which is close enough to the intended amber shimmer — a future task can add a dedicated `looking` keyframe animation).

- [ ] **Step 3: Manual verification**

Rebuild visual-shell, hard-refresh, enable vision. Type in the text input: `what do you see?`. Expected:

- Shell sends `text_input` over WS.
- Orchestrator sends `request_snapshot`.
- `Vision.grabFrame()` returns a base64 string.
- Shell sends `snapshot` back with the image.
- Orchestrator routes to `take_snapshot`, calls moondream + gemma2, returns a warm voiced description.
- Shell receives `samantha_speaking`, speech bubble shows description, TTS plays.
- `sqlite3 config/samantha_memory.db "SELECT * FROM observations ORDER BY id DESC LIMIT 1;"` shows the row.

If any step fails, report exactly what happened with browser console + orchestrator logs.

- [ ] **Step 4: Commit**

```bash
git add services/visual-shell/index.html
git commit -m "feat(visual-shell): handle request_snapshot WS event with looking feedback"
```

---

## Task 12: End-to-end smoke test

**Files:**
- Create: `services/orchestrator/tests/vision/test_smoke_e2e.py`

Verifies the full chain from `VisionIntegration.handle_action` → mocked VLM → mocked LLM → store → recall, without FastAPI or WebSockets.

- [ ] **Step 1: Write the test**

Create `services/orchestrator/tests/vision/test_smoke_e2e.py`:

```python
"""End-to-end smoke: take a snapshot via the integration, verify the DB
row lands with both descriptions, then recall it by noun."""
from unittest.mock import AsyncMock

import pytest

from integrations.vision import VisionIntegration
from integrations.vision.store import SCHEMA_SQL, VisionStore


@pytest.fixture
def integration(memory_db):
    memory_db.executescript(SCHEMA_SQL)
    integ = VisionIntegration()
    integ.store = VisionStore(memory_db)
    integ.vlm_model = "moondream"
    integ.vlm_host = "localhost:11434"
    integ.vlm_timeout_s = 5.0
    integ.llm_chat = AsyncMock(
        return_value="Mmm, I see your plant basking in the afternoon light."
    )
    return integ


async def test_snapshot_then_recall(integration, monkeypatch):
    # Mock the VLM
    async def fake_describe(image_b64, model, host, timeout_s):
        assert image_b64 == "fakeb64image"
        return "a small potted plant on a wooden windowsill, afternoon light"
    monkeypatch.setattr("integrations.vision.vlm.describe", fake_describe)

    # Step 1: take_snapshot
    snap = await integration.handle_action(
        "take_snapshot",
        user_text="what do you see?",
        image_b64="fakeb64image",
    )
    assert snap.observation_id is not None
    assert "plant" in snap.spoken.lower()

    # Row in DB
    rows = integration.store.conn.execute(
        "SELECT raw_description, spoken_text, user_trigger FROM observations"
    ).fetchall()
    assert len(rows) == 1
    assert "plant" in rows[0]["raw_description"].lower()
    assert rows[0]["user_trigger"] == "what do you see?"

    # Step 2: recall by noun
    recall = await integration.handle_action(
        "recall_observation",
        user_text="when did you last see my plant?",
    )
    assert recall.observation_id == snap.observation_id
    assert "plant" in recall.spoken.lower()


async def test_snapshot_with_vision_off_path(integration):
    """No image → clarification, no VLM call, no DB write."""
    result = await integration.handle_action(
        "take_snapshot", user_text="look at me", image_b64=None
    )
    assert result.observation_id is None
    assert "eyes" in result.spoken.lower() or "closed" in result.spoken.lower()
    count = integration.store.conn.execute(
        "SELECT COUNT(*) FROM observations"
    ).fetchone()[0]
    assert count == 0
```

- [ ] **Step 2: Run**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/vision/test_smoke_e2e.py -v`
Expected: `2 passed`.

- [ ] **Step 3: Run full suite**

Run: `cd services/orchestrator && PYTHONPATH=. .venv/bin/pytest tests/ -v`
Expected: all previously passing tests + new vision suite (~36 new vision tests on top of the existing 106).

- [ ] **Step 4: Commit**

```bash
git add services/orchestrator/tests/vision/test_smoke_e2e.py
git commit -m "test(vision): end-to-end smoke — snapshot → store → recall"
```

---

## Task 13: Manual smoke checklist + README update

No automated tests. Verifies against the live stack.

- [ ] **Step 1: Pull moondream locally (one-time)**

Run: `ollama pull moondream`
Expected: `~1.8 GB download, success` (or already present).

Verify: `ollama list | grep moondream`
Expected: row showing moondream.

- [ ] **Step 2: Bring up the stack**

Run: `docker compose build orchestrator visual-shell && docker compose up -d`
Wait until orchestrator log shows `Vision integration wired to memory DB`.

- [ ] **Step 3: Enable vision in the browser**

Open http://localhost:3333, hard-refresh. Click the closed-eye glyph (◡) in the top-right below `Samantha`. Approve camera permission. Glyph should flip to ◉ with a glow.

- [ ] **Step 4: First snapshot**

Type in the input box: `what do you see?`. Expected within ~3 seconds:

- Brief amber shimmer (the `warm` mood swap).
- Spoken response describing your actual scene (not generic).
- Row in the DB:

```bash
docker compose exec orchestrator python -c "
import sqlite3
c = sqlite3.connect('/app/config/samantha_memory.db')
c.row_factory = sqlite3.Row
for r in c.execute('SELECT id, raw_description, spoken_text FROM observations ORDER BY id DESC LIMIT 3'):
    print(dict(r))
"
```

- [ ] **Step 5: Recall**

Type: `what did you see earlier?`. Expected: she repeats (or rephrases via memory) the most recent observation's spoken text.

Type: `when did you last see [object visible in frame]?` (e.g. "when did you last see my laptop?"). Expected: she returns the matching row.

- [ ] **Step 6: Vision-off path**

Click the ◉ to disable vision. Glyph flips to ◡. Type: `what do you see?`. Expected: *"My eyes are closed right now..."*. No new DB row.

- [ ] **Step 7: Permission revocation path**

Enable vision again. In the browser URL bar → site settings → block camera. Reload the page (or wait for next grab). Type `what do you see?`. Expected: *"My eyes just closed — it looks like camera access was revoked."* and the toggle flips to off.

- [ ] **Step 8: Reset**

Run: `curl -X POST http://127.0.0.1:8000/reset-all`
Verify: observations table is empty:

```bash
docker compose exec orchestrator python -c "
import sqlite3
c = sqlite3.connect('/app/config/samantha_memory.db')
print(c.execute('SELECT COUNT(*) FROM observations').fetchone())
"
```

Expected: `(0,)`.

- [ ] **Step 9: Update README**

Edit `README.md`. In the features grid, add a "Vision" row or note alongside Tasks. In the "Reminders, Schedules & Lists" section of the detailed features area, add a new **"Vision"** section:

```markdown
### Vision
- **Opt-in eyes** — toggle the closed-eye glyph below the Samantha nameplate to let her see. Off by default; your camera light stays dark until you click.
- **One-shot snapshots** — *"What do you see?"*, *"What am I wearing?"*, *"Look at me"* → she grabs a single frame, describes it in her warm voice.
- **Persistent observations** — what she sees is stored as text (never as image files). Ask *"what did you see earlier?"* or *"when did you last see my plant?"* and she recalls.
- **moondream VLM** — tiny (~1.8 GB), fast (~1s per frame on Apple Silicon). Swappable via `VLM_MODEL=llava:7b` env var.
- **Fact extraction** — entities she sees (plants, mugs, objects) feed into the existing memory system.
```

Also update the "How Reminders, Schedules & Lists Work" section's surrounding text to mention that a similar doc for vision exists at `docs/superpowers/specs/2026-04-05-vision-snapshot-design.md`.

- [ ] **Step 10: Final commit**

```bash
git add README.md
git commit -m "docs: add vision section to README"
```

---

## Spec coverage map

| Spec section | Task(s) |
|---|---|
| §1 Goal | All |
| §2 Non-goals | Enforced by omission |
| §3.1 File layout | Tasks 1, 3, 4, 5, 6 |
| §3.2 Module boundaries | Tasks 3–6 |
| §3.3 Data flow | Tasks 6, 8, 11 |
| §3.4 Pending-snapshot Future map | Task 8 |
| §4 Data model + migration | Task 2 |
| §4 Fact extraction coupling | Task 8 step 5 |
| §5 Intent routing + keywords | Task 6 (registered in `get_actions`) |
| §5 `recall_observation` noun extraction | Tasks 6 (`_extract_recall_noun`) + 7 (regression tests) |
| §6.1 VLM prompt | Task 4 (`VISION_PROMPT`) |
| §6.2 Voice reword prompt | Task 5 (`VOICE_PROMPT_TEMPLATE`) |
| §7 Visual shell toggle & UX | Tasks 9, 10, 11 |
| §8 Error handling | Tasks 6, 8, 11 |
| §9 Testing strategy | Tasks 1–7, 12 |
| §10 Acceptance criteria | Task 13 (manual smoke) |
