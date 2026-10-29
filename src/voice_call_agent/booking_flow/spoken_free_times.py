"""The free starts of the day a caller chooses from, in words: as the model's task states them,
and as the code says them to the caller on entering the choose_time step.

The code says them because the model, rewording the ranges, misstated where they end in a
practice call: what the caller hears comes from the starts the backend offered.
"""

from voice_call_agent.booking_flow.booking_steps import TimeChoice
from voice_call_agent.booking_flow.free_ranges import (
    FreeRange,
    Unavailable,
    free_ranges,
    nearest_ranges,
    start_interval,
    why_unavailable,
)
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.conversation_content.spoken_moments import spoken_day, spoken_time
from voice_call_agent.write_guards.booking_guard import clock_time

MAX_SAID_RANGES = 4
"""The free times said to the caller at most: a long list is not remembered on the phone."""


def free_times_for_model(content: ConversationContent, choice: TimeChoice) -> str:
    """Every free start as ranges, said aloud and as the function takes them."""
    choices = content.booking_flow.choices
    said = [
        choices.free_time.format(spoken=spoken_time(content, r.first), clock=clock_time(r.first))
        if r.first == r.last
        else choices.free_range.format(
            first=spoken_time(content, r.first),
            first_clock=clock_time(r.first),
            last=spoken_time(content, r.last),
            last_clock=clock_time(r.last),
        )
        for r in free_ranges(choice.starts)
    ]
    interval = start_interval(choice.starts)
    every = "" if interval is None else choices.interval.format(minutes=interval)
    return "; ".join(said) + every


def requested_for_model(content: ConversationContent, choice: TimeChoice) -> str:
    """Why the time the caller asked for is not offered, or nothing if none was asked."""
    reason = _unavailable(choice)
    if reason is None or choice.taken is None:
        return ""
    texts, hours = content.booking_flow.choices.requested, choice.hours
    by_reason = {
        Unavailable.OUTSIDE_HOURS: texts.outside_hours,
        Unavailable.OFF_INTERVAL: texts.off_interval,
        Unavailable.DOES_NOT_FIT: texts.does_not_fit,
        Unavailable.TAKEN: texts.taken,
    }
    return by_reason[reason].format(
        time=spoken_time(content, choice.taken),
        duration=choice.service.duration_min,
        opens=spoken_time(content, hours.opens) if hours else "",
        closes=spoken_time(content, hours.closes) if hours else "",
        interval=start_interval(choice.starts) or "",
    )


def free_times_said(content: ConversationContent, choice: TimeChoice) -> str:
    """What the caller hears: why the time asked for is not offered, then the free times closest
    to it, at most `MAX_SAID_RANGES`."""
    said = content.booking_flow.choices.said
    every = free_ranges(choice.starts)
    nearest = nearest_ranges(every, choice.taken, MAX_SAID_RANGES)
    times = [_said_range(content, free) for free in nearest]
    joined = ", ".join(times[:-1]) + said.last_joiner + times[-1] if len(times) > 1 else times[0]
    if len(nearest) < len(every):
        joined += said.more
    return said.offer.format(
        reason=_said_reason(content, choice),
        day=spoken_day(content, choice.day),
        times=joined,
    )


def _said_range(content: ConversationContent, free: FreeRange) -> str:
    said = content.booking_flow.choices.said
    if free.first == free.last:
        return said.free_time.format(time=spoken_time(content, free.first))
    return said.free_range.format(
        first=spoken_time(content, free.first), last=spoken_time(content, free.last)
    )


def _said_reason(content: ConversationContent, choice: TimeChoice) -> str:
    reason = _unavailable(choice)
    if reason is None or choice.taken is None:
        return ""
    texts, hours = content.booking_flow.choices.said.reasons, choice.hours
    by_reason = {
        Unavailable.OUTSIDE_HOURS: texts.outside_hours,
        Unavailable.OFF_INTERVAL: texts.off_interval,
        Unavailable.DOES_NOT_FIT: texts.does_not_fit,
        Unavailable.TAKEN: texts.taken,
    }
    return by_reason[reason].format(
        time=spoken_time(content, choice.taken),
        opens=spoken_time(content, hours.opens) if hours else "",
        closes=spoken_time(content, hours.closes) if hours else "",
    )


def _unavailable(choice: TimeChoice) -> Unavailable | None:
    if choice.taken is None:
        return None
    if choice.hours is None:
        return Unavailable.TAKEN
    return why_unavailable(choice.taken, choice.starts, choice.service.duration_min, choice.hours)
