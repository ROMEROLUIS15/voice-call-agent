"""The golden cases of the conversation level, through the real runner with scripted providers."""

import pytest
from pipecat.services.ai_service import AIService

from evals.conversation_checks import conversation_failures
from evals.conversation_harness.conversation_driver import hold_conversation
from evals.conversation_harness.scripted_language_model import ScriptedLanguageModel
from evals.golden_cases import EvalLevel, GoldenCase, load_golden_dataset, runnable_cases
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.call_trace import ServiceVersions

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


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_reference_conversation(case: GoldenCase) -> None:
    models: list[ScriptedLanguageModel] = []

    def create_language_model(system_prompt: str) -> AIService:
        models.append(ScriptedLanguageModel(system_prompt))
        return models[-1]

    record = await hold_conversation(
        case,
        content=CONTENT,
        services=SCRIPTED_SERVICES,
        create_language_model=create_language_model,
    )

    assert conversation_failures(case, record, CONTENT.greeting) == []
    [model] = models
    assert model.system_prompt == CONTENT.system_prompt
    # The model hears every caller turn, in order, whatever the agent was saying.
    assert model.caller_messages == [turn.says for turn in case.turns]
    assert record.trace.services.prompt_version == CONTENT.version


def test_the_conversation_level_covers_greeting_interruption_and_identity() -> None:
    tags = {tag for case in CASES for tag in case.tags}
    assert {"greeting", "interruption", "identity"} <= tags
    assert {case.channel.value for case in CASES} == {"twilio", "whatsapp"}
