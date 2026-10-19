"""A language model that answers with a fixed line and records what it was given."""

from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService
from pipecat.services.settings import LLMSettings

from evals.conversation_harness.scripted_settings import complete_settings

SCRIPTED_REPLY = "Te escucho."


class ScriptedLanguageModel(LLMService):
    """Stands in for the provider in reference conversations, where the reply does not matter."""

    def __init__(self, system_prompt: str) -> None:
        super().__init__(settings=complete_settings(LLMSettings, system_instruction=system_prompt))
        self.system_prompt = system_prompt
        self.caller_messages: list[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return
        self.caller_messages = [
            str(message.get("content", ""))
            for message in frame.context.get_messages()
            if isinstance(message, dict) and message.get("role") == "user"
        ]
        await self.push_frame(LLMFullResponseStartFrame())
        await self.push_frame(LLMTextFrame(SCRIPTED_REPLY))
        await self.push_frame(LLMFullResponseEndFrame())
