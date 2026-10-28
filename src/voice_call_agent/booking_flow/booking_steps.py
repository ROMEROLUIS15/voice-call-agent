"""The booking functions of one call: thin steps over the scheduling backend and the write guard.

Each step does its work and reports where the conversation goes next as a `Step`, as Pipecat's
Flows examples do with a result field; `booking_graph` turns that into the next node. Nothing
here classifies what the caller said: the model fills the arguments, and the code checks them
against the catalog, the backend and the write guard (ADR 0011, ADR 0019).

The call's booking state lives in this object rather than in `FlowManager.state`, the gap it
fills: Pipecat's state is an untyped dict, and the write guard needs typed, validated values.
"""

from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from voice_call_agent.booking_flow.flow_arguments import (
    CheckAvailabilityArguments,
    ProposeBookingArguments,
    SelectStartArguments,
)
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.conversation_content.spoken_moments import spoken_day
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.scheduling_backend.scheduling_errors import (
    SchedulingBackendError,
    SchedulingBackendUnavailableError,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailableSlots,
    OpeningHours,
    ServiceOffering,
    WeeklyHours,
)
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend
from voice_call_agent.write_guards.booking_guard import (
    Booked,
    BookingGuard,
    ConfirmationRefusal,
    ProposalRefusal,
    Proposed,
    clock_time,
)

JsonObject = dict[str, Any]  # Any: a JSON value, as function results travel to the model.


class Step(StrEnum):
    REQUEST = "request"
    CHOOSE_TIME = "choose_time"
    NAME = "name"
    CONFIRM = "confirm"
    BOOKED = "booked"
    NOT_BOOKED = "not_booked"


@dataclass(frozen=True)
class StepOutcome:
    result: JsonObject
    """What the model gets back."""
    next_step: Step | None
    """Where the conversation goes; `None` stays on the current step."""


@dataclass(frozen=True)
class Slot:
    """A service, day and start time the backend offered for this call."""

    service: ServiceOffering
    day: date
    start: time


@dataclass(frozen=True)
class TimeChoice:
    """The free starts of a day the caller chooses from, and the start asked for if taken."""

    service: ServiceOffering
    day: date
    starts: list[time]
    taken: time | None
    offered_at_turn: int
    hours: OpeningHours | None
    """The day's opening hours, to say why `taken` is not offered."""
    """The caller's turns when the starts were offered: a start is chosen only after another."""


