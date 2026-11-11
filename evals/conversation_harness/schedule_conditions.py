"""The scheduling backend a golden case runs against: none, or the practice schedule in a state.

The clock is fixed so that "mañana" is always the same day: Monday 26 October 2026, 10:10 in
Caracas, where the practice businesses are.
"""

from datetime import UTC, date, datetime
from uuid import uuid4

from evals.golden_cases import ScheduleCondition
from voice_call_agent.call_session.session_builders import build_browser_session
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.practice_schedule.practice_catalog import load_practice_catalog
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailabilityResult,
    AvailableSlots,
    BookingRequest,
    WriteResult,
)

HARNESS_NOW = datetime(2026, 10, 26, 14, 10, tzinfo=UTC)
"""Monday 10:10 in Caracas (UTC-4): "mañana" is Tuesday 27."""


def harness_clock() -> datetime:
    return HARNESS_NOW


class _SlotTakenBeforeConfirmation(InMemorySchedule):
    """Another caller books the proposed slot just before the confirmation reaches the schedule."""

    async def book_appointment(self, request: BookingRequest) -> WriteResult:
        other = build_browser_session(f"other-caller-{uuid4().hex}")
        await self.resolve_call_business(other)
        await super().book_appointment(
            request.model_copy(update={"call_id": other.call_id, "idempotency_key": uuid4()})
        )
        return await super().book_appointment(request)


class _UnavailableForBookings(InMemorySchedule):
    """Reads answer; every booking times out."""

    async def book_appointment(self, request: BookingRequest) -> WriteResult:
        raise SchedulingBackendUnavailableError("the schedule does not answer in this case")


class _FullyBooked(InMemorySchedule):
    """Every open day has every start taken: the business is open, with no free time left."""

    async def availability(self, call_id: str, service_id: str, day: date) -> AvailabilityResult:
        result = await super().availability(call_id, service_id, day)
        return AvailableSlots(day=day, slots=[]) if isinstance(result, AvailableSlots) else result


def schedule_for(condition: ScheduleCondition, business: str | None) -> InMemorySchedule | None:
    """The practice schedule in the case's state, on the harness clock, where every call reaches
    `business`; `None`: no backend."""
    kinds: dict[ScheduleCondition, type[InMemorySchedule]] = {
        ScheduleCondition.OPEN: InMemorySchedule,
        ScheduleCondition.SLOT_TAKEN: _SlotTakenBeforeConfirmation,
        ScheduleCondition.UNAVAILABLE: _UnavailableForBookings,
        ScheduleCondition.FULLY_BOOKED: _FullyBooked,
    }
    kind = kinds.get(condition)
    if kind is None or business is None:
        return None
    catalog = load_practice_catalog()
    if business not in {known.id for known in catalog.businesses}:
        raise ValueError(f"no practice business {business!r}")
    reached = catalog.model_copy(update={"default_business": business})
    return kind(reached, now=harness_clock)
