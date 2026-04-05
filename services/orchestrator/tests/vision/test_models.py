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
