"""The start of a second service of the same caller, as close to the first as the schedule
allows: right after it, right before it, or else the nearest free start."""

from datetime import time

from voice_call_agent.booking_flow.back_to_back import back_to_back_start

TEN = time(10, 0)  # The first service: 10:00 to 10:30.


def test_right_after_the_first_when_it_is_free() -> None:
    assert back_to_back_start([time(10, 30), time(11, 0)], TEN, 30, 60) == time(10, 30)


def test_right_before_the_first_when_after_is_taken() -> None:
    # An hour-long second service ending at ten starts at nine.
    assert back_to_back_start([time(9, 0), time(11, 30)], TEN, 30, 60) == time(9, 0)


def test_the_nearest_free_start_after_the_first_when_neither_is_free() -> None:
    # Other callers took the hours around it: their bookings are never moved.
    assert back_to_back_start([time(8, 0), time(14, 0), time(15, 0)], TEN, 30, 60) == time(14, 0)


def test_the_latest_free_start_before_when_nothing_is_free_after() -> None:
    assert back_to_back_start([time(7, 0), time(8, 0)], TEN, 30, 60) == time(8, 0)


def test_no_start_when_the_day_has_none() -> None:
    assert back_to_back_start([], TEN, 30, 60) is None
