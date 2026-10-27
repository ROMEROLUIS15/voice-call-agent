"""A booking guard over the practice schedule, with a caller-turn counter the test advances."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from tests.practice_catalogs import MONDAY, TWO_BUSINESSES, barbershop_phone_call, schedule
from voice_call_agent.observability.call_trace import WriteDecision
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend
from voice_call_agent.write_guards.booking_guard import BookingGuard

TUESDAY = MONDAY + timedelta(days=1)
CALL_ID = "CA-barber"


@dataclass
class GuardedCall:
    backend: InMemorySchedule
    guard: BookingGuard
    turns: list[int] = field(default_factory=lambda: [0])
    decisions: list[WriteDecision] = field(default_factory=list)

    def caller_speaks(self) -> None:
        self.turns[0] += 1


async def guarded_call(
    wrap: Callable[[InMemorySchedule], SchedulingBackend] | None = None,
) -> GuardedCall:
    """A resolved barbershop call; `wrap` puts something in front of the schedule (a failure)."""
    practice = schedule()
    await practice.resolve_call_business(barbershop_phone_call(CALL_ID))
    turns = [0]
    decisions: list[WriteDecision] = []
    guard = BookingGuard(
        call_id=CALL_ID,
        catalog=TWO_BUSINESSES.business("barbershop").services,
        backend=wrap(practice) if wrap else practice,
        caller_turns=lambda: turns[0],
        on_decision=decisions.append,
    )
    return GuardedCall(practice, guard, turns, decisions)
