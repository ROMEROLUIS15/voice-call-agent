"""Start times a day offers for a service, from its opening hours and what is already booked."""

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from voice_call_agent.practice_schedule.practice_catalog import WEEKDAYS, PracticeBusiness
from voice_call_agent.scheduling_backend.scheduling_models import OpeningHours

Interval = tuple[time, time]


def hours_on(business: PracticeBusiness, day: date) -> OpeningHours | None:
    """The day's opening hours, or `None` when the business is closed."""
    return business.opening_hours.get(WEEKDAYS[day.weekday()])


def end_of(start: time, minutes: int) -> time | None:
    """`start` plus `minutes`, or `None` when that crosses midnight."""
    end = datetime.combine(date.min, start) + timedelta(minutes=minutes)
    return end.time() if end.date() == date.min else None


def fits(hours: OpeningHours, interval: Interval) -> bool:
    start, end = interval
    return hours.opens <= start and end <= hours.closes


def overlaps(interval: Interval, booked: Iterable[Interval]) -> bool:
    start, end = interval
    return any(start < other_end and other_start < end for other_start, other_end in booked)


def free_starts(
    hours: OpeningHours,
    *,
    duration_min: int,
    step_min: int,
    booked: list[Interval],
    not_before: time | None,
) -> list[time]:
    """Every `step_min` from opening, the starts whose whole service fits and is free."""
    starts: list[time] = []
    start: time | None = hours.opens
    while start is not None and (end := end_of(start, duration_min)) is not None:
        if not fits(hours, (start, end)):
            break
        if (not_before is None or start >= not_before) and not overlaps((start, end), booked):
            starts.append(start)
        start = end_of(start, step_min)
    return starts
