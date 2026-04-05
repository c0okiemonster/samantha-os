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
