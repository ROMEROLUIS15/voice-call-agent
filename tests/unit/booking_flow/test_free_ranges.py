"""Free starts said as ranges, and why a requested start is not offered, from the starts alone."""

from datetime import time

from voice_call_agent.booking_flow.free_ranges import (
    FreeRange,
    Unavailable,
    free_ranges,
    nearest_ranges,
    start_interval,
    why_unavailable,
)
from voice_call_agent.scheduling_backend.scheduling_models import OpeningHours

HOURS = OpeningHours(opens=time(8, 0), closes=time(12, 0))
# 30-minute starts with 09:30 to 10:30 missing: an appointment from 10:00 to 11:00 for a
# 30-minute service blocks 10:00 and 10:30; a 60-minute one would also block 09:30.
STARTS = [time(8, 0), time(8, 30), time(9, 0), time(11, 0), time(11, 30)]


def test_consecutive_starts_form_one_range_and_a_gap_starts_another() -> None:
    assert start_interval(STARTS) == 30
    assert free_ranges(STARTS) == [
        FreeRange(time(8, 0), time(9, 0)),
        FreeRange(time(11, 0), time(11, 30)),
    ]


def test_a_lone_start_is_its_own_range_and_has_no_interval() -> None:
    assert free_ranges([time(15, 0)]) == [FreeRange(time(15, 0), time(15, 0))]
    assert start_interval([time(15, 0)]) is None
    assert free_ranges([]) == []


def test_each_reason_a_requested_start_is_not_offered() -> None:
    def why(requested: time, duration_min: int = 60) -> Unavailable:
        return why_unavailable(requested, STARTS, duration_min, HOURS)

    assert why(time(7, 30)) is Unavailable.OUTSIDE_HOURS  # Before opening.
    assert why(time(11, 30), 60) is Unavailable.OUTSIDE_HOURS  # Would end after 12:00.
    assert why(time(8, 15)) is Unavailable.OFF_INTERVAL  # Starts are every 30 minutes.
    assert why(time(9, 30)) is Unavailable.DOES_NOT_FIT  # Free, but runs into 10:00.
    assert why(time(10, 0), 30) is Unavailable.TAKEN


def test_only_the_ranges_closest_to_the_time_asked_for_are_kept_in_day_order() -> None:
    lone = [FreeRange(time(h, 0), time(h, 0)) for h in (8, 10, 12, 14, 16, 17)]
    assert nearest_ranges(lone, None, 4) == lone[:4]  # Nothing asked for: the earliest.
    assert nearest_ranges(lone, time(15, 0), 3) == lone[3:]  # 14, 16, 17: in day order.
    assert nearest_ranges(lone[:2], time(15, 0), 4) == lone[:2]  # Few enough: all of them.
    within = [FreeRange(time(8, 0), time(9, 0)), FreeRange(time(11, 0), time(11, 30))]
    assert nearest_ranges(within, time(8, 30), 1) == within[:1]  # Inside a range: distance 0.
