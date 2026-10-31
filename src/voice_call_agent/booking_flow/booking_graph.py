"""The booking conversation as a Pipecat Flows graph (ADR 0019).

Each node gives the model one task and only the functions that task needs. The code says the
greeting, the free times to choose from and the read-back of the proposal, and routes on each
function's outcome (`booking_steps`), as Pipecat's Flows examples route on a result field. Built
per call from the call's business. Its services and the free starts are not enums in the
function schemas: a provider that validates tool calls against the schema ends the turn on a
value outside an enum and the agent falls silent (manifest §10). The code checks them instead
(`unknown_service`, `not_offered`), and the model corrects itself.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pipecat.flows import (
    ActionConfig,
    FlowArgs,
    FlowManager,
    FlowsDirectFunction,
    FlowsFunctionSchema,
    NodeConfig,
)
from pipecat.frames.frames import TTSSpeakFrame
from pydantic import BaseModel

from voice_call_agent.booking_flow.booking_steps import (
    BookingSteps,
    JsonObject,
    Step,
    StepOutcome,
)
from voice_call_agent.booking_flow.flow_arguments import (
    CheckAvailabilityArguments,
    ProposeBookingArguments,
    SelectStartArguments,
)
from voice_call_agent.booking_flow.spoken_free_times import (
    free_times_for_model,
    free_times_said,
    requested_for_model,
)
from voice_call_agent.conversation_content.content_loader import BookingTasks, ConversationContent
from voice_call_agent.conversation_content.spoken_moments import (
    booking_done,
    proposal_read_back,
    spoken_day,
    spoken_time,
)

StepFunction = Callable[[Mapping[str, Any]], Awaitable[StepOutcome]]

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
}
"""What each function is for, as the model reads it; the same in every call."""


class BookingGraph:
    """The nodes of one call's booking conversation."""

    def __init__(
        self, *, steps: BookingSteps, content: ConversationContent, role: str, greeting: str
    ) -> None:
        """`role` is the booking prompt with the call's business; `greeting`, the business's."""
        self._steps = steps
        self._content = content
        self._role = role
        self._greeting = greeting

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
            Step.CHOOSE_TIME: self._choose_time,
            Step.NAME: self._name,
            Step.CONFIRM: self._confirm,
            Step.BOOKED: self._booked,
            Step.NOT_BOOKED: self._not_booked,
        }
        return builders[step]()

    def _request(self) -> NodeConfig:
        return _node(Step.REQUEST, self._tasks.request, [self._check_availability()])

    def _check_availability(self) -> FlowsFunctionSchema:
        schema = _properties(CheckAvailabilityArguments)
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
            "select_start", _properties(SelectStartArguments), self._steps.select_start
        )
        node = _node(Step.CHOOSE_TIME, task, [select, self._check_availability()])
        node["pre_actions"] = [say(free_times_said(self._content, choice))]
        node["respond_immediately"] = False
        return node

    def _name(self) -> NodeConfig:
        slot = self._steps.slot
        if slot is None:  # Only reached once a start was chosen.
            return self._request()
        task = self._tasks.name.format(
            service_name=slot.service.name,
            day=spoken_day(self._content, slot.day),
            time=spoken_time(self._content, slot.start),
        )
        propose = self._function(
            "propose_booking", _properties(ProposeBookingArguments), self._steps.propose_booking
        )
        return _node(Step.NAME, task, [propose, self._check_availability()])

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
        )
        node = _node(
            Step.CONFIRM,
            self._tasks.confirm,
            [
                self._function("confirm_booking", {}, self._steps.confirm_booking),
                self._function("change_request", {}, self._steps.change_request),
            ],
        )
        node["pre_actions"] = [say(read_back)]
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

    @property
    def _tasks(self) -> BookingTasks:
        return self._content.booking_flow.tasks

    def _function(
        self, name: str, properties: dict[str, Any], step: StepFunction
    ) -> FlowsFunctionSchema:
        """A function of a node: it runs its step and moves to the node its outcome names."""

        async def run(
            args: FlowArgs, flow_manager: FlowManager
        ) -> tuple[JsonObject, NodeConfig | None]:
            outcome = await step(args)
            return outcome.result, (self.node(outcome.next_step) if outcome.next_step else None)

        return FlowsFunctionSchema(
            name=name,
            description=FUNCTION_DESCRIPTIONS[name],
            properties=properties,
            required=[key for key in properties if key in _required(name)],
            handler=run,
        )


def say(text: str) -> ActionConfig:
    """A line the code says on entering a node, before its task and functions apply.

    Not Flows' built-in `tts_say`: Flows applies the node only once that action's completion
    frame reaches the end of the pipeline, and a caller who speaks over the line drops the frame,
    so the node never applies and the model answers with the previous node's functions (Pipecat
    issue #5263, open in 1.14). A custom action is not waited for: the node applies at once and
    the line is still spoken, and kept in the context, as the caller hears it.
    """
    return {"type": "say", "handler": _speak, "text": text}


async def _speak(action: dict[str, Any], flow_manager: FlowManager) -> None:
    await flow_manager.worker.queue_frame(TTSSpeakFrame(text=action["text"]))


def _node(
    step: Step, task: str, functions: list[FlowsFunctionSchema | FlowsDirectFunction]
) -> NodeConfig:
    return NodeConfig(
        name=step.value,
        task_messages=[{"role": "developer", "content": task}],
        functions=functions,
    )


def _properties(arguments: type[BaseModel]) -> dict[str, Any]:
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


def _required(name: str) -> set[str]:
    model = _ARGUMENTS.get(name)
    return set(model.model_json_schema().get("required", [])) if model else set()


def booking_functions() -> dict[str, dict[str, Any]]:
    """Each booking function as the model receives it, the same in every call: what the
    behaviour fingerprint and the snapshots follow."""
    return {
        name: {
            "description": description,
            "properties": _properties(model) if (model := _ARGUMENTS.get(name)) else {},
            "required": sorted(_required(name)),
        }
        for name, description in FUNCTION_DESCRIPTIONS.items()
    }
