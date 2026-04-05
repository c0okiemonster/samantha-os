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
    async def fake_describe(image_b64, model, host, timeout_s, user_question=None):
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
