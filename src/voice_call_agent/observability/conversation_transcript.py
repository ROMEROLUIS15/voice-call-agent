"""What was said in a call, as its model saw it: a development aid (ADR 0017).

The call trace never holds conversation content (constitution §4 and §16). With
`CONVERSATION_TRANSCRIPTS_DIR`, refused outside development, each call also leaves a text file: the
prompt its model received and the conversation in order, with the caller's turns as the
speech-to-text heard them, the agent's lines as they were spoken (cut where the caller
interrupted) and each tool call with its result. It stays on this machine: never exported.
"""

import asyncio
import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Protocol, cast

from pipecat.processors.aggregators.llm_context import LLMContextMessage, LLMSpecificMessage
from pydantic import BaseModel, ConfigDict

from voice_call_agent.observability.call_trace import CallTrace
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode

_SPEAKERS = {"user": "caller", "assistant": "agent", "system": "system", "developer": "system"}
_UNSAFE_IN_FILE_NAMES = re.compile(r"[^A-Za-z0-9_-]")


class ConversationTranscript(BaseModel):
    model_config = ConfigDict(frozen=True)

    call_id: str
    header: str
    """Joins the transcript to the call's trace: call, business, start and outcome."""
    system_prompt: str
    lines: tuple[str, ...]

    def as_text(self) -> str:
        sections = [self.header, "", "--- prompt ---", self.system_prompt, ""]
        return "\n".join([*sections, "--- conversation ---", *self.lines]) + "\n"


class ConversationTranscriptSink(Protocol):
    """Where a finished call leaves its transcript."""

    async def write(self, transcript: ConversationTranscript) -> None: ...


class TextFileTranscriptSink:
    """One text file per call in a local directory, named after the call."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def path_for(self, call_id: str) -> Path:
        # Call ids come from Twilio, Meta or this service: only letters, digits, `_` and `-`
        # reach the file name, so no id can leave the directory.
        return self._directory / f"{_UNSAFE_IN_FILE_NAMES.sub('_', call_id)}.txt"

    async def write(self, transcript: ConversationTranscript) -> None:
        """Write the file in a thread, off the event loop."""
        await asyncio.to_thread(self._write, transcript)

    def _write(self, transcript: ConversationTranscript) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self.path_for(transcript.call_id).write_text(transcript.as_text(), encoding="utf-8")


async def keep_transcript(
    sink: ConversationTranscriptSink,
    trace: CallTrace,
    system_prompt: str,
    messages: Sequence[LLMContextMessage],
) -> None:
    """Write the call's transcript; a failure is reported and never reaches the call."""
    try:
        await sink.write(conversation_transcript(trace, system_prompt, messages))
    except Exception as error:
        report_error(ErrorCode.TRANSCRIPT_WRITE_FAILED, error=error, call_id=trace.call_id)


def conversation_transcript(
    trace: CallTrace, system_prompt: str, messages: Sequence[LLMContextMessage]
) -> ConversationTranscript:
    """The transcript of a finished call from its trace and its model's context."""
    header = (
        f"call {trace.call_id} | business {trace.business_id or 'none'} | "
        f"started {trace.started_at.isoformat()} | outcome {trace.outcome.value}"
    )
    return ConversationTranscript(
        call_id=trace.call_id,
        header=header,
        system_prompt=system_prompt,
        lines=tuple(_lines(messages)),
    )


def _lines(messages: Sequence[LLMContextMessage]) -> Iterator[str]:
    tool_names: dict[str, str] = {}
    for message in messages:
        if isinstance(message, LLMSpecificMessage):
            yield f"({message.llm}-specific message, not shown)"
            continue
        # A standard message is one of OpenAI's chat message types: a dict by role.
        fields = cast(Mapping[str, object], message)
        role = str(fields.get("role", "unknown"))
        text = _text(fields.get("content"))
        if role == "tool":
            name = tool_names.get(str(fields.get("tool_call_id")), "a tool")
            yield f"{name} returned: {text}"
            continue
        if text:
            yield f"{_SPEAKERS.get(role, role)}: {text}"
        for call_id, name, arguments in _tool_calls(fields.get("tool_calls")):
            tool_names[call_id] = name
            yield f"agent called {name} {arguments}"


def _text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for part in content:
        if isinstance(part, dict):
            parts.append(str(part["text"]) if "text" in part else f"[{part.get('type')}]")
    return " ".join(parts).strip()


def _tool_calls(calls: object) -> list[tuple[str, str, str]]:
    if not isinstance(calls, list):
        return []
    found = []
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict):
            found.append(
                (str(call.get("id")), str(function.get("name")), str(function.get("arguments")))
            )
    return found
