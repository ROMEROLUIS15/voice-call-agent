"""How long each request to the scheduling backend takes, seen from the call.

Wraps the call's `SchedulingBackend`, whichever implements it, and reports each request with its
duration and outcome: the caller waits on it inside a turn, so a slow backend shows up apart from
the model and the voice.
"""

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime

from voice_call_agent.observability.call_trace import BackendRequest
from voice_call_agent.scheduling_backend.scheduling_errors import SchedulingBackendError
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
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend


class TimedSchedulingBackend:
    """A `SchedulingBackend` that reports every request it passes on to `on_request`."""

    def __init__(
        self, backend: SchedulingBackend, on_request: Callable[[BackendRequest], None]
    ) -> None:
        self._backend = backend
        self._on_request = on_request

    async def availability(self, call_id: str, service_id: str, day: date) -> AvailabilityResult:
        return await self._timed(
            "availability", self._backend.availability(call_id, service_id, day)
        )

    async def upcoming_appointments(self, call_id: str) -> list[Appointment]:
        return await self._timed(
            "upcoming_appointments", self._backend.upcoming_appointments(call_id)
        )

    async def book_appointment(self, request: BookingRequest) -> WriteResult:
        return await self._timed("book_appointment", self._backend.book_appointment(request))

    async def reschedule_appointment(self, request: RescheduleRequest) -> WriteResult:
        return await self._timed(
            "reschedule_appointment", self._backend.reschedule_appointment(request)
        )

    async def cancel_appointment(self, request: CancellationRequest) -> WriteResult:
        return await self._timed("cancel_appointment", self._backend.cancel_appointment(request))

    async def leave_message(self, message: CallerMessage) -> None:
        await self._timed("leave_message", self._backend.leave_message(message))

    async def close_call(self, call_id: str, outcome: CallOutcome) -> None:
        await self._timed("close_call", self._backend.close_call(call_id, outcome))

    async def _timed[ResultT](self, operation: str, request: Awaitable[ResultT]) -> ResultT:
        started_at, started = datetime.now(UTC), time.monotonic()
        outcome = "ok"
        try:
            return await request
        except SchedulingBackendError as error:
            outcome = type(error).__name__
            raise
        finally:
            self._on_request(
                BackendRequest(
                    operation=operation,
                    started_at=started_at,
                    duration_ms=(time.monotonic() - started) * 1000,
                    outcome=outcome,
                )
            )
