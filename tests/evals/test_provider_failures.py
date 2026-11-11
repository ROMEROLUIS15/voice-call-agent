"""A provider that fails during the model evals stops the run: nothing is scored or stored."""

from pathlib import Path

import httpx2
import openai
import pytest
from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.ai_service import AIService

from evals import model_evals
from evals.conversation_harness import conversation_driver
from evals.conversation_harness.conversation_driver import (
    LanguageModelConnectionLostError,
    LanguageModelUnavailableError,
    hold_conversation,
)
from evals.conversation_harness.scripted_language_model import ScriptedLanguageModel
from evals.judge_scoring import JudgeUnavailableError, measure
from evals.model_eval_runs import CaseRun, ModelUnderTest, run_cases
from evals.model_evals import EXIT_CANNOT_RUN, main
from tests.evals.eval_runs_factory import FixedScoreJudge, golden_case
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.call_trace import ServiceVersions


class RefusingLanguageModel(ScriptedLanguageModel):
    """Refuses every request, as a provider does past its rate limit."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if not isinstance(frame, LLMContextFrame):
            await super().process_frame(frame, direction)
            return
        await self.push_error("Rate limit reached", exception=RuntimeError("429"))


class DisconnectingLanguageModel(ScriptedLanguageModel):
    """Loses the connection on every request, as a stream cut by the network does."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if not isinstance(frame, LLMContextFrame):
            await super().process_frame(frame, direction)
            return
        lost = openai.APIConnectionError(request=httpx2.Request("POST", "https://provider.test"))
        await self.push_error("Error during completion: Connection error.", exception=lost)


CONTENT = load_conversation_content()
SCRIPTED_SERVICES = ServiceVersions(
    prompt_version=CONTENT.version,
    locale=CONTENT.locale,
    llm_provider="scripted",
    llm_model="scripted",
    stt_model="scripted",
    tts_voice="scripted",
)


async def test_a_failed_model_is_not_measured_as_a_stalled_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversation_driver, "_REPLY_TIMEOUT_S", 2.0)

    def create_language_model(system_prompt: str) -> AIService:
        return RefusingLanguageModel(system_prompt)

    with pytest.raises(LanguageModelUnavailableError, match="provider failed") as failure:
        await hold_conversation(
            golden_case("booking-request-on-the-test-line"),
            content=CONTENT,
            services=SCRIPTED_SERVICES,
            create_language_model=create_language_model,
        )
    # A refusal is not a lost connection: the run stops instead of holding it again.
    assert not isinstance(failure.value, LanguageModelConnectionLostError)


async def test_a_lost_connection_is_told_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation_driver, "_REPLY_TIMEOUT_S", 2.0)

    def create_language_model(system_prompt: str) -> AIService:
        return DisconnectingLanguageModel(system_prompt)

    with pytest.raises(LanguageModelConnectionLostError, match="connection"):
        await hold_conversation(
            golden_case("booking-request-on-the-test-line"),
            content=CONTENT,
            services=SCRIPTED_SERVICES,
            create_language_model=create_language_model,
        )


async def test_a_conversation_whose_connection_dropped_is_held_once_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(conversation_driver, "_REPLY_TIMEOUT_S", 2.0)
    created: list[str] = []

    def create_language_model(system_prompt: str) -> AIService:
        created.append(system_prompt)
        if len(created) == 1:
            return DisconnectingLanguageModel(system_prompt)
        return ScriptedLanguageModel(system_prompt)

    model = ModelUnderTest(CONTENT, SCRIPTED_SERVICES, create_language_model)
    case = golden_case("booking-request-on-the-test-line")
    [run] = await run_cases([case], model, FixedScoreJudge(1.0), repetitions=1)
    assert len(created) == 2
    assert run.failure is None


async def test_a_connection_lost_twice_stops_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conversation_driver, "_REPLY_TIMEOUT_S", 2.0)

    def create_language_model(system_prompt: str) -> AIService:
        return DisconnectingLanguageModel(system_prompt)

    model = ModelUnderTest(CONTENT, SCRIPTED_SERVICES, create_language_model)
    case = golden_case("booking-request-on-the-test-line")
    with pytest.raises(LanguageModelConnectionLostError):
        await run_cases([case], model, FixedScoreJudge(1.0), repetitions=1)


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


class FlakyJudgeMetric:
    """Answers as listed: a score, or DeepEval's error for a reply that is not JSON."""

    def __init__(self, *answers: float | ValueError) -> None:
        self.answers = list(answers)

    async def a_measure(self) -> float:
        answer = self.answers.pop(0)
        if isinstance(answer, ValueError):
            raise answer
        return answer


async def test_a_judge_reply_that_is_not_json_is_asked_once_more() -> None:
    not_json = ValueError("Evaluation LLM outputted an invalid JSON.")
    assert await measure(FlakyJudgeMetric(not_json, 0.9).a_measure, "judge") == 0.9
    with pytest.raises(JudgeUnavailableError, match="invalid JSON"):
        await measure(FlakyJudgeMetric(not_json, not_json).a_measure, "judge")
