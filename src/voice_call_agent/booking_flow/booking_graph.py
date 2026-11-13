"""The booking conversation as a Pipecat Flows graph (ADR 0019), built per call from its business.

Each node gives the model one task and only the functions that task needs. The code says the
greeting, which day when a weekday and a date disagree, the free times, the question for the
name, the read-back of the proposal and that it was booked, and routes on each function's outcome
(`booking_steps`), as Pipecat's Flows examples route on a result field. Services and free starts
are not enums in the function schemas: a provider that validates tool calls against the schema
ends the turn on a value outside an enum and the agent falls silent (manifest §10). The code
checks them instead (`unknown_service`, `not_offered`), and the model corrects itself.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pipecat.flows import (
    NO_RESPONSE,
    FlowArgs,
    FlowManager,
    FlowsDirectFunction,
    FlowsFunctionSchema,
    NodeConfig,
)

# `_NoResponse` is the type of Flows' public `NO_RESPONSE` sentinel, which it does not export.
from pipecat.flows.types import _NoResponse
from pipecat.frames.frames import TTSSpeakFrame

from voice_call_agent.booking_flow.booking_steps import BookingSteps
from voice_call_agent.booking_flow.flow_arguments import (
    CheckAvailabilityArguments,
    ProposeBookingArguments,
    SelectStartArguments,
)
from voice_call_agent.booking_flow.function_schemas import (
    FUNCTION_DESCRIPTIONS,
    properties,
    required,
)
from voice_call_agent.booking_flow.spoken_free_times import (
    free_times_for_model,
    free_times_said,
    requested_for_model,
)
from voice_call_agent.booking_flow.spoken_lines import joined, say
from voice_call_agent.booking_flow.step_outcomes import JsonObject, Step, StepOutcome
from voice_call_agent.booking_flow.way_out import WayOut
from voice_call_agent.conversation_content.content_loader import BookingTasks, ConversationContent
from voice_call_agent.conversation_content.spoken_moments import (
    booking_done,
    proposal_read_back,
    spoken_day,
    spoken_time,
    which_day_question,
)

StepFunction = Callable[[Mapping[str, Any]], Awaitable[StepOutcome]]


NextNode = NodeConfig | _NoResponse | None
"""Where a function sends the call: a node, staying silent on the current one, or staying."""


class BookingGraph:
    """The nodes of one call's booking conversation."""

    def __init__(
        self,
        *,
        steps: BookingSteps,
        content: ConversationContent,
        role: str,
        greeting: str,
        on_read_back: Callable[[], None] = lambda: None,
    ) -> None:
        """`role` is the booking prompt with the call's business; `greeting`, the business's;
        `on_read_back` runs as each read-back is queued (a "sí" said over it books nothing)."""
        self._steps = steps
        self._content = content
        self._role = role
        self._greeting = greeting
        self._on_read_back = on_read_back
        self._way_out = WayOut(content)

    async def model_replied(self, flow_manager: FlowManager, *, said_something: bool) -> None:
        """A response of the model ended: one that said nothing is a stall, which the code
        answers instead of leaving the caller in silence; the third in a row offers the way out."""
        if said_something:
            self._way_out.stalls.moved_on()
        elif self._way_out.model_silent():
            node = self.node(Step.OFFER_WAY_OUT)
            node["pre_actions"] = joined(self._content.offer_way_out, [])
            await flow_manager.set_node_from_config(node)
        else:
            await flow_manager.worker.queue_frame(TTSSpeakFrame(text=self._content.model_silent))

    def initial_node(self) -> NodeConfig:
        """The request, after the business's greeting, waiting for the caller to speak."""
        node = self.node(Step.REQUEST)
        node["role_message"] = self._role
        node["pre_actions"] = [say(self._greeting)]
        node["respond_immediately"] = False
        return node

    def node(self, step: Step) -> NodeConfig:
        builders: dict[Step, Callable[[], NodeConfig]] = {
            Step.REQUEST: self._request,
            Step.WHICH_DAY: self._which_day,
            Step.CHOOSE_TIME: self._choose_time,
            Step.NAME: self._name,
            Step.CONFIRM: self._confirm,
            Step.BOOKED: self._booked,
            Step.NOT_BOOKED: self._not_booked,
            Step.OFFER_WAY_OUT: self._offer_way_out,
            Step.END: self._end,
        }
        return builders[step]()

    def _request(self) -> NodeConfig:
        return _node(Step.REQUEST, self._tasks.request, [self._check_availability()])

    def _which_day(self) -> NodeConfig:
        """The code asks which of the two days named, and the model waits for the answer."""
        question = self._steps.day_question
        if question is None:  # Only reached after check_availability set it.
            return self._request()
        said, other = question.said_date, question.weekday_date
        task = self._tasks.which_day.format(
            said_day=spoken_day(self._content, said),
            said_date=said.isoformat(),
            weekday_day=spoken_day(self._content, other),
            weekday_date=other.isoformat(),
        )
        node = _node(Step.WHICH_DAY, task, [self._check_availability()])
        node["pre_actions"] = [say(which_day_question(self._content, said, other))]
        node["respond_immediately"] = False
        return node

    def _check_availability(self) -> FlowsFunctionSchema:
        schema = properties(CheckAvailabilityArguments)
        return self._function("check_availability", schema, self._steps.check_availability)

    def _choose_time(self) -> NodeConfig:
        """The code says the free times, and the model waits for the caller to choose."""
        choice = self._steps.choice
        if choice is None:  # Only reached after check_availability set it.
            return self._request()
        task = self._tasks.choose_time.format(
            service_name=choice.service.name,
            day=spoken_day(self._content, choice.day),
            free_times=free_times_for_model(self._content, choice),
            requested=requested_for_model(self._content, choice),
        )
        select = self._function(
            "select_start", properties(SelectStartArguments), self._steps.select_start
        )
        node = _node(Step.CHOOSE_TIME, task, [select, self._check_availability()])
        node["pre_actions"] = [say(free_times_said(self._content, choice))]
        node["respond_immediately"] = False
        return node

    def _name(self) -> NodeConfig:
        """The code asks for the name, and the model waits for the caller's answer."""
        slot = self._steps.slot
        if slot is None:  # Only reached once a start was chosen.
            return self._request()
        task = self._tasks.name.format(
            service_name=slot.service.name,
            day=spoken_day(self._content, slot.day),
            time=spoken_time(self._content, slot.start),
        )
        propose = self._function(
            "propose_booking", properties(ProposeBookingArguments), self._steps.propose_booking
        )
        node = _node(Step.NAME, task, [propose, self._check_availability()])
        node["pre_actions"] = [say(self._content.name_ask)]
        node["respond_immediately"] = False
        return node

    def _confirm(self) -> NodeConfig:
        """The code reads the proposal back, and the model waits for the caller's answer."""
        proposal = self._steps.proposal
        if proposal is None:  # Only reached once a proposal was validated.
            return self._request()
        read_back = proposal_read_back(
            self._content,
            proposal.service_name,
            proposal.day,
            proposal.start,
            proposal.client_name,
            [waiting.service.name for waiting in self._steps.pending],
        )
        node = _node(
            Step.CONFIRM,
            self._tasks.confirm,
            [
                self._function("confirm_booking", {}, self._steps.confirm_booking),
                self._function("change_request", {}, self._steps.change_request),
                self._check_availability(),  # Another service besides it: read back with it.
            ],
        )
        # The facts, watched for speech over them, then the question as a line of its own.
        question = say(self._content.read_back_question)
        node["pre_actions"] = [say(read_back, before=self._on_read_back), question]
        node["respond_immediately"] = False
        return node

    def _booked(self) -> NodeConfig:
        """The code says the booking is done; the model waits for the caller."""
        new = self._function("new_request", {}, self._steps.change_request)
        node = _node(Step.BOOKED, self._tasks.booked, [new])
        booked = self._steps.booked
        if booked is not None:  # Always set on reaching this node; the guard keeps mypy honest.
            node["pre_actions"] = [say(booking_done(self._content, booked.day, booked.start))]
            node["respond_immediately"] = False
        return node

    def _not_booked(self) -> NodeConfig:
        return _node(Step.NOT_BOOKED, self._tasks.not_booked, [])

    def _offer_way_out(self) -> NodeConfig:
        """The code offered to try again or reach the business; the model waits for the answer."""
        keep = self._function("keep_trying", {}, self._way_out.keep_trying)
        end = self._function("end_call", {}, self._way_out.end_call)
        node = _node(Step.OFFER_WAY_OUT, self._tasks.offer_way_out, [keep, end])
        node["respond_immediately"] = False
        return node

    def _end(self) -> NodeConfig:
        """The code says goodbye and the call ends once it was said (Flows' end action)."""
        node = _node(Step.END, self._tasks.end, [])
        node["pre_actions"] = [{"type": "end_conversation", "text": self._content.goodbye}]
        return node

    @property
    def _tasks(self) -> BookingTasks:
        return self._content.booking_flow.tasks

    def _function(
        self, name: str, properties: dict[str, Any], step: StepFunction
    ) -> FlowsFunctionSchema:
        """A function of a node: it runs its step and moves to the node its outcome names."""

        async def run(args: FlowArgs, flow_manager: FlowManager) -> tuple[JsonObject, NextNode]:
            outcome = self._way_out.tally(await step(args))
            if outcome.silent:
                return outcome.result, NO_RESPONSE
            if outcome.next_step is None:
                return outcome.result, None
            node = self.node(outcome.next_step)
            if outcome.said is not None:  # The code says the result; the model waits.
                node["pre_actions"] = joined(outcome.said, node.get("pre_actions", []))
                node["respond_immediately"] = False
            return outcome.result, node

        return FlowsFunctionSchema(
            name=name,
            description=FUNCTION_DESCRIPTIONS[name],
            properties=properties,
            required=[key for key in properties if key in required(name)],
            handler=run,
        )


def _node(
    step: Step, task: str, functions: list[FlowsFunctionSchema | FlowsDirectFunction]
) -> NodeConfig:
    return NodeConfig(
        name=step.value,
        task_messages=[{"role": "developer", "content": task}],
        functions=functions,
    )
