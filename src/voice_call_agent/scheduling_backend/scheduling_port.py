"""`SchedulingBackend`: the system of record for appointments, seen from the agent.

The dialog and the guards depend on this protocol, never on a concrete backend. Every method
may raise a `SchedulingBackendError`; business outcomes come back as typed results.
"""

from datetime import date
from typing import Protocol

from voice_call_agent.scheduling_backend.scheduling_models import (
    Appointment,
    AvailabilityResult,
    BookingRequest,
    CallerMessage,
    CallOutcome,
    CancellationRequest,
    RescheduleRequest,
    WriteResult,
)


class SchedulingBackend(Protocol):
    """Reads and writes on the business of an already-resolved call."""

    async def availability(self, call_id: str, service_id: str, day: date) -> AvailabilityResult:
        """Free start times of that day for that service, in the business's local time."""
        ...

    async def upcoming_appointments(self, call_id: str) -> list[Appointment]:
        """Future active appointments of the caller (matched by the call's phone number)."""
        ...

    async def book_appointment(self, request: BookingRequest) -> WriteResult: ...

    async def reschedule_appointment(self, request: RescheduleRequest) -> WriteResult: ...

    async def cancel_appointment(self, request: CancellationRequest) -> WriteResult: ...

    async def leave_message(self, message: CallerMessage) -> None:
        """Deliver a message to the business owner when the agent cannot resolve the request."""
        ...

    async def close_call(self, call_id: str, outcome: CallOutcome) -> None:
        """Close the backend's call record; it lives with the appointments it led to."""
        ...
