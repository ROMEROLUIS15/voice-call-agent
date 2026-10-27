"""The practice schedule: business resolution, availability and writes, as the contract has them."""

from datetime import date, time, timedelta
from uuid import uuid4

import pytest

from tests.practice_catalogs import (
    MONDAY,
    barbershop_call,
    barbershop_phone_call,
    barbershop_whatsapp_call,
    schedule,
    spa_phone_call,
)
from voice_call_agent.call_session.business_resolution import (
    AmbiguousBusiness,
    BusinessResolved,
    NoBusinessMatch,
)
from voice_call_agent.call_session.session import CallSession
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.scheduling_backend.scheduling_errors import (
    IdempotencyKeyReusedError,
    SchedulingBackendRejectedRequestError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailableSlots,
    BookingRequest,
    CallerMessage,
    CallOutcome,
    CancellationRequest,
    ClosedDay,
    InvalidAvailabilityRequest,
    NameAndDateProof,
    RescheduleRequest,
    WriteRejected,
    WriteRejectionReason,
    WriteSucceeded,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend

TUESDAY = MONDAY + timedelta(days=1)


def _booking(
    call_id: str, start: time, service_id: str = "haircut", day: date = TUESDAY
) -> BookingRequest:
    return BookingRequest(
        call_id=call_id,
        service_id=service_id,
        day=day,
        start=start,
        client_name="Ana Ejemplo",
        idempotency_key=uuid4(),
    )


async def _resolved(backend: InMemorySchedule, *sessions: CallSession) -> InMemorySchedule:
    for session in sessions:
        await backend.resolve_call_business(session)
    return backend


def _as_port(backend: InMemorySchedule) -> SchedulingBackend:
    return backend  # Type check: the practice schedule honours the port.


async def test_a_call_without_a_dialed_number_reaches_the_default_business() -> None:
    resolution = await schedule().resolve_call_business(barbershop_call())
    assert isinstance(resolution, BusinessResolved)
    assert resolution.business_id == "barbershop"
    assert resolution.context.greeting == "Hola, Barbería Uno."
    assert resolution.context.weekly_hours.sat is None
    assert resolution.context.known_client_first_name is None


async def test_a_listed_number_reaches_its_business_and_the_call_keeps_it() -> None:
    backend = schedule()
    first = await backend.resolve_call_business(spa_phone_call("CA-1"))
    again = await backend.resolve_call_business(barbershop_phone_call("CA-1"))
    assert isinstance(first, BusinessResolved) and isinstance(again, BusinessResolved)
    assert (first.business_id, again.business_id) == ("spa", "spa")


async def test_today_offers_only_starts_after_now_that_fit_before_closing() -> None:
    backend = await _resolved(schedule(), barbershop_call())
    today = await _as_port(backend).availability("practice-1", "haircut", MONDAY)
    long_service = await backend.availability("practice-1", "full", TUESDAY)
    assert isinstance(today, AvailableSlots) and isinstance(long_service, AvailableSlots)
    assert today.slots[0] == time(10, 30)  # Now is 10:10.
    assert long_service.slots[0] == time(9) and long_service.slots[-1] == time(17)


async def test_closed_days_past_days_and_unknown_services_offer_nothing() -> None:
    backend = await _resolved(schedule(), barbershop_call())
    assert await backend.availability("practice-1", "haircut", MONDAY - timedelta(days=1)) == (
        InvalidAvailabilityRequest()
    )
    assert await backend.availability("practice-1", "haircut", MONDAY + timedelta(days=5)) == (
        ClosedDay()
    )
    assert await backend.availability("practice-1", "massage", TUESDAY) == (
        InvalidAvailabilityRequest()
    )


async def test_a_booking_takes_its_slot_and_shows_in_the_callers_appointments() -> None:
    backend = await _resolved(schedule(), barbershop_phone_call())
    result = await backend.book_appointment(_booking("CA-barber", time(9), "full"))
    assert isinstance(result, WriteSucceeded)
    slots = await backend.availability("CA-barber", "haircut", TUESDAY)
    assert isinstance(slots, AvailableSlots)
    assert time(9) not in slots.slots and time(9, 30) not in slots.slots
    assert time(10) in slots.slots
    [appointment] = await backend.upcoming_appointments("CA-barber")
    assert (appointment.id, appointment.service_name) == (result.appointment_id, "Corte y barba")


@pytest.mark.parametrize(
    ("start", "day", "reason"),
    [
        (time(9), TUESDAY, WriteRejectionReason.SLOT_CONFLICT),
        (time(17, 30), TUESDAY, WriteRejectionReason.OUTSIDE_HOURS),
        (time(10), MONDAY + timedelta(days=5), WriteRejectionReason.OUTSIDE_HOURS),
        (time(9), MONDAY, WriteRejectionReason.INVALID_ARGS),
    ],
    ids=["overlaps-a-booking", "runs-past-closing", "closed-day", "already-past"],
)
async def test_a_booking_that_cannot_happen_is_rejected(
    start: time, day: date, reason: WriteRejectionReason
) -> None:
    backend = await _resolved(schedule(), barbershop_phone_call())
    already = await backend.book_appointment(_booking("CA-barber", time(9, 30)))
    assert isinstance(already, WriteSucceeded)
    result = await backend.book_appointment(_booking("CA-barber", start, "full", day))
    assert result == WriteRejected(reason=reason)


async def test_a_retried_booking_is_written_once_and_a_reused_key_is_refused() -> None:
    backend = await _resolved(schedule(), barbershop_phone_call())
    request = _booking("CA-barber", time(11))
    first = await backend.book_appointment(request)
    assert await backend.book_appointment(request) == first
    assert len(await backend.upcoming_appointments("CA-barber")) == 1
    with pytest.raises(IdempotencyKeyReusedError):
        await backend.book_appointment(request.model_copy(update={"start": time(12)}))


async def test_requests_of_an_unknown_call_are_refused() -> None:
    with pytest.raises(SchedulingBackendRejectedRequestError):
        await schedule().availability("never-started", "haircut", TUESDAY)


async def test_an_unverified_caller_needs_the_name_and_date_to_change_an_appointment() -> None:
    backend = await _resolved(schedule(), barbershop_phone_call())
    booked = await backend.book_appointment(_booking("CA-barber", time(11)))
    assert isinstance(booked, WriteSucceeded)

    def reschedule(proof: NameAndDateProof | None) -> RescheduleRequest:
        return RescheduleRequest(
            call_id="CA-barber",
            appointment_id=booked.appointment_id,
            new_day=TUESDAY,
            new_start=time(15),
            identity=proof,
            idempotency_key=uuid4(),
        )

    wrong = NameAndDateProof(client_name="Otra Persona", appointment_day=TUESDAY)
    right = NameAndDateProof(client_name="ana ejemplo ", appointment_day=TUESDAY)
    assert await backend.reschedule_appointment(reschedule(None)) == WriteRejected(
        reason=WriteRejectionReason.IDENTITY_REQUIRED
    )
    assert await backend.reschedule_appointment(reschedule(wrong)) == WriteRejected(
        reason=WriteRejectionReason.IDENTITY_MISMATCH
    )
    assert isinstance(await backend.reschedule_appointment(reschedule(right)), WriteSucceeded)
    [moved] = await backend.upcoming_appointments("CA-barber")
    assert moved.start == time(15)


async def test_a_verified_caller_cancels_and_is_greeted_by_first_name() -> None:
    backend = await _resolved(schedule(), barbershop_whatsapp_call("wacid.1"))
    booked = await backend.book_appointment(_booking("wacid.1", time(11)))
    assert isinstance(booked, WriteSucceeded)
    cancel = CancellationRequest(
        call_id="wacid.1",
        appointment_id=booked.appointment_id,
        identity=None,
        idempotency_key=uuid4(),
    )
    later = await backend.resolve_call_business(barbershop_whatsapp_call("wacid.2"))
    assert isinstance(later, BusinessResolved)
    assert later.context.known_client_first_name == "Ana"
    assert isinstance(await backend.cancel_appointment(cancel), WriteSucceeded)
    assert await backend.upcoming_appointments("wacid.1") == []


async def test_another_callers_appointment_answers_like_a_missing_one() -> None:
    backend = await _resolved(
        schedule(),
        barbershop_phone_call("CA-ana"),
        barbershop_phone_call("CA-other", "+584129999999"),
    )
    booked = await backend.book_appointment(_booking("CA-ana", time(11)))
    assert isinstance(booked, WriteSucceeded)
    cancel = CancellationRequest(
        call_id="CA-other",
        appointment_id=booked.appointment_id,
        identity=None,
        idempotency_key=uuid4(),
    )
    assert await backend.cancel_appointment(cancel) == WriteRejected(
        reason=WriteRejectionReason.NOT_FOUND
    )


async def test_a_spoken_name_resolves_only_to_the_calls_own_business() -> None:
    backend = await _resolved(schedule(), barbershop_call())
    own = await backend.resolve_spoken_business("practice-1", "barbería uno")
    assert isinstance(own, BusinessResolved) and own.business_id == "barbershop"
    assert await backend.resolve_spoken_business("practice-1", "spa dos") == NoBusinessMatch()
    assert await backend.resolve_spoken_business("practice-1", "o") == AmbiguousBusiness(
        candidates=["Barbería Uno", "Spa Dos"]
    )


async def test_messages_stay_with_the_calls_business_and_closing_forgets_the_call() -> None:
    backend = await _resolved(schedule(), spa_phone_call())
    message = CallerMessage(
        call_id="CA-spa", caller_name="Ana", reason="cambio", callback_phone=None
    )
    await backend.leave_message(message)
    await backend.close_call("CA-spa", CallOutcome.MESSAGE_TAKEN)
    assert backend.messages == [("spa", message)]
    assert backend.outcomes == {"CA-spa": CallOutcome.MESSAGE_TAKEN}
    with pytest.raises(SchedulingBackendRejectedRequestError):
        await backend.upcoming_appointments("CA-spa")