class BookingSteps:
    """The booking state of one call and the functions that move it."""

    def __init__(
        self,
        *,
        call_id: str,
        catalog: Sequence[ServiceOffering],
        backend: SchedulingBackend,
        guard: BookingGuard,
        content: ConversationContent,
        weekly_hours: WeeklyHours,
    ) -> None:
        self._call_id = call_id
        self._weekly_hours = weekly_hours
        self._catalog = {service.id: service for service in catalog}
        self._backend = backend
        self._guard = guard
        self._content = content
        self.slot: Slot | None = None
        self.choice: TimeChoice | None = None
        self.proposal: Proposed | None = None

    @property
    def catalog(self) -> list[ServiceOffering]:
        return list(self._catalog.values())

    async def check_availability(self, arguments: Mapping[str, Any]) -> StepOutcome:
        call = _arguments(CheckAvailabilityArguments, arguments)
        if isinstance(call, StepOutcome):
            return call
        return await _answering(self._check_availability(call))

    async def select_start(self, arguments: Mapping[str, Any]) -> StepOutcome:
        call = _arguments(SelectStartArguments, arguments)
        if isinstance(call, StepOutcome):
            return call
        if self.choice is None or call.start not in self.choice.starts:
            return StepOutcome({"status": "not_offered"}, None)
        if self._guard.caller_turns() <= self.choice.offered_at_turn:
            # The model picked a time the caller has not chosen yet: the caller chooses it.
            return StepOutcome({"status": "waiting_for_the_choice"}, None)
        self.slot = Slot(self.choice.service, self.choice.day, call.start)
        return StepOutcome({"status": "selected", "start": clock_time(call.start)}, Step.NAME)

    async def propose_booking(self, arguments: Mapping[str, Any]) -> StepOutcome:
        call = _arguments(ProposeBookingArguments, arguments)
        if isinstance(call, StepOutcome):
            return call
        if self.slot is None:
            return StepOutcome({"status": "no_slot_chosen"}, Step.REQUEST)
        return await _answering(self._propose(self.slot, call.client_name))

    async def confirm_booking(self, _arguments: Mapping[str, Any]) -> StepOutcome:
        if self.proposal is None:
            return StepOutcome({"status": "nothing_to_confirm"}, Step.REQUEST)
        return await _answering(self._confirm(self.proposal))

    async def change_request(self, _arguments: Mapping[str, Any]) -> StepOutcome:
        """The caller wants something else: back to the request, nothing pending is kept."""
        self.slot, self.choice, self.proposal = None, None, None
        return StepOutcome({"status": "changing"}, Step.REQUEST)

    async def _check_availability(self, call: CheckAvailabilityArguments) -> StepOutcome:
        # A new request: nothing chosen or proposed for the earlier one may be proposed or booked.
        self.slot, self.choice, self.proposal = None, None, None
        service = self._catalog.get(call.service_id)
        if service is None:
            return StepOutcome({"status": "unknown_service"}, None)
        result = await self._backend.availability(self._call_id, service.id, call.day)
        # The weekday is the code's, never the model's arithmetic (ADR 0019).
        day = {"day": call.day.isoformat(), "day_spoken": spoken_day(self._content, call.day)}
        if not isinstance(result, AvailableSlots):
            return StepOutcome({"status": result.kind, **day}, None)
        if not result.slots:
            return StepOutcome({"status": "no_free_starts", **day}, None)
        if call.start is not None and call.start in result.slots:
            self.slot = Slot(service, call.day, call.start)
            status = {"status": "available", **day, "start": clock_time(call.start)}
            return StepOutcome(status, Step.NAME)
        self.choice = TimeChoice(
            service,
            call.day,
            result.slots,
            call.start,
            self._guard.caller_turns(),
            self._weekly_hours.on(call.day),
        )
        starts = [clock_time(start) for start in result.slots]
        return StepOutcome(
            {"status": "choose_time", **day, "free_starts": starts}, Step.CHOOSE_TIME
        )

    async def _propose(self, slot: Slot, client_name: str) -> StepOutcome:
        result = await self._guard.propose(slot.service.id, slot.day, slot.start, client_name)
        if isinstance(result, Proposed):
            self.proposal = result
            return StepOutcome({"status": "proposed"}, Step.CONFIRM)
        if result.reason is ProposalRefusal.SLOT_NOT_OFFERED and result.available_starts:
            self.choice = TimeChoice(
                slot.service,
                slot.day,
                result.available_starts,
                slot.start,
                self._guard.caller_turns(),
                self._weekly_hours.on(slot.day),
            )
            return StepOutcome({"status": "slot_taken"}, Step.CHOOSE_TIME)
        return StepOutcome({"status": result.reason.value}, Step.REQUEST)

    async def _confirm(self, proposal: Proposed) -> StepOutcome:
        result = await self._guard.confirm(proposal.proposal_id)
        if isinstance(result, Booked):
            self.slot, self.choice, self.proposal = None, None, None
            return StepOutcome({"status": "booked"}, Step.BOOKED)
        if result.reason == ConfirmationRefusal.CALLER_HAS_NOT_ANSWERED:
            return StepOutcome({"status": "waiting_for_the_answer"}, None)
        if result.reason == ConfirmationRefusal.BACKEND_UNAVAILABLE:
            return StepOutcome({"status": "backend_unavailable"}, Step.NOT_BOOKED)
        # The backend refused the write, such as a slot taken since it was offered.
        self.slot, self.proposal = None, None
        return StepOutcome({"status": "slot_taken"}, Step.REQUEST)


def _arguments[ArgumentsT: BaseModel](
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


async def _answering(work: Awaitable[StepOutcome]) -> StepOutcome:
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
        return StepOutcome({"status": "backend_unavailable"}, Step.NOT_BOOKED)
