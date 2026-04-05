from datetime import datetime, timezone

import pytest
from freezegun import freeze_time

from integrations.tasks.models import ParseError
from integrations.tasks.parser import parse_when

UTC = timezone.utc


@freeze_time("2026-04-05 12:00:00")  # Sunday noon UTC
def test_in_twenty_minutes():
    dt = parse_when("in 20 minutes", tz="UTC")
    assert dt == datetime(2026, 4, 5, 12, 20, tzinfo=UTC)


@freeze_time("2026-04-05 12:00:00")
def test_at_5pm_today():
    dt = parse_when("at 5pm", tz="UTC")
    assert dt == datetime(2026, 4, 5, 17, 0, tzinfo=UTC)


@freeze_time("2026-04-05 20:00:00")  # 8pm — 5pm is already past
def test_at_5pm_rolls_to_tomorrow_when_past():
    dt = parse_when("at 5pm", tz="UTC")
    assert dt.date() == datetime(2026, 4, 6).date()
    assert dt.hour == 17


@freeze_time("2026-04-05 12:00:00")
def test_tomorrow_at_3():
    dt = parse_when("tomorrow at 3pm", tz="UTC")
    assert dt == datetime(2026, 4, 6, 15, 0, tzinfo=UTC)


@freeze_time("2026-04-05 12:00:00")  # Sunday
def test_friday():
    dt = parse_when("friday", tz="UTC")
    assert dt.weekday() == 4  # Friday
    assert dt > datetime(2026, 4, 5, 12, 0, tzinfo=UTC)


@freeze_time("2026-04-05 12:00:00")
def test_empty_string_raises():
    with pytest.raises(ParseError):
        parse_when("", tz="UTC")


@freeze_time("2026-04-05 12:00:00")
def test_unparseable_raises():
    with pytest.raises(ParseError):
        parse_when("glorp wibble", tz="UTC")


@freeze_time("2026-04-05 12:00:00")
def test_result_is_always_utc():
    dt = parse_when("at 5pm", tz="Europe/Stockholm")
    # 5pm Europe/Stockholm in April = 15:00 UTC (CEST = UTC+2)
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 15
