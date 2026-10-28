"""In-memory `SchedulingBackend` and `BusinessResolver` over the practice catalog.

Like the contract's backend, it registers each call with its business when the business is
resolved and reads the business of every later request from that record (contract §4).
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from itertools import count
from typing import TypeVar
from uuid import UUID

from voice_call_agent.call_session.business_resolution import (
    AmbiguousBusiness,
    BusinessResolved,
    CallStartResolution,
    NoBusinessMatch,
    SpokenNameResolution,
)
from voice_call_agent.call_session.session import CallSession
from voice_call_agent.practice_schedule.opening_hours import (
    START_INTERVAL_MIN,
    Interval,
    end_of,
    fits,
    free_starts,
    hours_on,
    overlaps,
)
from voice_call_agent.practice_schedule.practice_catalog import PracticeBusiness, PracticeCatalog
from voice_call_agent.scheduling_backend.scheduling_errors import (
    IdempotencyKeyReusedError,
    SchedulingBackendRejectedRequestError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    Appointment,
    AvailabilityResult,
    AvailableSlots,
    BookingRequest,
    CallerMessage,
    CallOutcome,
    CancellationRequest,
    ClosedDay,
    IdentityProof,
    InvalidAvailabilityRequest,
    NameAndDateProof,
    RescheduleRequest,
    ServiceOffering,
    WriteRejected,
    WriteRejectionReason,
    WriteResult,
    WriteSucceeded,
)

Clock = Callable[[], datetime]
_Write = TypeVar("_Write", BookingRequest, RescheduleRequest, CancellationRequest)


@dataclass(frozen=True)
class _Call:
    business: PracticeBusiness
    caller_phone: str | None
    identity_verified: bool


@dataclass
class _Booking:
    appointment_id: str
    business_id: str
    service: ServiceOffering
    day: date
    slot: Interval
    client_name: str
    client_phone: str | None

    def appointment(self) -> Appointment:
        return Appointment(
            id=self.appointment_id, service_name=self.service.name, day=self.day, start=self.slot[0]
        )


class InMemorySchedule:
    """The practice schedule: fictitious businesses, appointments kept in memory."""

    def __init__(self, catalog: PracticeCatalog, now: Clock = lambda: datetime.now(UTC)) -> None:
        self._catalog = catalog
        self._now = now
        self._calls: dict[str, _Call] = {}
        self._bookings: list[_Booking] = []
        self._results: dict[UUID, tuple[object, WriteResult]] = {}
        self._appointment_numbers = count(1)
        self.messages: list[tuple[str, CallerMessage]] = []
        self.outcomes: dict[str, CallOutcome] = {}

    async def resolve_call_business(self, session: CallSession) -> CallStartResolution:
        """The business that lists the dialed number, or the default one; fixed for the call."""
        known = self._calls.get(session.call_id)
        business = (
            known.business if known else self._catalog.business_for_number(session.dialed_phone)
        )
        self._calls[session.call_id] = _Call(
            business, session.caller_phone, session.identity_verified
        )
        first_name = (
            self._known_first_name(business, session) if session.identity_verified else None
        )
        return BusinessResolved(business_id=business.id, context=business.context(first_name))

    async def resolve_spoken_business(self, call_id: str, spoken_name: str) -> SpokenNameResolution:
        call = self._call(call_id)
        wanted = spoken_name.strip().casefold()
        matches = [b for b in self._catalog.businesses if wanted and wanted in b.name.casefold()]
        if len(matches) > 1:
            return AmbiguousBusiness(candidates=[business.name for business in matches[:3]])
        if matches == [call.business]:  # A call's business never changes (INV-1).
            return BusinessResolved(
                business_id=call.business.id, context=call.business.context(None)
            )
        return NoBusinessMatch()

    async def availability(self, call_id: str, service_id: str, day: date) -> AvailabilityResult:
        business = self._call(call_id).business
        service = business.service(service_id)
        today, now = self._local_now(business)
        if service is None or day < today:
            return InvalidAvailabilityRequest()
        hours = hours_on(business, day)
        if hours is None:
            return ClosedDay()
        starts = free_starts(
            hours,
            duration_min=service.duration_min,
            step_min=START_INTERVAL_MIN,
            booked=self._booked(business.id, day),
            not_before=now if day == today else None,
        )
        return AvailableSlots(day=day, slots=starts)

    async def upcoming_appointments(self, call_id: str) -> list[Appointment]:
        call = self._call(call_id)
        today, now = self._local_now(call.business)
        return [
            booking.appointment()
            for booking in sorted(self._bookings, key=lambda b: (b.day, b.slot))
            if booking.business_id == call.business.id
            and booking.client_phone is not None
            and booking.client_phone == call.caller_phone
            and (booking.day, booking.slot[0]) >= (today, now)
        ]

    async def book_appointment(self, request: BookingRequest) -> WriteResult:
        return self._once(request, self._book)

    async def reschedule_appointment(self, request: RescheduleRequest) -> WriteResult:
        return self._once(request, self._reschedule)

    async def cancel_appointment(self, request: CancellationRequest) -> WriteResult:
        return self._once(request, self._cancel)

    async def leave_message(self, message: CallerMessage) -> None:
        self.messages.append((self._call(message.call_id).business.id, message))

    async def close_call(self, call_id: str, outcome: CallOutcome) -> None:
        self._calls.pop(call_id, None)
        self.outcomes[call_id] = outcome

    def _once(self, request: _Write, write: Callable[[_Write], WriteResult]) -> WriteResult:
        """A repeated key gets its stored result; the same key with another body is refused
        (contract §5)."""
        stored = self._results.get(request.idempotency_key)
        if stored is not None:
            previous, result = stored
            if previous != request:
                raise IdempotencyKeyReusedError
            return result
        result = write(request)
        self._results[request.idempotency_key] = (request, result)
        return result

    def _book(self, request: BookingRequest) -> WriteResult:
        call = self._call(request.call_id)
        service = call.business.service(request.service_id)
        if service is None:
            return WriteRejected(reason=WriteRejectionReason.INVALID_ARGS)
        slot = self._free_slot(call.business, service, request.day, request.start, moving=None)
        if isinstance(slot, WriteRejectionReason):
            return WriteRejected(reason=slot)
        booking = _Booking(
            appointment_id=f"practice-apt-{next(self._appointment_numbers)}",
            business_id=call.business.id,
            service=service,
            day=request.day,
            slot=slot,
            client_name=request.client_name,
            client_phone=call.caller_phone,
        )
        self._bookings.append(booking)
        return WriteSucceeded(appointment_id=booking.appointment_id)

    def _reschedule(self, request: RescheduleRequest) -> WriteResult:
        call = self._call(request.call_id)
        booking = self._own_booking(call, request.appointment_id, request.identity)
        if isinstance(booking, WriteRejected):
            return booking
        slot = self._free_slot(
            call.business, booking.service, request.new_day, request.new_start, moving=booking
        )
        if isinstance(slot, WriteRejectionReason):
            return WriteRejected(reason=slot)
        booking.day, booking.slot = request.new_day, slot
        return WriteSucceeded(appointment_id=booking.appointment_id)

    def _cancel(self, request: CancellationRequest) -> WriteResult:
        call = self._call(request.call_id)
        booking = self._own_booking(call, request.appointment_id, request.identity)
        if isinstance(booking, WriteRejected):
            return booking
        self._bookings.remove(booking)
        return WriteSucceeded(appointment_id=booking.appointment_id)

    def _free_slot(
        self,
        business: PracticeBusiness,
        service: ServiceOffering,
        day: date,
        start: time,
        moving: _Booking | None,
    ) -> Interval | WriteRejectionReason:
        """The appointment's interval if it can be booked; otherwise why not."""
        today, now = self._local_now(business)
        if (day, start) < (today, now):
            return WriteRejectionReason.INVALID_ARGS
        hours = hours_on(business, day)
        end = end_of(start, service.duration_min)
        if hours is None or end is None or not fits(hours, (start, end)):
            return WriteRejectionReason.OUTSIDE_HOURS
        if overlaps((start, end), self._booked(business.id, day, moving)):
            return WriteRejectionReason.SLOT_CONFLICT
        return start, end

    def _own_booking(
        self, call: _Call, appointment_id: str, identity: IdentityProof | None
    ) -> _Booking | WriteRejected:
        booking = next((b for b in self._bookings if b.appointment_id == appointment_id), None)
        # Another business's or another caller's appointment answers exactly like a missing one
        # (contract §4.5).
        if (
            booking is None
            or booking.business_id != call.business.id
            or booking.client_phone is None
            or booking.client_phone != call.caller_phone
        ):
            return WriteRejected(reason=WriteRejectionReason.NOT_FOUND)
        if call.identity_verified:
            return booking
        if identity is None:
            return WriteRejected(reason=WriteRejectionReason.IDENTITY_REQUIRED)
        if not _proves(identity, booking):
            return WriteRejected(reason=WriteRejectionReason.IDENTITY_MISMATCH)
        return booking

    def _booked(
        self, business_id: str, day: date, moving: _Booking | None = None
    ) -> list[Interval]:
        return [
            b.slot
            for b in self._bookings
            if b.business_id == business_id and b.day == day and b is not moving
        ]

    def _known_first_name(self, business: PracticeBusiness, session: CallSession) -> str | None:
        """Only the first name of a client the business already has (constitution §4)."""
        names = [
            b.client_name
            for b in self._bookings
            if b.business_id == business.id and b.client_phone == session.caller_phone
        ]
        return names[-1].split()[0] if names and names[-1].strip() else None

    def _local_now(self, business: PracticeBusiness) -> tuple[date, time]:
        local = self._now().astimezone(business.zone)
        return local.date(), local.time()

    def _call(self, call_id: str) -> _Call:
        call = self._calls.get(call_id)
        if call is None:
            raise SchedulingBackendRejectedRequestError(f"unknown call {call_id}")
        return call


def _proves(identity: IdentityProof, booking: _Booking) -> bool:
    """The practice schedule sends no one-time codes, so only the name and the date prove it."""
    return (
        isinstance(identity, NameAndDateProof)
        and identity.client_name.strip().casefold() == booking.client_name.strip().casefold()
        and identity.appointment_day == booking.day
    )
