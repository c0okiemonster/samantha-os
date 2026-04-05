from integrations.tasks.models import Recurrence
from integrations.tasks.parser import parse_recurrence


def test_no_recurrence():
    rec, stripped = parse_recurrence("remind me to call mom at 5")
    assert rec is None
    assert stripped == "remind me to call mom at 5"


def test_every_day():
    rec, stripped = parse_recurrence("every day at 8 remind me to take vitamins")
    assert rec == Recurrence("daily")
    assert "every day" not in stripped.lower()
    assert "at 8" in stripped


def test_every_morning_is_daily():
    rec, _ = parse_recurrence("every morning at 7 stretch")
    assert rec == Recurrence("daily")


def test_every_evening_is_daily():
    rec, _ = parse_recurrence("every evening at 9 journal")
    assert rec == Recurrence("daily")


def test_every_weekday():
    rec, stripped = parse_recurrence("every weekday at 8 vitamins")
    assert rec == Recurrence("weekdays")
    assert "weekday" not in stripped.lower()


def test_every_monday():
    rec, _ = parse_recurrence("every monday at 9 planning")
    assert rec == Recurrence("weekly:mon")


def test_every_sunday():
    rec, _ = parse_recurrence("every sunday evening reflect")
    assert rec == Recurrence("weekly:sun")


def test_every_abbreviated_day():
    rec, _ = parse_recurrence("every fri afternoon")
    assert rec == Recurrence("weekly:fri")
