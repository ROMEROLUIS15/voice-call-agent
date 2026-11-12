"""The booking functions of one call: thin steps over the scheduling backend and the write guard.

Each step does its work and reports where the conversation goes next as a `Step`, as Pipecat's
Flows examples do with a result field; `booking_graph` turns that into the next node. Nothing
here classifies what the caller said: the model fills the arguments, and the code checks them
against the catalog, the backend and the write guard (ADR 0011, ADR 0019).

The call's booking state lives in this object rather than in `FlowManager.state`, the gap it
fills: Pipecat's state is an untyped dict, and the write guard needs typed, validated values.
"""

from collections.abc import Mapping, Sequence
from datetime import date, time
from typing import Any

from voice_call_agent.booking_flow.back_to_back import back_to_back_start
from voice_call_agent.booking_flow.booking_state import PendingRequest, Slot, TimeChoice
from voice_call_agent.booking_flow.flow_arguments import (
    CheckAvailabilityArguments,
    ProposeBookingArguments,
    SelectStartArguments,
)
from voice_call_agent.booking_flow.named_day import DayQuestion
from voice_call_agent.booking_flow.requested_day import requested_day
from voice_call_agent.booking_flow.step_outcomes import (
    Step,
    StepOutcome,
    answering,
    backend_unavailable,
    validated_arguments,
)
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.conversation_content.spoken_moments import (
    booked_then,
    day_closed,
    day_full,
    spoken_day,
)
from voice_call_agent.scheduling_backend.scheduling_models import (
    AvailabilityResult,
    AvailableSlots,
    ClosedDay,
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
        self.pending: list[PendingRequest] = []
        """Services asked for besides the one being booked, booked next in order."""
        self._request: tuple[str, int] | None = None
        """The service id of the request being booked and the caller's turn it started on."""
        self._client_name: str | None = None
        """The name of the last booking, for the next service: the read-back says it."""

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
        if self.choice is None:
            return StepOutcome({"status": "not_offered"}, None)
        if self._guard.caller_turns() <= self.choice.offered_at_turn:
            # The model picked a time the caller has not chosen yet: the caller chooses it.
            return StepOutcome({"status": "waiting_for_the_choice"}, None)
        if call.start not in self.choice.starts:  # The code says why, and the nearest free times.
            choice, start = self.choice, call.start
            self._offer_times(choice.service, choice.day, choice.starts, start)
            return StepOutcome(
                {"status": "not_offered", "start": clock_time(start)}, Step.CHOOSE_TIME
            )
        self.slot = Slot(self.choice.service, self.choice.day, call.start)
        if (name := call.client_name or self._client_name) is not None:
            return await answering(self._content, self._propose(self.slot, name))
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
        """The caller wants something else: back to the request, nothing chosen or proposed is
        kept; the services waiting for this one still wait."""
        self.slot, self.choice, self.proposal = None, None, None
        return StepOutcome({"status": "changing"}, Step.REQUEST, self._content.changing)

    async def _check_availability(self, call: CheckAvailabilityArguments) -> StepOutcome:
        service = self._catalog.get(call.service_id)
        if service is None:
            return StepOutcome({"status": "unknown_service"}, None)
        adds = self._adds_to_the_request(service, call.in_addition)
        if not adds:
            # A new request: nothing chosen or proposed for the earlier one is proposed or booked.
            self.slot, self.choice, self.proposal, self.day_question = None, None, None, None
            self._request = (service.id, self._guard.caller_turns())
        asked = self._settle_day(call)
        if isinstance(asked, StepOutcome):
            return asked
        if adds and self._request is not None:
            # Asked again, it waits once, with what was said last.
            waiting = [waiting for waiting in self.pending if waiting.service.id != service.id]
            self.pending = [*waiting, PendingRequest(service, asked, call.start, call.client_name)]
            # Asked in the same response as the request: it must not replace that one's step.
            same_turn = self._request[1] == self._guard.caller_turns()
            after = self._catalog[self._request[0]].name
            queued = {"status": "queued", "service": service.name, "after": after}
            if self.proposal is not None:  # Read back again, with the services that wait.
                return StepOutcome(queued, Step.CONFIRM)
            return StepOutcome(queued, None, silent=same_turn)
        self.pending = [waiting for waiting in self.pending if waiting.service.id != service.id]
        return await self._offer(service, asked, call.start, call.client_name)

    def _adds_to_the_request(self, service: ServiceOffering, in_addition: bool | None) -> bool:
        """A different service asked for while one is being booked, in the same response or
        said to be besides it, waits for it; otherwise it replaces it. The request lasts until
        it is booked or replaced: a change at the read-back clears its time, not the request."""
        if self._request is None:
            return False
        service_id, turn = self._request
        same_turn = turn == self._guard.caller_turns()
        return service.id != service_id and (same_turn or bool(in_addition))

    async def _offer(
        self,
        service: ServiceOffering,
        asked: date,
        start: time | None,
        client_name: str | None,
        known: AvailabilityResult | None = None,
    ) -> StepOutcome:
        """The service's availability that day (`known` if already read), and where the
        conversation goes with it."""
        result = known or await self._backend.availability(self._call_id, service.id, asked)
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
        if start is not None and start in result.slots:
            self.slot = Slot(service, asked, start)
            if (name := client_name or self._client_name) is not None:
                return await self._propose(self.slot, name)
            status = {"status": "available", **day, "start": clock_time(start)}
            return StepOutcome(status, Step.NAME)
        self._offer_times(service, asked, result.slots, start)
        starts = [clock_time(start) for start in result.slots]
        return StepOutcome(
            {"status": "choose_time", **day, "free_starts": starts}, Step.CHOOSE_TIME
        )

    def _settle_day(self, call: CheckAvailabilityArguments) -> date | StepOutcome:
        """The day asked for, worked out from the caller's words; where to go instead when they
        cannot say a day, or when the weekday named does not match the date named."""
        question = requested_day(call, self._content, self._today)
        if not isinstance(question, DayQuestion):
            return question
        # Two days were named: nothing is offered for either until the caller says which.
        self.day_question = question
        dates = {
            "date": question.said_date.isoformat(),
            "weekday_date": question.weekday_date.isoformat(),
        }
        return StepOutcome({"status": "weekday_mismatch", **dates}, Step.WHICH_DAY)

    def _offer_times(
        self, service: ServiceOffering, day: date, starts: list[time], taken: time | None
    ) -> None:
        """The free starts the caller chooses from, offered at this caller turn."""
        hours = self._weekly_hours.on(day)
        self.choice = TimeChoice(service, day, starts, taken, self._guard.caller_turns(), hours)

    async def _propose(self, slot: Slot, client_name: str) -> StepOutcome:
        result = await self._guard.propose(slot.service.id, slot.day, slot.start, client_name)
        if isinstance(result, Proposed):
            self.proposal = result
            day = {"day": slot.day.isoformat(), "day_spoken": spoken_day(self._content, slot.day)}
            proposed = {"service": result.service_name, **day, "start": clock_time(slot.start)}
            return StepOutcome({"status": "proposed", **proposed}, Step.CONFIRM)  # No name.
        if result.reason is ProposalRefusal.SLOT_NOT_OFFERED and result.available_starts:
            self._offer_times(slot.service, slot.day, result.available_starts, slot.start)
            return StepOutcome({"status": "slot_taken"}, Step.CHOOSE_TIME)
        return StepOutcome({"status": result.reason.value}, Step.REQUEST)

    async def _confirm(self, proposal: Proposed) -> StepOutcome:
        result = await self._guard.confirm(proposal.proposal_id)
        if isinstance(result, Booked):
            self.booked, self._client_name = proposal, proposal.client_name
            first = self.slot.service if self.slot is not None else None
            self.slot, self.choice, self.proposal, self._request = None, None, None, None
            if not self.pending:
                return StepOutcome({"status": "booked"}, Step.BOOKED)
            return await self._book_the_next(proposal, first)
        if result.reason == ConfirmationRefusal.CALLER_HAS_NOT_ANSWERED:
            return StepOutcome({"status": "waiting_for_the_answer"}, None)
        if result.reason == ConfirmationRefusal.READ_BACK_NOT_HEARD:  # Spoken over: read again.
            again = self._content.read_back_again
            return StepOutcome({"status": "read_back_repeated"}, Step.CONFIRM, again)
        if result.reason == ConfirmationRefusal.BACKEND_UNAVAILABLE:
            return backend_unavailable(self._content)
        # The backend refused the write, such as a slot taken since it was offered.
        self.slot, self.proposal = None, None
        return StepOutcome({"status": "slot_taken"}, Step.REQUEST, self._content.slot_taken)

    async def _book_the_next(self, done: Proposed, first: ServiceOffering | None) -> StepOutcome:
        """The code says the booking is done and goes on with the next service asked for: on
        the same day and with no other time asked, as close to the first as the schedule allows
        (right after it, by each service's duration), never over another caller's booking."""
        following = self.pending.pop(0)
        self._request = (following.service.id, self._guard.caller_turns())
        start, known = following.start, None
        together = following.day == done.day and following.start in (None, done.start)
        if together and first is not None:
            service = following.service
            known = await self._backend.availability(self._call_id, service.id, following.day)
            if isinstance(known, AvailableSlots):
                durations = (first.duration_min, service.duration_min)
                start = back_to_back_start(known.slots, done.start, *durations) or start
        offered = await self._offer(
            following.service, following.day, start, following.client_name, known
        )
        said = booked_then(
            self._content, done.service_name, done.day, done.start, following.service.name
        )
        if offered.said is not None:
            said = f"{said} {offered.said}"
        result = {
            "status": "booked",
            "next_service": following.service.name,
            "next": offered.result,
        }
        return StepOutcome(result, offered.next_step or Step.REQUEST, said)
