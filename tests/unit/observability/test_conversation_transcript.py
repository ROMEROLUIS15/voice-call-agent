"""A call's transcript: what was said, in order, kept in a local file named after the call."""

from pathlib import Path
from typing import cast

from pipecat.processors.aggregators.llm_context import LLMContextMessage, LLMSpecificMessage

from tests.browser_peer import reported_error_codes
from tests.call_trace_factory import make_call_trace
from voice_call_agent.observability.conversation_transcript import (
    ConversationTranscript,
    TextFileTranscriptSink,
    conversation_transcript,
    keep_transcript,
)

GREETING = "Hola, gracias por llamar. ¿En qué te puedo ayudar?"
ARGUMENTS = '{"service_id": "haircut", "day": "2026-10-30"}'
MESSAGES = cast(
    list[LLMContextMessage],
    [
        {"role": "assistant", "content": GREETING},
        {"role": "user", "content": " Quiero un corte el viernes. "},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "check_availability", "arguments": ARGUMENTS},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": '{"slots": ["15:00"]}'},
        {"role": "assistant", "content": [{"type": "text", "text": "Tengo a las tres."}]},
        {"role": "tool", "tool_call_id": "unknown", "content": "{}"},
        LLMSpecificMessage(llm="google", message={"parts": []}),
    ],
)


def test_each_message_becomes_a_line_in_the_order_it_was_said() -> None:
    transcript = conversation_transcript(make_call_trace(call_id="practice-1"), "prompt", MESSAGES)

    assert transcript.lines == (
        f"agent: {GREETING}",
        "caller: Quiero un corte el viernes.",
        f"agent called check_availability {ARGUMENTS}",
        'check_availability returned: {"slots": ["15:00"]}',
        "agent: Tengo a las tres.",
        "a tool returned: {}",
        "(google-specific message, not shown)",
    )
    assert transcript.header.startswith("call practice-1 | business none | started 2026-10-19")
    assert transcript.header.endswith("outcome info_only")


def test_the_text_holds_the_prompt_and_then_the_conversation() -> None:
    transcript = conversation_transcript(make_call_trace(), "Eres la recepcionista.", MESSAGES)

    text = transcript.as_text()

    assert text.index("--- prompt ---\nEres la recepcionista.") < text.index(
        f"--- conversation ---\nagent: {GREETING}"
    )


async def test_the_file_is_named_after_the_call_and_never_leaves_its_directory(
    tmp_path: Path,
) -> None:
    sink = TextFileTranscriptSink(tmp_path / "transcripts")
    trace = make_call_trace(call_id="../../outside/practice.1")

    await sink.write(conversation_transcript(trace, "prompt", MESSAGES))

    [written] = (tmp_path / "transcripts").iterdir()
    assert written.name == "______outside_practice_1.txt"
    assert GREETING in written.read_text(encoding="utf-8")


async def test_a_transcript_that_cannot_be_written_is_reported_and_never_raised() -> None:
    class _BrokenSink:
        async def write(self, transcript: ConversationTranscript) -> None:
            raise OSError("disk full")

    with reported_error_codes() as codes:
        await keep_transcript(_BrokenSink(), make_call_trace(), "prompt", MESSAGES)

    assert codes == ["TRANSCRIPT_WRITE_FAILED"]
