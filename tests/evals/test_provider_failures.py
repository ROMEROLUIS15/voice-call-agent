"""A provider that fails during the model evals stops the run: nothing is scored or stored."""

from pathlib import Path

import pytest
from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.ai_service import AIService

from evals import model_evals
from evals.conversation_harness import conversation_driver
from evals.conversation_harness.conversation_driver import (
    LanguageModelUnavailableError,
    hold_conversation,
)
from evals.conversation_harness.scripted_language_model import ScriptedLanguageModel
from evals.judge_scoring import JudgeUnavailableError
from evals.model_eval_runs import CaseRun
from evals.model_evals import EXIT_CANNOT_RUN, main
from tests.evals.eval_runs_factory import golden_case
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.call_trace import ServiceVersions


class RefusingLanguageModel(ScriptedLanguageModel):
    """Refuses every request, as a provider does past its rate limit."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if not isinstance(frame, LLMContextFrame):
            await super().process_frame(frame, direction)
            return
        await self.push_error("Rate limit reached", exception=RuntimeError("429"))


async def test_a_failed_model_is_not_measured_as_a_stalled_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversation_driver, "_REPLY_TIMEOUT_S", 2.0)
    content = load_conversation_content()

    def create_language_model(system_prompt: str) -> AIService:
        return RefusingLanguageModel(system_prompt)

    with pytest.raises(LanguageModelUnavailableError, match="provider failed"):
        await hold_conversation(
            golden_case("booking-request-on-the-test-line"),
            content=content,
            services=ServiceVersions(
                prompt_version=content.version,
                locale=content.locale,
                llm_provider="scripted",
                llm_model="scripted",
                stt_model="scripted",
                tts_voice="scripted",
            ),
            create_language_model=create_language_model,
        )


@pytest.mark.parametrize(
    "failure",
    [
        LanguageModelUnavailableError("a case: the language model's provider failed"),
        JudgeUnavailableError("the judge failed: 503 UNAVAILABLE"),
    ],
)
def test_a_provider_failure_during_the_run_cannot_run(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-judge-key")

    async def failing_run(*_: object, **__: object) -> list[CaseRun]:
        raise failure

    monkeypatch.setattr(model_evals, "run_cases", failing_run)
    monkeypatch.setattr(model_evals, "ConversationJudge", lambda api_key: object())
    report = tmp_path / "report.md"

    assert main(["--report", str(report)]) == EXIT_CANNOT_RUN
    assert not report.exists()
    assert "Nothing was scored or stored" in capsys.readouterr().out
