"""The booking functions of one call: thin steps over the scheduling backend and the write guard.

Each step does its work and reports where the conversation goes next as a `Step`, as Pipecat's
Flows examples do with a result field; `booking_graph` turns that into the next node. Nothing
here classifies what the caller said: the model fills the arguments, and the code checks them
against the catalog, the backend and the write guard (ADR 0011, ADR 0019).

The call's booking state lives in this object rather than in `FlowManager.state`, the gap it
fills: Pipecat's state is an untyped dict, and the write guard needs typed, validated values.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Any

from voice_call_agent.booking_flow.flow_arguments import (
    CheckAvailabilityArguments,
    ProposeBookingArguments,
    SelectStartArguments,
)
from voice_call_agent.booking_flow.named_day import (
    DayQuestion,
    NamedDay,
    UnknownNamedDayError,
    day_question,
    day_said,
)
from voice_call_agent.booking_flow.step_outcomes import (
    Step,
    StepOutcome,
    answering,
    backend_unavailable,
    validated_arguments,
)
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.conversation_content.spoken_moments import day_closed, day_full, spoken_day
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailableSlots,
    ClosedDay,
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
        today: date,
    ) -> None:
        """`today` is the date in the business's time zone: the other day asked about when a
        weekday does not match the date is never in the past."""
        self._call_id = call_id
        self._today = today
        self._weekly_hours = weekly_hours
        self._catalog = {service.id: service for service in catalog}
        self._backend = backend
        self._guard = guard
        self._content = content
        self.slot: Slot | None = None
        self.choice: TimeChoice | None = None
        self.proposal: Proposed | None = None
        self.booked: Proposed | None = None
        """The proposal the backend booked last: the code says it to the caller."""
        self.day_question: DayQuestion | None = None
        """A weekday and a date the caller named that do not match: the code asks which."""

    @property
    def catalog(self) -> list[ServiceOffering]:
        return list(self._catalog.values())

    async def check_availability(self, arguments: Mapping[str, Any]) -> StepOutcome:
        call = validated_arguments(CheckAvailabilityArguments, arguments)
        if isinstance(call, StepOutcome):
            return call
        return await answering(self._content, self._check_availability(call))

    async def select_start(self, arguments: Mapping[str, Any]) -> StepOutcome:
        call = validated_arguments(SelectStartArguments, arguments)
        if isinstance(call, StepOutcome):
            return call
        if self.choice is None or call.start not in self.choice.starts:
            return StepOutcome({"status": "not_offered"}, None)
        if self._guard.caller_turns() <= self.choice.offered_at_turn:
            # The model picked a time the caller has not chosen yet: the caller chooses it.
            return StepOutcome({"status": "waiting_for_the_choice"}, None)
        self.slot = Slot(self.choice.service, self.choice.day, call.start)
        if call.client_name is not None:
            return await answering(self._content, self._propose(self.slot, call.client_name))
        return StepOutcome({"status": "selected", "start": clock_time(call.start)}, Step.NAME)

    async def propose_booking(self, arguments: Mapping[str, Any]) -> StepOutcome:
        call = validated_arguments(ProposeBookingArguments, arguments)
        if isinstance(call, StepOutcome):
            return call
        if self.slot is None:
            return StepOutcome({"status": "no_slot_chosen"}, Step.REQUEST)
        return await answering(self._content, self._propose(self.slot, call.client_name))

    async def confirm_booking(self, _arguments: Mapping[str, Any]) -> StepOutcome:
        if self.proposal is None:
            return StepOutcome({"status": "nothing_to_confirm"}, Step.REQUEST)
        return await answering(self._content, self._confirm(self.proposal))

    async def change_request(self, _arguments: Mapping[str, Any]) -> StepOutcome:
        """The caller wants something else: back to the request, nothing pending is kept."""
        self.slot, self.choice, self.proposal = None, None, None
        return StepOutcome({"status": "changing"}, Step.REQUEST)

    async def _check_availability(self, call: CheckAvailabilityArguments) -> StepOutcome:
        # A new request: nothing chosen or proposed for the earlier one may be proposed or booked.
        self.slot, self.choice, self.proposal, self.day_question = None, None, None, None
        service = self._catalog.get(call.service_id)
        if service is None:
            return StepOutcome({"status": "unknown_service"}, None)
        asked = self._settle_day(call)
        if isinstance(asked, StepOutcome):
            return asked
        result = await self._backend.availability(self._call_id, service.id, asked)
        # The weekday is the code's, never the model's arithmetic (ADR 0019).
        day = {"day": asked.isoformat(), "day_spoken": spoken_day(self._content, asked)}
        if isinstance(result, ClosedDay):
            said = day_closed(self._content, asked)
            return StepOutcome({"status": result.kind, **day}, Step.REQUEST, said)
        if not isinstance(result, AvailableSlots):
            return StepOutcome({"status": result.kind, **day}, None)
        if not result.slots:
            said = day_full(self._content, asked)
            return StepOutcome({"status": "no_free_starts", **day}, Step.REQUEST, said)
        if call.start is not None and call.start in result.slots:
            self.slot = Slot(service, asked, call.start)
            if call.client_name is not None:
                return await self._propose(self.slot, call.client_name)
            status = {"status": "available", **day, "start": clock_time(call.start)}
            return StepOutcome(status, Step.NAME)
        self.choice = TimeChoice(
            service,
            asked,
            result.slots,
            call.start,
            self._guard.caller_turns(),
            self._weekly_hours.on(asked),
        )
        starts = [clock_time(start) for start in result.slots]
        return StepOutcome(
            {"status": "choose_time", **day, "free_starts": starts}, Step.CHOOSE_TIME
        )

    def _settle_day(self, call: CheckAvailabilityArguments) -> date | StepOutcome:
        """The day asked for, worked out from the caller's words; where to go instead when they
        cannot say a day, or when the weekday named does not match the date named."""
        briefing = self._content.booking_briefing
        named = NamedDay(call.weekday, call.day_number, call.month)
        weekdays, months, today = briefing.weekdays, briefing.months, self._today
        try:
            day = day_said(
                named,
                call.relative_day,
                call.next_week,
                weekdays=weekdays,
                months=months,
                today=today,
            )
            question = day_question(day, named, weekdays=weekdays, months=months, today=today)
        except UnknownNamedDayError as error:
            report_error(ErrorCode.TOOL_ARGUMENTS_INVALID, fields=",".join(error.fields))
            return StepOutcome({"status": "invalid_arguments", "fields": error.fields}, None)
        if question is None:
            return day
        # Two days were named: nothing is offered for either until the caller says which.
        self.day_question = question
        dates = {
            "date": question.said_date.isoformat(),
            "weekday_date": question.weekday_date.isoformat(),
        }
        return StepOutcome({"status": "weekday_mismatch", **dates}, Step.WHICH_DAY)

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
            self.booked = proposal
            self.slot, self.choice, self.proposal = None, None, None
            return StepOutcome({"status": "booked"}, Step.BOOKED)
        if result.reason == ConfirmationRefusal.CALLER_HAS_NOT_ANSWERED:
            return StepOutcome({"status": "waiting_for_the_answer"}, None)
        if result.reason == ConfirmationRefusal.BACKEND_UNAVAILABLE:
            return backend_unavailable(self._content)
        # The backend refused the write, such as a slot taken since it was offered.
        self.slot, self.proposal = None, None
        return StepOutcome({"status": "slot_taken"}, Step.REQUEST, self._content.slot_taken)
