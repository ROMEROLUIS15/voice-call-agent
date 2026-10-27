"""The booking tools: schemas generated from their arguments, and handlers that always answer."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from pipecat.services.llm_service import FunctionCallParams, LLMService
from pydantic import BaseModel

from tests.write_guard_fixtures import CALL_ID, TUESDAY, GuardedCall, guarded_call
from voice_call_agent.agent_tools.booking_tools import BookingTools, tool_schema
from voice_call_agent.agent_tools.tool_arguments import (
    CheckAvailabilityArguments,
    ConfirmBookingArguments,
    ProposeBookingArguments,
)
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend

Handler = Callable[[FunctionCallParams], Awaitable[None]]
ARGUMENTS: dict[str, type[BaseModel]] = {
    "check_availability": CheckAvailabilityArguments,
    "propose_booking": ProposeBookingArguments,
    "confirm_booking": ConfirmBookingArguments,
}


class _RecordingModel:
    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}

    def register_function(self, name: str, handler: Handler) -> None:
        self.handlers[name] = handler


@dataclass
class _Params:
    function_name: str
    arguments: Mapping[str, Any]
    results: list[Any] = field(default_factory=list)

    async def result_callback(self, result: Any) -> None:
        self.results.append(result)


async def _registered(
    call: GuardedCall, backend: SchedulingBackend | None = None
) -> _RecordingModel:
    tools = BookingTools(call_id=CALL_ID, backend=backend or call.backend, guard=call.guard)
    model = _RecordingModel()
    tools.register(cast(LLMService, model))
    return model


async def _call(model: _RecordingModel, name: str, **arguments: Any) -> Any:
    params = _Params(name, arguments)
    await model.handlers[name](cast(FunctionCallParams, params))
    [result] = params.results
    return result


@pytest.mark.parametrize("name", sorted(ARGUMENTS))
def test_each_schema_is_generated_from_its_arguments_model(name: str) -> None:
    model_schema = ARGUMENTS[name].model_json_schema()
    schema = tool_schema(name)
    assert schema.name == name
    assert schema.required == model_schema["required"]
    assert set(schema.properties) == set(model_schema["properties"])
    for field_name, spec in schema.properties.items():
        expected = {k: v for k, v in model_schema["properties"][field_name].items() if k != "title"}
        assert spec == expected, field_name


async def test_the_model_reads_availability_proposes_and_confirms() -> None:
    call = await guarded_call()
    model = await _registered(call)
    slots = await _call(
        model, "check_availability", service_id="haircut", day=TUESDAY.isoformat(), start="11:00"
    )
    assert slots["kind"] == "available_slots" and "11:00" in slots["free_starts"]
    assert (slots["requested_start"], slots["requested_start_free"]) == ("11:00", True)
    proposal = await _call(
        model,
        "propose_booking",
        service_id="haircut",
        day="2026-10-27",
        start="11:00",
        client_name="Ana",
    )
    assert proposal["kind"] == "proposed"
    call.caller_speaks()
    booked = await _call(model, "confirm_booking", proposal_id=proposal["proposal_id"])
    assert booked["kind"] == "booked"


async def test_invalid_arguments_are_answered_without_their_values() -> None:
    call = await guarded_call()
    model = await _registered(call)
    result = await _call(
        model,
        "propose_booking",
        service_id="haircut",
        day="el martes",
        start="11:00",
        client_name="Ana Ejemplo",
        business_id="spa",  # A tenant the model made up never travels.
    )
    assert result == {"kind": "invalid_arguments", "fields": ["business_id", "day"]}
    assert "Ana" not in str(result)


async def test_an_unavailable_backend_is_answered_as_such() -> None:
    class _Down:
        async def availability(self, *_: object) -> None:
            raise SchedulingBackendUnavailableError

    call = await guarded_call()
    model = await _registered(call, cast(SchedulingBackend, _Down()))
    result = await _call(model, "check_availability", service_id="haircut", day="2026-10-27")
    assert result == {"kind": "backend_unavailable"}


def test_the_tools_schema_offers_the_three_tools() -> None:
    names = {"check_availability", "propose_booking", "confirm_booking"}
    tools = BookingTools(
        call_id=CALL_ID,
        backend=cast(InMemorySchedule, None),
        guard=cast(Any, None),
    )
    assert {schema.name for schema in tools.schema.standard_tools} == names
