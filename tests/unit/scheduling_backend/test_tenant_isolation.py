"""Cross-tenant attempts: a call of business A never reaches business B's data."""

from datetime import date, time
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tests.in_memory_scheduling_backend import InMemorySchedulingBackend
from voice_call_agent.call_session.session import TenantAlreadyResolvedError
from voice_call_agent.call_session.session_builders import build_whatsapp_session
from voice_call_agent.scheduling_backend.scheduling_models import (
    Appointment,
    BookingRequest,
    CancellationRequest,
    InvalidAvailabilityRequest,
    WriteRejected,
    WriteRejectionReason,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend

CALLER = "+584120000000"
DAY = date(2026, 10, 22)


@pytest.fixture
def backend() -> InMemorySchedulingBackend:
    backend = InMemorySchedulingBackend()
    backend.service_business.update({"haircut-a": "business-a", "massage-b": "business-b"})
    backend.add_appointment(
        "business-a", CALLER, Appointment(id="apt-a", service_name="Corte", day=DAY, start=time(15))
    )
    # The same person is also a client of business B.
    backend.add_appointment(
        "business-b",
        CALLER,
        Appointment(id="apt-b", service_name="Masaje", day=DAY, start=time(10)),
    )
    backend.register_call("call-a", "business-a", CALLER)
    return backend


def _as_port(backend: InMemorySchedulingBackend) -> SchedulingBackend:
    return backend  # Type check: the fake honours the port.


async def test_reads_only_return_the_calls_business(backend: InMemorySchedulingBackend) -> None:
    appointments = await _as_port(backend).upcoming_appointments("call-a")
    assert [a.id for a in appointments] == ["apt-a"]


async def test_another_business_appointment_cannot_be_cancelled(
    backend: InMemorySchedulingBackend,
) -> None:
    request = CancellationRequest(
        call_id="call-a", appointment_id="apt-b", identity=None, idempotency_key=uuid4()
    )
    result = await backend.cancel_appointment(request)
    assert result == WriteRejected(reason=WriteRejectionReason.NOT_FOUND)


async def test_another_business_service_cannot_be_booked(
    backend: InMemorySchedulingBackend,
) -> None:
    request = BookingRequest(
        call_id="call-a",
        service_id="massage-b",
        day=DAY,
        start=time(9),
        client_name="Ana Ejemplo",
        idempotency_key=uuid4(),
    )
    assert await backend.book_appointment(request) == WriteRejected(
        reason=WriteRejectionReason.INVALID_ARGS
    )
    assert isinstance(
        await backend.availability("call-a", "massage-b", DAY), InvalidAvailabilityRequest
    )


def test_a_tenant_proposed_by_the_llm_never_reaches_a_request() -> None:
    tool_arguments = {
        "call_id": "call-a",
        "service_id": "haircut-a",
        "day": "2026-10-22",
        "start": "09:00",
        "client_name": "Ana Ejemplo",
        "idempotency_key": str(uuid4()),
        "business_id": "business-b",  # What a manipulated LLM might add.
    }
    with pytest.raises(ValidationError, match="business_id"):
        BookingRequest.model_validate(tool_arguments)


def test_the_calls_business_is_fixed_once_resolved() -> None:
    session = build_whatsapp_session("wacid.1", "584120000000", "15550001111")
    resolved = session.resolve_business("business-a")
    assert resolved.business_id == "business-a"
    assert resolved.resolve_business("business-a").business_id == "business-a"
    with pytest.raises(TenantAlreadyResolvedError):
        resolved.resolve_business("business-b")
