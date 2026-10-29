"""Each request to the scheduling backend is reported with its duration and outcome."""

from datetime import date

import pytest

from voice_call_agent.observability.backend_timing import TimedSchedulingBackend
from voice_call_agent.observability.call_trace import BackendRequest
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailabilityResult,
    CallOutcome,
    ClosedDay,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend


class OneDayBackend:
    """Answers availability; refuses to close the call, as a backend that is down."""

    async def availability(self, call_id: str, service_id: str, day: date) -> AvailabilityResult:
        return ClosedDay()

    async def close_call(self, call_id: str, outcome: CallOutcome) -> None:
        raise SchedulingBackendUnavailableError("down")


async def test_a_request_is_reported_with_its_outcome_and_the_answer_passes_through() -> None:
    reported: list[BackendRequest] = []
    backend: SchedulingBackend = OneDayBackend()  # type: ignore[assignment]
    timed = TimedSchedulingBackend(backend, reported.append)

    assert await timed.availability("CA1", "haircut", date(2030, 6, 17)) == ClosedDay()
    with pytest.raises(SchedulingBackendUnavailableError):
        await timed.close_call("CA1", CallOutcome.BOOKED)

    assert [(r.operation, r.outcome) for r in reported] == [
        ("availability", "ok"),
        ("close_call", "SchedulingBackendUnavailableError"),
    ]
    assert all(r.duration_ms >= 0 for r in reported)
