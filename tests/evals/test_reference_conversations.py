"""The golden cases of the conversation level, through the real runner with scripted providers."""

from zoneinfo import ZoneInfo

import pytest
from pipecat.services.ai_service import AIService

from evals.conversation_checks import conversation_failures
from evals.conversation_harness.conversation_driver import ConversationRecord, hold_conversation
from evals.conversation_harness.schedule_conditions import HARNESS_NOW
from evals.conversation_harness.scripted_language_model import ScriptedLanguageModel
from evals.golden_cases import EvalLevel, GoldenCase, load_golden_dataset, runnable_cases
from voice_call_agent.conversation_content.business_briefing import booking_prompt
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.call_trace import ServiceVersions
from voice_call_agent.observability.conversation_transcript import ConversationTranscript

CASES = runnable_cases(load_golden_dataset(), EvalLevel.CONVERSATION)
CONTENT = load_conversation_content()
SCRIPTED_SERVICES = ServiceVersions(
    prompt_version=CONTENT.version,
    locale=CONTENT.locale,
    llm_provider="scripted",
    llm_model="scripted",
    stt_model="scripted",
    tts_voice="scripted",
)


class _RecordingTranscriptSink:
    def __init__(self) -> None:
        self.transcripts: list[ConversationTranscript] = []

    async def write(self, transcript: ConversationTranscript) -> None:
        self.transcripts.append(transcript)


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_reference_conversation(case: GoldenCase) -> None:
    models: list[ScriptedLanguageModel] = []

    def create_language_model(system_prompt: str) -> AIService:
        models.append(ScriptedLanguageModel(system_prompt, case.expected.tool_call))
        return models[-1]

    transcripts = _RecordingTranscriptSink()
    record = await hold_conversation(
        case,
        content=CONTENT,
        services=SCRIPTED_SERVICES,
        create_language_model=create_language_model,
        transcript_sink=transcripts,
    )

    greeting = record.business.greeting if record.business else CONTENT.greeting
    assert conversation_failures(case, record, greeting) == []
    [model] = models
    assert model.system_prompt == _expected_prompt(record) == record.system_prompt
    # The model hears every caller turn, in order, whatever the agent was saying.
    assert model.caller_messages == [turn.says for turn in case.turns]
    assert record.trace.services.prompt_version == CONTENT.version
    _assert_the_transcript_is_in_order(case, record)
    [transcript] = transcripts.transcripts
    _assert_the_kept_transcript_shows_what_was_said(case, record, transcript, greeting)


def _assert_the_transcript_is_in_order(case: GoldenCase, record: ConversationRecord) -> None:
    """What the judge reads: every turn in order, each tool after the caller turn that asked
    for it and with the line spoken after its result."""
    turns = record.turns
    callers = [index for index, turn in enumerate(turns) if turn.role == "user"]
    assert [turns[index].text for index in callers] == [turn.says for turn in case.turns]
    assert [t.text for t in turns if t.role == "assistant" and t.text] == record.agent_lines
    tools = [(index, call.name) for index, turn in enumerate(turns) for call in turn.tool_calls]
    if case.expected.tool_call is None:
        assert tools == []
        return
    # The scripted model proposes on the first caller turn and confirms on the second.
    assert [name for _, name in tools] == ["propose_booking", "confirm_booking"]
    (proposed, _), (confirmed, _) = tools
    assert callers[0] < proposed < callers[1] < confirmed


def _assert_the_kept_transcript_shows_what_was_said(
    case: GoldenCase, record: ConversationRecord, transcript: ConversationTranscript, greeting: str
) -> None:
    """What a developer reads after a practice call (ADR 0017): the prompt, what the agent said
    as far as the caller heard it, each caller turn as heard and each tool call with its result,
    in order."""
    assert transcript.call_id == record.trace.call_id
    assert f"outcome {record.trace.outcome.value}" in transcript.header
    assert transcript.system_prompt == record.system_prompt
    lines = transcript.lines
    if not record.agent_interrupted:  # An interrupted line keeps only what was spoken.
        assert lines[0] == f"agent: {greeting}"
    callers = [line for line in lines if line.startswith("caller: ")]
    assert callers == [f"caller: {turn.says}" for turn in case.turns]
    tools = [line.split()[2] for line in lines if line.startswith("agent called ")]
    results = [line.split()[0] for line in lines if " returned: " in line]
    expected = [] if case.expected.tool_call is None else ["propose_booking", "confirm_booking"]
    assert tools == results == expected


def _expected_prompt(record: ConversationRecord) -> str:
    """The booking prompt of the business the call resolved, or the one that books nothing."""
    if record.business is None:
        return CONTENT.system_prompt
    today = HARNESS_NOW.astimezone(ZoneInfo(record.business.timezone)).date()
    return booking_prompt(CONTENT, record.business, today)


def test_the_conversation_level_covers_greeting_interruption_identity_and_booking() -> None:
    tags = {tag for case in CASES for tag in case.tags}
    assert {"greeting", "interruption", "identity", "booking"} <= tags
    assert {case.channel.value for case in CASES} == {"twilio", "whatsapp"}
