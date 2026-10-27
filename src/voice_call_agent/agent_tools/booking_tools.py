"""The booking tools of one call: availability read from the backend, proposal and confirmation
through the write guards."""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams, LLMService
from pydantic import BaseModel, ValidationError

from voice_call_agent.agent_tools.tool_arguments import (
    CheckAvailabilityArguments,
    ConfirmBookingArguments,
    ProposeBookingArguments,
)
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendError,
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import AvailableSlots
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend
from voice_call_agent.write_guards.booking_guard import BookingGuard, clock_time

_TOOLS: dict[str, tuple[str, type[BaseModel]]] = {
    "check_availability": (
        "Free start times of one day for one service, and whether the time the caller asked for "
        "is free. Call it before offering or accepting a time.",
        CheckAvailabilityArguments,
    ),
    "propose_booking": (
        "Propose a booking once the service, day, time and name are known. Read the summary it "
        "returns to the caller and ask whether they confirm it.",
        ProposeBookingArguments,
    ),
    "confirm_booking": (
        "Book a proposal, only after the caller accepted it unchanged. Report the real result.",
        ConfirmBookingArguments,
    ),
}
TOOL_NAMES = tuple(_TOOLS)
_JsonObject = dict[str, Any]  # Any: a JSON value, as tool results travel to the model.


def tool_schema(name: str) -> FunctionSchema:
    """A tool's schema, generated from its arguments model."""
    description, arguments = _TOOLS[name]
    schema = arguments.model_json_schema()
    properties = {
        field: {key: value for key, value in spec.items() if key != "title"}
        for field, spec in schema["properties"].items()
    }
    return FunctionSchema(
        name=name,
        description=description,
        properties=properties,
        required=list(schema.get("required", [])),
    )


class BookingTools:
    """What the model can do in a call with a business: read availability, propose, confirm."""

    def __init__(self, *, call_id: str, backend: SchedulingBackend, guard: BookingGuard) -> None:
        self._call_id = call_id
        self._backend = backend
        self._guard = guard

    @property
    def schema(self) -> ToolsSchema:
        return ToolsSchema(standard_tools=[tool_schema(name) for name in _TOOLS])

    def register(self, llm: LLMService) -> None:
        handlers: dict[str, Callable[[Mapping[str, Any]], Awaitable[_JsonObject]]] = {
            "check_availability": self._check_availability,
            "propose_booking": self._propose_booking,
            "confirm_booking": self._confirm_booking,
        }
        for name, handler in handlers.items():
            llm.register_function(name, _answering_with(handler))

    async def _check_availability(self, arguments: Mapping[str, Any]) -> _JsonObject:
        call = CheckAvailabilityArguments.model_validate(arguments)
        result = await self._backend.availability(self._call_id, call.service_id, call.day)
        if not isinstance(result, AvailableSlots):
            return result.model_dump(mode="json")
        answer: _JsonObject = {
            "kind": result.kind,
            "day": result.day.isoformat(),
            "free_starts": [clock_time(start) for start in result.slots],
        }
        if call.start is not None:
            # Computed here, not left to the model: reading a long list of times is where a
            # model with little reasoning errs (manifest §10).
            answer["requested_start"] = clock_time(call.start)
            answer["requested_start_free"] = call.start in result.slots
        return answer

    async def _propose_booking(self, arguments: Mapping[str, Any]) -> _JsonObject:
        call = ProposeBookingArguments.model_validate(arguments)
        result = await self._guard.propose(call.service_id, call.day, call.start, call.client_name)
        return result.model_dump(mode="json")

    async def _confirm_booking(self, arguments: Mapping[str, Any]) -> _JsonObject:
        call = ConfirmBookingArguments.model_validate(arguments)
        result = await self._guard.confirm(call.proposal_id)
        # The backend's appointment id means nothing to the caller: the model never gets it.
        return result.model_dump(mode="json", exclude={"appointment_id"})


def _answering_with(
    handler: Callable[[Mapping[str, Any]], Awaitable[_JsonObject]],
) -> Callable[[FunctionCallParams], Awaitable[None]]:
    """A Pipecat function handler that always answers the model, also when the call fails."""

    async def answer(params: FunctionCallParams) -> None:
        try:
            result = await handler(params.arguments)
        except ValidationError as error:
            # Not the error itself: its message carries the values, and one may be a name.
            fields = _invalid_fields(error)
            report_error(
                ErrorCode.TOOL_ARGUMENTS_INVALID, tool=params.function_name, fields=",".join(fields)
            )
            result = {"kind": "invalid_arguments", "fields": fields}
        except SchedulingBackendError as error:
            unavailable = isinstance(error, SchedulingBackendUnavailableError)
            report_error(
                ErrorCode.SCHEDULING_BACKEND_UNAVAILABLE
                if unavailable
                else ErrorCode.SCHEDULING_BACKEND_REJECTED,
                error=error,
                tool=params.function_name,
            )
            result = {"kind": "backend_unavailable"}
        await params.result_callback(result)

    return answer


def _invalid_fields(error: ValidationError) -> list[str]:
    """Which arguments were wrong, never their values (they may hold a name)."""
    return sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
