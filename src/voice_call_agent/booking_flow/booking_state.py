"""What one call holds while it books: the slot or the times being chosen, and the services the
caller asked for that wait for the one being booked."""

from dataclasses import dataclass
from datetime import date, time

from voice_call_agent.scheduling_backend.scheduling_models import OpeningHours, ServiceOffering


@dataclass(frozen=True)
class Slot:
    """A service, day and start time the backend offered for this call."""

    service: ServiceOffering
    day: date
    start: time


@dataclass(frozen=True)
class TimeChoice:
    """The free starts of a day the caller chooses from, and the start asked for if taken."""

    service: ServiceOffering
    day: date
    starts: list[time]
    taken: time | None
    offered_at_turn: int
    hours: OpeningHours | None
    """The day's opening hours, to say why `taken` is not offered."""
    """The caller's turns when the starts were offered: a start is chosen only after another."""


@dataclass(frozen=True)
class PendingRequest:
    """A service the caller asked for besides the one being booked: the code books it next."""

    service: ServiceOffering
    day: date
    start: time | None
    client_name: str | None
