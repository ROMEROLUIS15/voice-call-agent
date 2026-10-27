"""Cross-tenant attempts: a call of business A never reaches business B's data.

They run against the practice schedule, which follows the contract's tenancy (contract §4); the
real enforcement for Cronix lives in Cronix (row-level security and server-side scoping).
"""

from datetime import time, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tests.practice_catalogs import MONDAY, barbershop_phone_call, schedule, spa_phone_call
from voice_call_agent.call_session.session import TenantAlreadyResolvedError
from voice_call_agent.call_session.session_builders import build_whatsapp_session
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.scheduling_backend.scheduling_models import (
    BookingRequest,
    CancellationRequest,
    InvalidAvailabilityRequest,
    WriteRejected,
    WriteRejectionReason,
    WriteSucceeded,
)

LATER = MONDAY + timedelta(days=1)


def _booking(call_id: str, service_id: str) -> BookingRequest:
    return BookingRequest(
        call_id=call_id,
        service_id=service_id,
        day=MONDAY if service_id == "massage" else LATER,
        start=time(15),
        client_name="Ana Ejemplo",
        idempotency_key=uuid4(),
    )


@pytest.fixture
async def backend() -> InMemorySchedule:
    """The same person is a client of both businesses and calls each of them."""
    backend = schedule()
    await backend.resolve_call_business(barbershop_phone_call("call-a"))
    await backend.resolve_call_business(spa_phone_call("call-b"))
    assert isinstance(await backend.book_appointment(_booking("call-a", "haircut")), WriteSucceeded)
    assert isinstance(await backend.book_appointment(_booking("call-b", "massage")), WriteSucceeded)
    return backend


async def test_reads_only_return_the_calls_business(backend: InMemorySchedule) -> None:
    [appointment] = await backend.upcoming_appointments("call-a")
    assert appointment.service_name == "Corte"


async def test_another_business_appointment_cannot_be_cancelled(backend: InMemorySchedule) -> None:
    [spa_appointment] = await backend.upcoming_appointments("call-b")
    request = CancellationRequest(
        call_id="call-a",
        appointment_id=spa_appointment.id,
        identity=None,
        idempotency_key=uuid4(),
    )
    assert await backend.cancel_appointment(request) == WriteRejected(
        reason=WriteRejectionReason.NOT_FOUND
    )


async def test_another_business_service_cannot_be_booked(backend: InMemorySchedule) -> None:
    assert await backend.book_appointment(_booking("call-a", "massage")) == WriteRejected(
        reason=WriteRejectionReason.INVALID_ARGS
    )
    assert isinstance(
        await backend.availability("call-a", "massage", MONDAY), InvalidAvailabilityRequest
    )


def test_a_tenant_proposed_by_the_llm_never_reaches_a_request() -> None:
    tool_arguments = {
        "call_id": "call-a",
        "service_id": "haircut",
        "day": "2026-10-27",
        "start": "09:00",
        "client_name": "Ana Ejemplo",
        "idempotency_key": str(uuid4()),
        "business_id": "spa",  # What a manipulated LLM might add.
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
