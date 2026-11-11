"""The start of a second service of the same caller on the same day, as close to the first as
the schedule allows.

The free starts come from the scheduling backend, which already leaves out every start whose
service would overlap another booking or end after closing: another caller's booking is never
moved. Each service lasts what its catalog entry says.
"""

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta

_ANY_DAY = date(2000, 1, 1)
"""Only the time of day matters: the two services are on the same day."""


def back_to_back_start(
    free: Sequence[time], first_start: time, first_minutes: int, second_minutes: int
) -> time | None:
    """Right after the first, else right before it, else the nearest free start after it, else
    the latest before it; `None` when the day has no free start."""
    after = _shifted(first_start, first_minutes)
    before = _shifted(first_start, -second_minutes)
    if after in free:
        return after
    if before in free:
        return before
    later = [start for start in free if start > first_start]
    if later:
        return min(later)
    earlier = [start for start in free if start < first_start]
    return max(earlier) if earlier else None


def _shifted(moment: time, minutes: int) -> time:
    return (datetime.combine(_ANY_DAY, moment) + timedelta(minutes=minutes)).time()
