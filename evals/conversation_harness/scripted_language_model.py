"""A language model that answers with a fixed line, records what it was given and, when the case
has a write, proposes it on the first caller turn and confirms it on the second."""

import json
from uuid import uuid4

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

from evals.conversation_harness.scripted_settings import complete_settings
from evals.golden_cases import ExpectedToolCall

SCRIPTED_REPLY = "Te escucho."


class ScriptedLanguageModel(LLMService):
    """Stands in for the provider in reference conversations, where the reply does not matter."""

    def __init__(self, system_prompt: str, write: ExpectedToolCall | None = None) -> None:
        super().__init__(settings=complete_settings(LLMSettings, system_instruction=system_prompt))
        self.system_prompt = system_prompt
        self.caller_messages: list[str] = []
        self._write = write

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
        if call := self._tool_call_due(messages, frame.context):
            # No response frames around a call alone: the harness counts replies by them, and
            # the reply comes after the tool's result.
            await self.run_function_calls([call])
            return
        await self.push_frame(LLMFullResponseStartFrame())
        await self.push_frame(LLMTextFrame(SCRIPTED_REPLY))
        await self.push_frame(LLMFullResponseEndFrame())

    def _tool_call_due(
        self, messages: list[dict[str, object]], context: LLMContext
    ) -> FunctionCallFromLLM | None:
        """The write's tool call this caller turn asks for; none after a tool's result."""
        if self._write is None or not messages or messages[-1].get("role") != "user":
            return None
        turn = len(self.caller_messages)
        if turn == 1:
            return _call("propose_booking", dict(self._write.arguments), context)
        if turn == 2 and (proposal_id := _last_proposal_id(messages)) is not None:
            return _call("confirm_booking", {"proposal_id": proposal_id}, context)
        return None


def _call(name: str, arguments: dict[str, str], context: LLMContext) -> FunctionCallFromLLM:
    return FunctionCallFromLLM(
        function_name=name, tool_call_id=f"call-{uuid4().hex}", arguments=arguments, context=context
    )


def _last_proposal_id(messages: list[dict[str, object]]) -> str | None:
    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        result = json.loads(str(message.get("content", "{}")))
        proposal_id = result.get("proposal_id") if isinstance(result, dict) else None
        if isinstance(proposal_id, str):
            return proposal_id
    return None
