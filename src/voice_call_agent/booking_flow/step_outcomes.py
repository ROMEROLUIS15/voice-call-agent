"""What a booking step reports: where the conversation goes and what the model gets back, and
the outcomes of a step that could not run (arguments the model got wrong, a backend that did
not answer)."""

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendError,
    SchedulingBackendUnavailableError,
)

JsonObject = dict[str, Any]  # Any: a JSON value, as function results travel to the model.


class Step(StrEnum):
    REQUEST = "request"
    WHICH_DAY = "which_day"
    CHOOSE_TIME = "choose_time"
    NAME = "name"
    CONFIRM = "confirm"
    BOOKED = "booked"
    NOT_BOOKED = "not_booked"
    OFFER_WAY_OUT = "offer_way_out"
    END = "end"


@dataclass(frozen=True)
class StepOutcome:
    result: JsonObject
    """What the model gets back."""
    next_step: Step | None
    """Where the conversation goes; `None` stays on the current step."""
    said: str | None = None
    """A line the code says on moving to `next_step`, from the backend's answer; the model then
    waits for the caller instead of saying it in a second round."""
    silent: bool = False
    """Stay on the current step without the model speaking: another function called in the
    same response decides where the conversation goes (a second service, queued)."""


def validated_arguments[ArgumentsT: BaseModel](
    model: type[ArgumentsT], arguments: Mapping[str, Any]
) -> ArgumentsT | StepOutcome:
    """The validated arguments, or the answer that says which were wrong (never their values,
    which may hold a name)."""
    try:
        return model.model_validate(arguments)
    except ValidationError as error:
        fields = sorted({".".join(str(part) for part in item["loc"]) for item in error.errors()})
        report_error(ErrorCode.TOOL_ARGUMENTS_INVALID, fields=",".join(fields))
        return StepOutcome({"status": "invalid_arguments", "fields": fields}, None)


def backend_unavailable(content: ConversationContent) -> StepOutcome:
    """Nothing was booked: the code says so and the call ends (INV-5)."""
    said = content.backend_unavailable
    return StepOutcome({"status": "backend_unavailable"}, Step.NOT_BOOKED, said)


async def answering(content: ConversationContent, work: Awaitable[StepOutcome]) -> StepOutcome:
    """The step's outcome, or the answer that the backend did not respond."""
    try:
        return await work
    except SchedulingBackendError as error:
        unavailable = isinstance(error, SchedulingBackendUnavailableError)
        report_error(
            ErrorCode.SCHEDULING_BACKEND_UNAVAILABLE
            if unavailable
            else ErrorCode.SCHEDULING_BACKEND_REJECTED,
            error=error,
        )
        return backend_unavailable(content)
