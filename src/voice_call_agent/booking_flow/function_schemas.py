"""The booking functions as the model receives them: what each is for and its arguments, the same
in every call; what the behaviour fingerprint and the snapshots follow."""

from typing import Any

from pydantic import BaseModel

from voice_call_agent.booking_flow.flow_arguments import (
    CheckAvailabilityArguments,
    ProposeBookingArguments,
    SelectStartArguments,
)

FUNCTION_DESCRIPTIONS = {
    "check_availability": (
        "Free start times of one day for one service, and whether the time the caller asked for "
        "is free. Call it as soon as the service and the day are known."
    ),
    "select_start": "Record the start time the caller chose, one of the free times offered.",
    "propose_booking": (
        "Propose the booking of the chosen service, day and time under the name of the person "
        "it is for. The system then reads it to the caller and asks whether it is right."
    ),
    "confirm_booking": "Book the proposal the caller just heard, only if they accept it unchanged.",
    "change_request": "The caller wants to change something, hesitates or says no.",
    "new_request": "The caller wants another appointment.",
    "keep_trying": "After the way out was offered, the caller wants to try again.",
    "end_call": "After the way out was offered, the caller prefers to stop; the system says bye.",
}
"""What each function is for, as the model reads it; the same in every call."""


def properties(arguments: type[BaseModel]) -> dict[str, Any]:
    """The JSON Schema properties of an arguments model."""
    schema = arguments.model_json_schema()
    return {
        field: {key: value for key, value in spec.items() if key != "title"}
        for field, spec in schema["properties"].items()
    }


_ARGUMENTS: dict[str, type[BaseModel]] = {
    "check_availability": CheckAvailabilityArguments,
    "select_start": SelectStartArguments,
    "propose_booking": ProposeBookingArguments,
}


def required(name: str) -> set[str]:
    model = _ARGUMENTS.get(name)
    return set(model.model_json_schema().get("required", [])) if model else set()


def booking_functions() -> dict[str, dict[str, Any]]:
    """Each booking function as the model receives it, the same in every call: what the
    behaviour fingerprint and the snapshots follow."""
    return {
        name: {
            "description": description,
            "properties": properties(model) if (model := _ARGUMENTS.get(name)) else {},
            "required": sorted(required(name)),
        }
        for name, description in FUNCTION_DESCRIPTIONS.items()
    }
