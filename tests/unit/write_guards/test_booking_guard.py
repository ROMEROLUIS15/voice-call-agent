"""Booking proposals validated by code and confirmed only after the caller answered (ADR 0011)."""

from datetime import date, time
from typing import cast
from uuid import UUID, uuid4

from tests.practice_catalogs import MONDAY, barbershop_phone_call
from tests.write_guard_fixtures import CALL_ID, TUESDAY, guarded_call
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    BookingRequest,
    WriteResult,
    WriteSucceeded,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend
from voice_call_agent.write_guards.booking_guard import (
    Booked,
    ConfirmationRefusal,
    ConfirmationRefused,
    ProposalRefusal,
    ProposalRefused,
    Proposed,
)


async def test_a_valid_proposal_is_kept_and_summarized_for_the_read_back() -> None:
    call = await guarded_call()
    proposal = await call.guard.propose("full", TUESDAY, time(11), "Ana Ejemplo")
    assert isinstance(proposal, Proposed)
    assert (proposal.service_name, proposal.day, proposal.start) == (
        "Corte y barba",
        TUESDAY,
        time(11),
    )
    assert [d.outcome for d in call.decisions] == ["proposed"]
    assert await call.backend.upcoming_appointments(CALL_ID) == []  # Nothing written yet.


async def test_proposals_outside_the_catalog_or_the_availability_are_refused() -> None:
    call = await guarded_call()
    saturday, sunday = MONDAY.replace(day=31), MONDAY.replace(day=25)
    assert await call.guard.propose("massage", TUESDAY, time(11), "Ana") == ProposalRefused(
        reason=ProposalRefusal.UNKNOWN_SERVICE
    )
    assert await call.guard.propose("haircut", saturday, time(11), "Ana") == ProposalRefused(
        reason=ProposalRefusal.CLOSED_DAY
    )
    assert await call.guard.propose("haircut", sunday, time(11), "Ana") == ProposalRefused(
        reason=ProposalRefusal.INVALID_DAY
    )
    off_grid = await call.guard.propose("haircut", TUESDAY, time(11, 15), "Ana")
    assert isinstance(off_grid, ProposalRefused)
    assert off_grid.reason is ProposalRefusal.SLOT_NOT_OFFERED
    assert time(11) in off_grid.available_starts


async def test_the_same_proposal_twice_is_one_proposal() -> None:
    call = await guarded_call()
    first = await call.guard.propose("haircut", TUESDAY, time(11), "Ana Ejemplo")
    again = await call.guard.propose("haircut", TUESDAY, time(11), " ana ejemplo")
    assert isinstance(first, Proposed) and isinstance(again, Proposed)
    assert first.proposal_id == again.proposal_id


async def test_a_confirmation_before_the_caller_answers_writes_nothing() -> None:
    call = await guarded_call()
    proposal = await call.guard.propose("haircut", TUESDAY, time(11), "Ana Ejemplo")
    assert isinstance(proposal, Proposed)
    refused = await call.guard.confirm(proposal.proposal_id)
    assert refused == ConfirmationRefused(reason=ConfirmationRefusal.CALLER_HAS_NOT_ANSWERED)
    assert await call.backend.upcoming_appointments(CALL_ID) == []


async def test_a_confirmed_proposal_is_booked_once() -> None:
    call = await guarded_call()
    proposal = await call.guard.propose("haircut", TUESDAY, time(11), "Ana Ejemplo")
    assert isinstance(proposal, Proposed)
    call.caller_speaks()
    booked = await call.guard.confirm(proposal.proposal_id)
    assert isinstance(booked, Booked)
    assert await call.guard.confirm(proposal.proposal_id) == ConfirmationRefused(
        reason=ConfirmationRefusal.ALREADY_CONFIRMED
    )
    [appointment] = await call.backend.upcoming_appointments(CALL_ID)
    assert appointment.id == booked.appointment_id
    assert [d.outcome for d in call.decisions] == ["proposed", "booked", "already_confirmed"]


async def test_an_unknown_proposal_cannot_be_confirmed() -> None:
    call = await guarded_call()
    call.caller_speaks()
    assert await call.guard.confirm(uuid4()) == ConfirmationRefused(
        reason=ConfirmationRefusal.UNKNOWN_PROPOSAL
    )


async def test_a_slot_taken_before_the_confirmation_is_reported_and_not_retried() -> None:
    call = await guarded_call()
    proposal = await call.guard.propose("haircut", TUESDAY, time(11), "Ana Ejemplo")
    assert isinstance(proposal, Proposed)
    await _someone_else_books(call.backend, TUESDAY, time(11))
    call.caller_speaks()
    assert await call.guard.confirm(proposal.proposal_id) == ConfirmationRefused(
        reason="SLOT_CONFLICT"
    )
    assert await call.guard.confirm(proposal.proposal_id) == ConfirmationRefused(
        reason=ConfirmationRefusal.UNKNOWN_PROPOSAL
    )


class _DownOnce:
    """The practice schedule, whose first booking times out after it was written."""

    def __init__(self, practice: InMemorySchedule) -> None:
        self._practice = practice
        self.attempts: list[UUID] = []

    def __getattr__(self, name: str) -> object:
        return getattr(self._practice, name)

    async def book_appointment(self, request: BookingRequest) -> WriteResult:
        self.attempts.append(request.idempotency_key)
        result = await self._practice.book_appointment(request)
        if len(self.attempts) == 1:
            raise SchedulingBackendUnavailableError
        return result


async def test_a_retry_after_the_backend_failed_books_once() -> None:
    flaky: list[_DownOnce] = []

    def down_once(practice: InMemorySchedule) -> SchedulingBackend:
        flaky.append(_DownOnce(practice))
        return cast(SchedulingBackend, flaky[0])  # Delegates the rest of the port.

    call = await guarded_call(down_once)
    proposal = await call.guard.propose("haircut", TUESDAY, time(11), "Ana Ejemplo")
    assert isinstance(proposal, Proposed)
    call.caller_speaks()
    assert await call.guard.confirm(proposal.proposal_id) == ConfirmationRefused(
        reason=ConfirmationRefusal.BACKEND_UNAVAILABLE
    )
    assert isinstance(await call.guard.confirm(proposal.proposal_id), Booked)
    assert flaky[0].attempts == [proposal.proposal_id] * 2  # The same key: one write.
    assert len(await call.backend.upcoming_appointments(CALL_ID)) == 1


async def _someone_else_books(backend: InMemorySchedule, day: date, start: time) -> None:
    await backend.resolve_call_business(barbershop_phone_call("CA-other", "+584129999999"))
    request = BookingRequest(
        call_id="CA-other",
        service_id="haircut",
        day=day,
        start=start,
        client_name="Otra Persona",
        idempotency_key=uuid4(),
    )
    assert isinstance(await backend.book_appointment(request), WriteSucceeded)
