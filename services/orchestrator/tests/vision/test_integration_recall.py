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
    # Either returns "" (all stopwords after lead) or "lunch" — both acceptable.
    result = _extract_recall_noun("what did i wear at lunch?")
    assert result in ("lunch", "")


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
