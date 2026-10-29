"""The free starts of a day said as ranges, and why a requested start is not among them.

Worked out from what the backend offers (the free starts), the service's duration and the day's
opening hours: the agent never sees other callers' appointments (constitution §15).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from itertools import pairwise

from voice_call_agent.scheduling_backend.scheduling_models import OpeningHours


@dataclass(frozen=True)
class FreeRange:
    """Starts from `first` to `last`, one every interval: a single start when they are equal."""

    first: time
    last: time


class Unavailable(StrEnum):
    """Why a requested start is not offered."""

    OUTSIDE_HOURS = "outside_hours"
    """The service would start before opening or end after closing."""
    OFF_INTERVAL = "off_interval"
    """Between two offered starts: appointments start only on the interval."""
    DOES_NOT_FIT = "does_not_fit"
    """The time is free, but the service would run into the next appointment."""
    TAKEN = "taken"


def start_interval(starts: Sequence[time]) -> int | None:
    """Minutes between offered starts (the smallest gap), or `None` with fewer than two."""
    gaps = [_minutes(later) - _minutes(earlier) for earlier, later in pairwise(starts)]
    return min(gaps) if gaps else None


def free_ranges(starts: Sequence[time]) -> list[FreeRange]:
    """Consecutive starts at the interval, as one range each."""
    interval = start_interval(starts)
    ranges: list[FreeRange] = []
    for start in starts:
        if ranges and _minutes(start) - _minutes(ranges[-1].last) == interval:
            ranges[-1] = FreeRange(ranges[-1].first, start)
        else:
            ranges.append(FreeRange(start, start))
    return ranges


def nearest_ranges(ranges: Sequence[FreeRange], around: time | None, limit: int) -> list[FreeRange]:
    """At most `limit` ranges, the closest to `around` (the earliest without it), in day order."""
    if around is None or len(ranges) <= limit:
        return list(ranges[:limit])
    target = _minutes(around)

    def distance(free: FreeRange) -> int:
        first, last = _minutes(free.first), _minutes(free.last)
        return 0 if first <= target <= last else min(abs(first - target), abs(last - target))

    return sorted(sorted(ranges, key=distance)[:limit], key=lambda free: free.first)


def why_unavailable(
    requested: time, starts: Sequence[time], duration_min: int, hours: OpeningHours
) -> Unavailable:
    """Why `requested`, not among `starts`, cannot be booked for a service of `duration_min`."""
    start = _minutes(requested)
    if start < _minutes(hours.opens) or start + duration_min > _minutes(hours.closes):
        return Unavailable.OUTSIDE_HOURS
    interval = start_interval(starts)
    if interval is not None and (start - _minutes(hours.opens)) % interval:
        return Unavailable.OFF_INTERVAL
    # After a range's last start the time stays free at least until that service would end.
    if any(_minutes(r.last) < start < _minutes(r.last) + duration_min for r in free_ranges(starts)):
        return Unavailable.DOES_NOT_FIT
    return Unavailable.TAKEN


def _minutes(moment: time) -> int:
    return moment.hour * 60 + moment.minute
