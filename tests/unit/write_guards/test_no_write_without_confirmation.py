"""Property: whatever the model does, no booking is written without a confirmation the caller
answered, and no proposal is written twice (INV-2, INV-6)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from typing import cast
from uuid import UUID, uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.write_guard_fixtures import CALL_ID, TUESDAY, GuardedCall, guarded_call
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.scheduling_backend.scheduling_models import (
    BookingRequest,
    WriteResult,
    WriteSucceeded,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend
from voice_call_agent.write_guards.booking_guard import Proposed


@dataclass(frozen=True)
class _Propose:
    service_id: str
    start: time


@dataclass(frozen=True)
class _CallerSpeaks:
    pass


@dataclass(frozen=True)
class _Confirm:
    proposal_index: int
    """Which earlier proposal the model names; past the end: an id it made up."""


_steps = st.lists(
    st.one_of(
        st.builds(
            _Propose,
            st.sampled_from(["haircut", "full", "massage"]),
            st.sampled_from([time(9), time(9, 30), time(10), time(17, 30)]),
        ),
        st.just(_CallerSpeaks()),
        st.builds(_Confirm, st.integers(min_value=0, max_value=6)),
    ),
    max_size=25,
)


class _RecordingBackend:
    """The practice schedule, recording each booking with the caller turns at that moment."""

    def __init__(self, practice: InMemorySchedule, caller_turns: Callable[[], int]) -> None:
        self._practice = practice
        self._caller_turns = caller_turns
        self.bookings: list[tuple[UUID, int, WriteResult]] = []

    def __getattr__(self, name: str) -> object:
        return getattr(self._practice, name)

    async def book_appointment(self, request: BookingRequest) -> WriteResult:
        result = await self._practice.book_appointment(request)
        self.bookings.append((request.idempotency_key, self._caller_turns(), result))
        return result


async def _play(steps: list[object]) -> None:
    calls: list[GuardedCall] = []
    recorders: list[_RecordingBackend] = []

    def recording(practice: InMemorySchedule) -> SchedulingBackend:
        recorders.append(_RecordingBackend(practice, lambda: calls[0].turns[0]))
        return cast(SchedulingBackend, recorders[0])  # Delegates the rest of the port.

    call = await guarded_call(recording)
    calls.append(call)
    proposed_at: dict[UUID, int] = {}
    for step in steps:
        match step:
            case _Propose(service_id, start):
                result = await call.guard.propose(service_id, TUESDAY, start, "Ana Ejemplo")
                if isinstance(result, Proposed):
                    proposed_at.setdefault(result.proposal_id, call.turns[0])
            case _CallerSpeaks():
                call.caller_speaks()
            case _Confirm(index):
                ids = list(proposed_at)
                await call.guard.confirm(ids[index] if index < len(ids) else uuid4())
    written = [
        (key, turn)
        for key, turn, result in recorders[0].bookings
        if isinstance(result, WriteSucceeded)
    ]
    for key, turn in written:
        assert key in proposed_at, "a booking the guard never proposed"
        assert turn > proposed_at[key], "a booking before the caller answered its proposal"
    assert len({key for key, _ in written}) == len(written), "a proposal written twice"
    assert len(await call.backend.upcoming_appointments(CALL_ID)) == len(written)


@settings(max_examples=200, deadline=None)
@given(_steps)
def test_no_booking_without_an_answered_confirmation_nor_twice(steps: list[object]) -> None:
    asyncio.run(_play(steps))
