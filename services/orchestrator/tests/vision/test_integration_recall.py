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


def test_noun_wearing_not_sliced_to_ing():
    """Regression: 'what was I wearing yesterday?' must NOT return 'ing'.
    The lead regex needs word-boundary anchoring after the wear/see verbs
    so '-ing' suffixes are consumed as part of the verb, not left behind."""
    assert _extract_recall_noun("what was I wearing yesterday?") == ""


def test_noun_wearing_with_real_noun_survives():
    """After stripping 'what was I wearing', a real content noun survives."""
    result = _extract_recall_noun("what was I wearing to the beach?")
    assert result == "beach"


def test_noun_looking_handled():
    """'looking' must be stripped cleanly, not leave 'ing' behind."""
    result = _extract_recall_noun("what was I looking at in the mug?")
    assert result == "mug"


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
