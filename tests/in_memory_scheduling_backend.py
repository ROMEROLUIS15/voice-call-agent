"""In-memory `SchedulingBackend` with the contract's tenancy semantics (contract §4).

The business of every request comes from the registered call, never from the request. Later
tests of the agent's tools run against it; the real enforcement lives in Cronix (row-level security
and server-side scoping).
"""

from dataclasses import dataclass, field
from datetime import date, time

from voice_call_agent.scheduling_backend.scheduling_models import (
    Appointment,
    AvailabilityResult,
    AvailableSlots,
    BookingRequest,
    CallerMessage,
    CallOutcome,
    CancellationRequest,
    InvalidAvailabilityRequest,
    RescheduleRequest,
    WriteRejected,
    WriteRejectionReason,
    WriteResult,
    WriteSucceeded,
)


@dataclass
class _Call:
    business_id: str
    caller_phone: str


@dataclass
class InMemorySchedulingBackend:
    calls: dict[str, _Call] = field(default_factory=dict)
    service_business: dict[str, str] = field(default_factory=dict)
    appointments: dict[str, tuple[str, str, Appointment]] = field(default_factory=dict)
    """appointment id → (business id, client phone, appointment)."""
    messages: list[tuple[str, CallerMessage]] = field(default_factory=list)

    def register_call(self, call_id: str, business_id: str, caller_phone: str) -> None:
        self.calls[call_id] = _Call(business_id, caller_phone)

    def add_appointment(
        self, business_id: str, client_phone: str, appointment: Appointment
    ) -> None:
        self.appointments[appointment.id] = (business_id, client_phone, appointment)

    async def availability(self, call_id: str, service_id: str, day: date) -> AvailabilityResult:
        if self.service_business.get(service_id) != self.calls[call_id].business_id:
            return InvalidAvailabilityRequest()
        return AvailableSlots(day=day, slots=[time(9), time(9, 30)])

    async def upcoming_appointments(self, call_id: str) -> list[Appointment]:
        call = self.calls[call_id]
        return [
            appointment
            for business_id, phone, appointment in self.appointments.values()
            if business_id == call.business_id and phone == call.caller_phone
        ]

    async def book_appointment(self, request: BookingRequest) -> WriteResult:
        if self.service_business.get(request.service_id) != self.calls[request.call_id].business_id:
            return WriteRejected(reason=WriteRejectionReason.INVALID_ARGS)
        return WriteSucceeded(appointment_id=f"apt-{len(self.appointments) + 1}")

    async def reschedule_appointment(self, request: RescheduleRequest) -> WriteResult:
        return self._own_appointment_or_not_found(request.call_id, request.appointment_id)

    async def cancel_appointment(self, request: CancellationRequest) -> WriteResult:
        return self._own_appointment_or_not_found(request.call_id, request.appointment_id)

    async def leave_message(self, message: CallerMessage) -> None:
        self.messages.append((self.calls[message.call_id].business_id, message))

    async def close_call(self, call_id: str, outcome: CallOutcome) -> None:
        self.calls.pop(call_id, None)

    def _own_appointment_or_not_found(self, call_id: str, appointment_id: str) -> WriteResult:
        call = self.calls[call_id]
        found = self.appointments.get(appointment_id)
        # Another business's appointment answers exactly like a missing one (contract §4.5).
        if found is None or found[0] != call.business_id or found[1] != call.caller_phone:
            return WriteRejected(reason=WriteRejectionReason.NOT_FOUND)
        return WriteSucceeded(appointment_id=appointment_id)
