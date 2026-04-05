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


@freeze_time("2026-04-05 15:00:00")  # 3pm UTC
def test_at_bare_hour_afternoon_picks_same_day_pm():
    """'at 5' said at 3pm should mean 5pm today, not midnight on the 5th."""
    dt = parse_when("at 5", tz="UTC")
    assert dt == datetime(2026, 4, 5, 17, 0, tzinfo=UTC)


@freeze_time("2026-04-05 09:00:00")  # 9am UTC
def test_at_bare_hour_morning_picks_later_today_pm():
    """'at 5' said at 9am should still mean 5pm today (next occurrence)."""
    dt = parse_when("at 5", tz="UTC")
    assert dt == datetime(2026, 4, 5, 17, 0, tzinfo=UTC)


@freeze_time("2026-04-05 20:00:00")  # 8pm UTC — 5pm already past, 5am next
def test_at_bare_hour_late_picks_tomorrow_am():
    dt = parse_when("at 5", tz="UTC")
    assert dt == datetime(2026, 4, 6, 5, 0, tzinfo=UTC)


@freeze_time("2026-04-05 10:00:00")
def test_at_bare_hour_24h_format():
    """'at 17' is unambiguous 24-hour."""
    dt = parse_when("at 17", tz="UTC")
    assert dt == datetime(2026, 4, 5, 17, 0, tzinfo=UTC)


@freeze_time("2026-04-05 10:00:00")
def test_at_bare_noon():
    """'at 12' should mean noon, not midnight."""
    dt = parse_when("at 12", tz="UTC")
    assert dt == datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
