"""Cronix as the scheduling backend and the business resolver, through its phone agent API.

v1 serves the phone line (contract §4): a call starts by its dialed number, then reads the
availability, books and closes. The business of every request comes from Cronix's call record,
never from what the agent sends. Rescheduling, cancelling, reading the caller's appointments and
taking messages are v1.1: until then they refuse, and no step of the booking flow calls them.
"""

from collections.abc import Callable
from datetime import date, time
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlencode

from voice_call_agent.adapters.cronix_scheduling_api.signed_api import JsonObject, SignedApi
from voice_call_agent.call_session.business_resolution import (
    BusinessResolved,
    CallStartResolution,
    SpokenNameResolution,
    UnknownLine,
)
from voice_call_agent.call_session.session import CallSession
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendRejectedRequestError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    Appointment,
    AvailabilityResult,
    AvailableSlots,
    BookingRequest,
    BusinessContext,
    CallerMessage,
    CallOutcome,
    CancellationRequest,
    ClosedDay,
    InvalidAvailabilityRequest,
    OpeningHours,
    RescheduleRequest,
    ServiceOffering,
    WeeklyHours,
    WriteRejected,
    WriteRejectionReason,
    WriteResult,
    WriteSucceeded,
)

_V1_ONLY = "not served by Cronix's phone agent API v1"


class CronixSchedulingBackend:
    """`SchedulingBackend` and `BusinessResolver` over Cronix's signed phone agent API."""

    def __init__(self, api: SignedApi, greeting: Callable[[str], str]) -> None:
        """`greeting` builds a business's greeting from its name: Cronix keeps none."""
        self._api = api
        self._greeting = greeting

    async def resolve_call_business(self, session: CallSession) -> CallStartResolution:
        # v1 serves the phone line: Cronix refuses another entry (contract §4).
        result = await self._api.post(
            "/v1/calls/start",
            {
                "call_sid": session.call_id,
                "channel": session.line_kind,
                "to": session.dialed_phone or "",
                "from": session.caller_phone,
            },
        )
        if not result.get("success"):
            if result.get("error") == "UNKNOWN_LINE":
                return UnknownLine()
            raise SchedulingBackendRejectedRequestError(f"call start: {result.get('error')}")
        business = result["business"]
        return BusinessResolved(business_id=str(business["id"]), context=self._context(result))

    async def resolve_spoken_business(self, call_id: str, spoken_name: str) -> SpokenNameResolution:
        raise SchedulingBackendRejectedRequestError(f"choosing a business by name is {_V1_ONLY}")

    async def availability(self, call_id: str, service_id: str, day: date) -> AvailabilityResult:
        query = urlencode({"call_sid": call_id, "service_id": service_id, "date": day.isoformat()})
        result = await self._api.get(f"/v1/availability?{query}")
        if result.get("success"):
            return AvailableSlots(day=day, slots=[time.fromisoformat(s) for s in result["slots"]])
        if result.get("error") == "CLOSED_DAY":
            return ClosedDay()
        if result.get("error") in ("INVALID_ARGS", "NOT_FOUND"):
            return InvalidAvailabilityRequest()
        raise SchedulingBackendRejectedRequestError(f"availability: {result.get('error')}")

    async def book_appointment(self, request: BookingRequest) -> WriteResult:
        result = await self._api.post(
            "/v1/appointments",
            {
                "call_sid": request.call_id,
                "service_id": request.service_id,
                "date": request.day.isoformat(),
                "time": request.start.strftime("%H:%M"),
                "client_name": request.client_name,
            },
            idempotency_key=str(request.idempotency_key),
        )
        if result.get("success"):
            return WriteSucceeded(appointment_id=str(result["appointment_id"]))
        error = result.get("error")
        if isinstance(error, str) and error in WriteRejectionReason.__members__:
            return WriteRejected(reason=WriteRejectionReason(error))
        raise SchedulingBackendRejectedRequestError(f"booking: {error}")

    async def close_call(self, call_id: str, outcome: CallOutcome) -> None:
        await self._api.post(f"/v1/calls/{quote(call_id, safe='')}/end", {"outcome": outcome.value})

    async def upcoming_appointments(self, call_id: str) -> list[Appointment]:
        raise SchedulingBackendRejectedRequestError(f"reading appointments is {_V1_ONLY}")

    async def reschedule_appointment(self, request: RescheduleRequest) -> WriteResult:
        raise SchedulingBackendRejectedRequestError(f"rescheduling is {_V1_ONLY}")

    async def cancel_appointment(self, request: CancellationRequest) -> WriteResult:
        raise SchedulingBackendRejectedRequestError(f"cancelling is {_V1_ONLY}")

    async def leave_message(self, message: CallerMessage) -> None:
        raise SchedulingBackendRejectedRequestError(f"taking messages is {_V1_ONLY}")

    def _context(self, result: JsonObject) -> BusinessContext:
        business = result["business"]
        return BusinessContext(
            name=business["name"],
            timezone=business["timezone"],
            greeting=self._greeting(business["name"]),
            recording_enabled=False,
            services=[_service(service) for service in result["services"]],
            weekly_hours=_weekly_hours(result["working_hours"]),
            currency=business["currency"],
            known_client_first_name=None,  # The phone line never names the caller (§4.1).
        )


def _service(service: JsonObject) -> ServiceOffering:
    price = service.get("price")
    return ServiceOffering(
        id=str(service["id"]),
        name=service["name"],
        duration_min=int(service["duration_min"]),
        price=None if price is None else Decimal(str(price)),
    )


def _weekly_hours(hours: dict[str, Any]) -> WeeklyHours:  # Any: the API's JSON hours.
    def day(key: str) -> OpeningHours | None:
        value = hours.get(key)
        if not value:
            return None
        return OpeningHours(opens=time.fromisoformat(value[0]), closes=time.fromisoformat(value[1]))

    return WeeklyHours(
        **{key: day(key) for key in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    )
