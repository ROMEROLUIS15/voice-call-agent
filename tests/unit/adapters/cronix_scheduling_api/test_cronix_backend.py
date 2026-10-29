"""Cronix's phone agent API through a local stand-in that checks every signature."""

import asyncio
import hashlib
import hmac
import time
from collections.abc import AsyncIterator, Callable
from datetime import date
from datetime import time as clock
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from pydantic import SecretStr

from voice_call_agent.adapters.cronix_scheduling_api.cronix_backend import CronixSchedulingBackend
from voice_call_agent.adapters.cronix_scheduling_api.signed_api import SignedApi
from voice_call_agent.call_session.business_resolution import BusinessResolved, UnknownLine
from voice_call_agent.call_session.session_builders import (
    build_twilio_session,
    build_whatsapp_session,
)
from voice_call_agent.scheduling_backend.scheduling_errors import (
    IdempotencyKeyReusedError,
    SchedulingBackendRejectedRequestError,
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailableSlots,
    BookingRequest,
    CallOutcome,
    ClosedDay,
    InvalidAvailabilityRequest,
    WriteRejected,
    WriteRejectionReason,
    WriteSucceeded,
)
from voice_call_agent.settings.sections import SchedulingApiSettings

SECRET = "test-signing-secret"
KEY = UUID("00000000-0000-4000-8000-000000000001")
START = {
    "success": True,
    "business": {
        "id": "b1",
        "name": "Barbería Prueba",
        "timezone": "America/Caracas",
        "currency": "VES",
    },
    "services": [
        {"id": "s1", "name": "Corte", "duration_min": 30, "price": 10},
        {"id": "s2", "name": "Consulta", "duration_min": 60, "price": None},
    ],
    "working_hours": {"mon": ["09:00", "18:00"], "sun": None},
    "known_client": None,
}

Reply = Callable[[str, dict[str, Any] | None], tuple[int, dict[str, Any] | None]]


