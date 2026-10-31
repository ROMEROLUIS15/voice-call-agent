"""A weekday and a date the caller named for one day, checked against each other by the code.

"El jueves cuatro" when the fourth is a Wednesday: the caller said two days, and booking either
one without asking books a day they may not want. The model passes the weekday and the day number
as the caller said them; the code finds whether they disagree and which two days to ask about.
The model's own reading of the calendar is not trusted for this (ADR 0019).
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

_DAY_NUMBER_REACH = 20
"""How far from the day passed the date with the caller's day number is looked for."""


@dataclass(frozen=True)
class DayQuestion:
    """The caller named a weekday and a date that do not match: they say which day they want."""

    said_date: date
    """The date with the day number the caller said."""
    weekday_date: date
    """The day with the weekday the caller said, the nearest to `said_date` from today on."""


def weekday_index(said: str, weekdays: Sequence[str]) -> int | None:
    """The weekday the caller said (0 is Monday), whatever its case or accents; `None` if it is
    not one of `weekdays`."""
    wanted = _plain(said)
    return next((index for index, name in enumerate(weekdays) if _plain(name) == wanted), None)


def day_question(
    day: date, day_number: int | None, weekday: int | None, today: date
) -> DayQuestion | None:
    """The question to ask when the weekday said does not match the date said, else `None`.

    The date said is the one with the caller's day number nearest the day passed, so a model
    that resolved "el jueves cuatro" to Thursday the fifth is still caught.
    """
    if weekday is None:
        return None
    said = day if day_number is None else _nearest_with_number(day, day_number)
    if said is None or said.weekday() == weekday:
        return None
    # The only day with that weekday within three days of the date said.
    other = said + timedelta(days=(weekday - said.weekday() + 3) % 7 - 3)
    if other < today:
        other += timedelta(days=7)
    return DayQuestion(said, other)


def _nearest_with_number(day: date, number: int) -> date | None:
    around = (
        day + timedelta(days=offset) for offset in range(-_DAY_NUMBER_REACH, _DAY_NUMBER_REACH + 1)
    )
    candidates = [candidate for candidate in around if candidate.day == number]
    return min(candidates, key=lambda candidate: abs(candidate - day), default=None)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
