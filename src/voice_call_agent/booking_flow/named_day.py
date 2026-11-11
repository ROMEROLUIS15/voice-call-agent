"""A weekday and a date the caller named for one day, checked against each other by the code.

"El jueves cuatro" when the fourth is a Wednesday: the caller said two days, and booking either
one without asking books a day they may not want. The model passes the weekday, the day number
and the month as the caller said them; the code works out the date said from the calendar, finds
whether it disagrees with the weekday and which two days to ask about. The model's own reading of
the calendar is not trusted for this (ADR 0019).
"""

import calendar
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

_MONTHS_AHEAD = 12
"""How far from today a day number without a month is looked for."""
RELATIVE_DAYS = {"today": 0, "tomorrow": 1, "day_after_tomorrow": 2}
_DAY_FIELDS = ["weekday", "day_number", "relative_day"]
"""The arguments a day can be said with: one of them is needed."""
"""The days a caller names from today ("mañana"), as the model passes them, and their offset."""


@dataclass(frozen=True)
class DayQuestion:
    """The caller named a weekday and a date that do not match: they say which day they want."""

    said_date: date
    """The date the caller named: their day number and month, the next one from today on."""
    weekday_date: date
    """The day with the weekday the caller said, the nearest to `said_date` from today on."""


@dataclass(frozen=True)
class NamedDay:
    """A day as the caller named it, in their words; any part may be missing."""

    weekday: str | None
    day_number: int | None
    month: str | None


class UnknownNamedDayError(Exception):
    """A part of the named day is not a weekday or a month, or the date does not exist."""

    def __init__(self, fields: list[str]) -> None:
        super().__init__(", ".join(fields))
        self.fields = fields


def day_said(
    named: NamedDay,
    relative_day: str | None,
    next_week: bool | None,
    *,
    weekdays: Sequence[str],
    months: Sequence[str],
    today: date,
) -> date:
    """The day the caller asked for, worked out by the code from their words.

    In order: a day named from today ("mañana"); a day number, with its month if one was named,
    the next such date from today on; a weekday of next week, in the coming Monday-to-Sunday
    week; a weekday alone, the next one from tomorrow on, so "el lunes" said on a Monday is next
    week's. A weekday that does not match the day is left to `day_question`.
    """
    if relative_day is not None:
        offset = RELATIVE_DAYS.get(relative_day.strip().casefold())
        if offset is None:
            raise UnknownNamedDayError(["relative_day"])
        return today + timedelta(days=offset)
    month = _index(named.month, months, "month")
    if named.day_number is not None:
        return _date_named(named.day_number, month, today)
    weekday = _index(named.weekday, weekdays, "weekday")
    if weekday is None:
        raise UnknownNamedDayError(["weekday"] if next_week else _DAY_FIELDS)
    if next_week:
        return today + timedelta(days=7 - today.weekday() + weekday)
    return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)


def day_question(
    day: date,
    named: NamedDay,
    *,
    weekdays: Sequence[str],
    months: Sequence[str],
    today: date,
) -> DayQuestion | None:
    """The question to ask when the weekday named does not match the date named, else `None`.

    The date named comes from the caller's day number and month, not from the `day` the model
    passed, so a model that resolved "el jueves cuatro" to Thursday the fifth is still caught;
    without a day number, it is `day`.
    """
    weekday = _index(named.weekday, weekdays, "weekday")
    month = _index(named.month, months, "month")
    if weekday is None:
        return None
    said = day if named.day_number is None else _date_named(named.day_number, month, today)
    if said.weekday() == weekday:
        return None
    # The only day with that weekday within three days of the date named.
    other = said + timedelta(days=(weekday - said.weekday() + 3) % 7 - 3)
    if other < today:
        other += timedelta(days=7)
    return DayQuestion(said, other)


def _date_named(number: int, month: int | None, today: date) -> date:
    """The next date from today on with the day number, in the month if one was named."""
    if month is not None:
        months = [(today.year, month + 1), (today.year + 1, month + 1)]
    else:
        months = [
            (today.year + (today.month - 1 + ahead) // 12, (today.month - 1 + ahead) % 12 + 1)
            for ahead in range(_MONTHS_AHEAD + 1)
        ]
    named = (
        date(year, number_month, number)
        for year, number_month in months
        if number <= calendar.monthrange(year, number_month)[1]
    )
    found = next((candidate for candidate in named if candidate >= today), None)
    if found is None:
        raise UnknownNamedDayError(["day_number", "month"] if month is not None else ["day_number"])
    return found


def _index(said: str | None, names: Sequence[str], field: str) -> int | None:
    """The position of the name the caller said, whatever its case or accents."""
    if said is None:
        return None
    wanted = _plain(said)
    found = next((index for index, name in enumerate(names) if _plain(name) == wanted), None)
    if found is None:
        raise UnknownNamedDayError([field])
    return found


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