class FakeCronixApi:
    """Answers as `reply` says, after refusing any request whose signature does not match."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any] | None, str | None]] = []
        self.reply: Reply = lambda route, body: (200, {"success": True})
        self.delay_s = 0.0

    async def handle(self, request: web.Request) -> web.Response:
        raw = await request.text()
        route = request.path_qs[request.path_qs.index("/v1/") :]
        timestamp = request.headers.get("X-Cronix-Timestamp", "")
        expected = hmac.new(
            SECRET.encode(), f"{timestamp}.{request.method}.{route}.{raw}".encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("X-Cronix-Signature", "")):
            return web.Response(status=401)
        body = await request.json() if raw else None
        self.requests.append((request.method, route, body, request.headers.get("Idempotency-Key")))
        await asyncio.sleep(self.delay_s)
        status, payload = self.reply(route, body)
        return web.json_response(payload, status=status) if payload else web.Response(status=status)


@pytest.fixture
async def cronix() -> AsyncIterator[tuple[FakeCronixApi, CronixSchedulingBackend]]:
    api = FakeCronixApi()
    app = web.Application()
    app.router.add_route("*", "/functions/phone-agent-api/{tail:.*}", api.handle)
    server = TestServer(app)
    await server.start_server()
    settings = SchedulingApiSettings(
        base_url=str(server.make_url("/functions/phone-agent-api")),
        signing_secret=SecretStr(SECRET),
        read_timeout_seconds=0.5,
        write_timeout_seconds=0.5,
    )
    yield api, CronixSchedulingBackend(SignedApi(settings), lambda name: f"Hola, {name}.")
    await server.close()


async def test_a_call_starts_by_its_dialed_number_and_brings_the_business_context(
    cronix: tuple[FakeCronixApi, CronixSchedulingBackend],
) -> None:
    api, backend = cronix
    api.reply = lambda route, body: (200, START)
    resolution = await backend.resolve_call_business(
        build_twilio_session("CA1", "+584121234567", "+13055550101")
    )
    assert isinstance(resolution, BusinessResolved) and resolution.business_id == "b1"
    context = resolution.context
    assert (context.greeting, context.currency, context.known_client_first_name) == (
        "Hola, Barbería Prueba.",
        "VES",
        None,
    )
    assert [s.price for s in context.services] == [Decimal("10"), None]
    assert context.weekly_hours.mon is not None and context.weekly_hours.sun is None
    [(method, route, body, _)] = api.requests
    assert (method, route) == ("POST", "/v1/calls/start")
    assert body == {
        "call_sid": "CA1",
        "channel": "twilio",
        "to": "+13055550101",
        "from": "+584121234567",
    }


async def test_an_unknown_line_and_a_whatsapp_call_are_not_resolved(
    cronix: tuple[FakeCronixApi, CronixSchedulingBackend],
) -> None:
    api, backend = cronix
    api.reply = lambda route, body: (200, {"success": False, "error": "UNKNOWN_LINE"})
    session = build_twilio_session("CA1", "+584121234567", "+19999999999")
    assert isinstance(await backend.resolve_call_business(session), UnknownLine)
    whatsapp = build_whatsapp_session("wa1", "+584121234567", "+13055550101")
    api.reply = lambda route, body: (200, {"success": False, "error": "INVALID_ARGS"})
    with pytest.raises(SchedulingBackendRejectedRequestError):
        await backend.resolve_call_business(whatsapp)  # v1 serves the phone line only.
    assert api.requests[-1][2] is not None and api.requests[-1][2]["channel"] == "whatsapp"


async def test_availability_signs_its_query_and_reads_slots_and_closed_days(
    cronix: tuple[FakeCronixApi, CronixSchedulingBackend],
) -> None:
    api, backend = cronix
    api.reply = lambda route, body: (
        200,
        {"success": True, "date": "2030-06-17", "slots": ["09:00", "11:30"]},
    )
    result = await backend.availability("CA1", "s1", date(2030, 6, 17))
    assert result == AvailableSlots(day=date(2030, 6, 17), slots=[clock(9), clock(11, 30)])
    assert api.requests[0][1] == "/v1/availability?call_sid=CA1&service_id=s1&date=2030-06-17"
    api.reply = lambda route, body: (200, {"success": False, "error": "CLOSED_DAY"})
    assert await backend.availability("CA1", "s1", date(2030, 6, 16)) == ClosedDay()
    api.reply = lambda route, body: (200, {"success": False, "error": "NOT_FOUND"})
    assert (
        await backend.availability("CA1", "s1", date(2030, 6, 17)) == InvalidAvailabilityRequest()
    )


def _booking() -> BookingRequest:
    return BookingRequest(
        call_id="CA1",
        service_id="s1",
        day=date(2030, 6, 17),
        start=clock(10),
        client_name="Ana Ejemplo",
        idempotency_key=KEY,
    )


async def test_a_booking_carries_its_idempotency_key_and_reads_the_outcome(
    cronix: tuple[FakeCronixApi, CronixSchedulingBackend],
) -> None:
    api, backend = cronix
    api.reply = lambda route, body: (200, {"success": True, "appointment_id": "a1"})
    assert await backend.book_appointment(_booking()) == WriteSucceeded(appointment_id="a1")
    [(_, route, body, key)] = api.requests
    assert (route, key) == ("/v1/appointments", str(KEY))
    assert body == {
        "call_sid": "CA1",
        "service_id": "s1",
        "date": "2030-06-17",
        "time": "10:00",
        "client_name": "Ana Ejemplo",
    }
    api.reply = lambda route, body: (200, {"success": False, "error": "OUTSIDE_HOURS"})
    assert await backend.book_appointment(_booking()) == WriteRejected(
        reason=WriteRejectionReason.OUTSIDE_HOURS
    )
    api.reply = lambda route, body: (409, {"success": False, "error": "IDEMPOTENCY_MISMATCH"})
    with pytest.raises(IdempotencyKeyReusedError):
        await backend.book_appointment(_booking())


async def test_a_busy_or_slow_api_is_retried_once_with_the_same_key(
    cronix: tuple[FakeCronixApi, CronixSchedulingBackend],
) -> None:
    api, backend = cronix
    answers = iter(
        [
            (503, {"success": False, "error": "IN_PROGRESS"}),
            (200, {"success": True, "appointment_id": "a1"}),
        ]
    )
    api.reply = lambda route, body: next(answers)
    assert await backend.book_appointment(_booking()) == WriteSucceeded(appointment_id="a1")
    assert [key for *_, key in api.requests] == [str(KEY), str(KEY)]

    api.requests.clear()
    api.reply = lambda route, body: (503, {"success": False, "error": "UNAVAILABLE"})
    with pytest.raises(SchedulingBackendUnavailableError):
        await backend.book_appointment(_booking())
    assert len(api.requests) == 2  # Once, then given up: the caller is waiting.

    api.reply = lambda route, body: (200, {"success": True, "date": "2030-06-17", "slots": []})
    api.delay_s = 1.0
    started = time.monotonic()
    with pytest.raises(SchedulingBackendUnavailableError):
        await backend.availability("CA1", "s1", date(2030, 6, 17))
    assert time.monotonic() - started < 2.0  # Two timed-out attempts of 0.5 s, not more.


async def test_a_refused_signature_is_rejected_without_the_call_parameters(
    cronix: tuple[FakeCronixApi, CronixSchedulingBackend],
) -> None:
    api, backend = cronix
    api.reply = lambda route, body: (401, None)
    with pytest.raises(SchedulingBackendRejectedRequestError) as raised:
        await backend.availability("CA-private-sid", "s1", date(2030, 6, 17))
    assert "CA-private-sid" not in str(raised.value)
    assert SECRET not in str(raised.value)


async def test_the_call_is_closed_with_its_outcome(
    cronix: tuple[FakeCronixApi, CronixSchedulingBackend],
) -> None:
    api, backend = cronix
    await backend.close_call("CA1", CallOutcome.BOOKED)
    assert api.requests == [("POST", "/v1/calls/CA1/end", {"outcome": "booked"}, None)]
