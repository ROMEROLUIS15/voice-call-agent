"""A language model that answers with a fixed line, records what it was given and, when the case
has a write, books it through the booking flow (ADR 0019): it checks the availability with the
name, which proposes, on the first caller turn, and confirms from the second on, after the code read
the proposal back."""

import asyncio
from datetime import date
from uuid import uuid4

from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    Frame,
    FunctionCallFromLLM,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings

from evals.conversation_harness.schedule_conditions import HARNESS_NOW
from evals.conversation_harness.scripted_settings import complete_settings
from evals.golden_cases import ExpectedToolCall
from voice_call_agent.conversation_content.content_loader import load_conversation_content

SCRIPTED_REPLY = "Te escucho."


class ScriptedLanguageModel(LLMService):
    """Stands in for the provider in reference conversations, where the reply does not matter."""

    def __init__(
        self,
        system_prompt: str,
        write: ExpectedToolCall | None = None,
        says_before_calls: str | None = None,
        answers_after_s: float = 0.0,
    ) -> None:
        super().__init__(settings=complete_settings(LLMSettings, system_instruction=system_prompt))
        self.system_prompt = system_prompt
        self.caller_messages: list[str] = []
        self._write = write
        self._says_before_calls = says_before_calls
        """A line said in the same response as each function call, as a real model may say
        ("Perfecto, reviso el miércoles."): the response ends before the call runs."""
        self._answers_after_s = answers_after_s
        """How long each answer takes, as a provider's does; the harness must wait for it."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return
        messages: list[dict[str, object]] = [
            dict(message) for message in frame.context.get_messages() if isinstance(message, dict)
        ]
        self.caller_messages = [
            str(message.get("content", "")) for message in messages if message.get("role") == "user"
        ]
        if self._answers_after_s:
            await asyncio.sleep(self._answers_after_s)
        if call := self._tool_call_due(messages, frame.context):
            # The reply comes after the tool's result. A line said with the call ends its
            # response before the call runs, in the order a provider's response arrives.
            if self._says_before_calls:
                await self.push_frame(LLMFullResponseStartFrame())
                await self.push_frame(LLMTextFrame(self._says_before_calls))
                await self.push_frame(LLMFullResponseEndFrame())
            await self.run_function_calls([call])
            return
        await self.push_frame(LLMFullResponseStartFrame())
        await self.push_frame(LLMTextFrame(SCRIPTED_REPLY))
        await self.push_frame(LLMFullResponseEndFrame())

    def _tool_call_due(
        self, messages: list[dict[str, object]], context: LLMContext
    ) -> FunctionCallFromLLM | None:
        """The function the booking flow's current node offers for the write, if it is due.

        The availability check, with the name the caller said, answers each caller turn of the
        request step;
        the proposal is made as soon as its node offers it (the name step, when the name was not
        taken with the check); the confirmation answers each caller turn after the read-back,
        until one is to a read-back heard whole.
        """
        if self._write is None or not messages:
            return None
        offered, after_caller = _offered_functions(context), messages[-1].get("role") == "user"
        write = self._write.arguments
        turn = len(self.caller_messages)
        # The request step offers only the availability check: answered on the first turn, and
        # again when the code asked the caller for a day they had not said.
        if offered == {"check_availability"} and after_caller:
            arguments = {key: write[key] for key in ("service_id", "start", "client_name")}
            # Every name of the day (today or tomorrow, its weekday, its number and month): the
            # code keeps those the caller said and works the date out from them.
            arguments |= _names_of(date.fromisoformat(write["day"]))
            return _call("check_availability", arguments, context)
        if "propose_booking" in offered:
            return _call("propose_booking", {"client_name": write["client_name"]}, context)
        if "confirm_booking" in offered and after_caller and turn >= 2:  # Again after a re-read.
            return _call("confirm_booking", {}, context)
        return None


def _names_of(day: date) -> dict[str, str]:
    briefing = load_conversation_content().booking_briefing
    names = {
        "weekday": briefing.weekdays[day.weekday()],
        "day_number": str(day.day),
        "month": briefing.months[day.month - 1],
    }
    relative = ("today", "tomorrow", "day_after_tomorrow")
    if 0 <= (ahead := (day - HARNESS_NOW.date()).days) < len(relative):
        names["relative_day"] = relative[ahead]
    return names


def _call(name: str, arguments: dict[str, str], context: LLMContext) -> FunctionCallFromLLM:
    return FunctionCallFromLLM(
        function_name=name, tool_call_id=f"call-{uuid4().hex}", arguments=arguments, context=context
    )


def _offered_functions(context: LLMContext) -> set[str]:
    """The functions the current node of the flow offers."""
    tools = context.tools
    if not isinstance(tools, ToolsSchema):
        return set()
    return {tool.name for tool in tools.standard_tools}
