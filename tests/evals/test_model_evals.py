"""The model evals pipeline, with a scripted model and a fixed judge instead of providers."""

from pathlib import Path

import pytest
from pipecat.services.ai_service import AIService

from evals.conversation_harness.scripted_language_model import SCRIPTED_REPLY, ScriptedLanguageModel
from evals.eval_baseline import EvalBaseline, MetricScore, Verdict, compare_with_baseline
from evals.eval_settings import ModelEvalSettings
from evals.golden_cases import EvalLevel, load_golden_dataset, runnable_cases
from evals.model_eval_runs import CaseRun, ModelUnderTest, aggregate_scores, run_cases
from evals.model_evals import EXIT_CANNOT_RUN, EXIT_OK, EXIT_REGRESSION, conclude, main
from evals.quality_criteria import MetricKind
from evals.task_metrics import is_brief, is_speakable
from tests.evals.eval_runs_factory import FixedScoreJudge, case_run
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.call_trace import ServiceVersions
from voice_call_agent.settings.sections import LanguageModelProvider

UNMEASURED = EvalBaseline(fingerprint="f", inputs={})


def _scripted_model() -> ModelUnderTest:
    content = load_conversation_content()

    def create(system_prompt: str) -> AIService:
        return ScriptedLanguageModel(system_prompt)

    services = ServiceVersions(
        prompt_version=content.version,
        locale=content.locale,
        llm_provider="scripted",
        llm_model="scripted",
        stt_model="scripted",
        tts_voice="scripted",
    )
    return ModelUnderTest(content=content, services=services, create_language_model=create)


@pytest.mark.parametrize(
    ("reply", "speakable"),
    [
        ("Claro, a las tres y media de la tarde.", True),
        ("Claro, a las 3:30.", False),
        ("Tenemos:\n- corte\n- barba", False),
        ("**Listo**", False),
        ("¡Perfecto! 😊", False),
    ],
)
def test_speakable_replies(reply: str, speakable: bool) -> None:
    assert is_speakable(reply) is speakable


def test_brief_replies() -> None:
    assert is_brief("Hola. ¿En qué te ayudo?")
    assert is_brief("Sin puntuación final")
    assert not is_brief("Uno. Dos. Tres.")


def test_security_counts_met_or_not_and_quality_averages() -> None:
    runs = [
        case_run(
            "booking-request-on-the-test-line", {"invents-nothing": 0.9, "natural-spanish": 0.8}
        ),
        case_run(
            "booking-request-on-the-test-line", {"invents-nothing": 0.4, "natural-spanish": 0.6}
        ),
    ]
    scores = aggregate_scores(runs)
    assert scores["invents-nothing"] == MetricScore(kind=MetricKind.SECURITY, score=0.5)
    assert scores["natural-spanish"] == MetricScore(kind=MetricKind.QUALITY, score=0.7)


def test_security_may_not_drop_and_quality_may_drop_by_its_margin() -> None:
    baseline = UNMEASURED.model_copy(
        update={
            "metrics": {
                "invents-nothing": MetricScore(kind=MetricKind.SECURITY, score=1.0),
                "natural-spanish": MetricScore(kind=MetricKind.QUALITY, score=0.9),
                "brief-replies": MetricScore(kind=MetricKind.QUALITY, score=0.9),
            }
        }
    )
    current = {
        "invents-nothing": MetricScore(kind=MetricKind.SECURITY, score=0.99),
        "natural-spanish": MetricScore(kind=MetricKind.QUALITY, score=0.86),
        "brief-replies": MetricScore(kind=MetricKind.QUALITY, score=0.84),
        "speakable-replies": MetricScore(kind=MetricKind.QUALITY, score=1.0),
    }
    verdicts = {c.metric_id: c.verdict for c in compare_with_baseline(baseline, current)}
    assert verdicts == {
        "invents-nothing": Verdict.REGRESSION,
        "natural-spanish": Verdict.OK,
        "brief-replies": Verdict.REGRESSION,
        "speakable-replies": Verdict.NEW,
    }


async def test_the_model_cases_run_and_replace_an_unmeasured_baseline(tmp_path: Path) -> None:
    cases = runnable_cases(load_golden_dataset(), EvalLevel.MODEL)
    judge = FixedScoreJudge(1.0)
    model = _scripted_model()
    runs = await run_cases(cases, model, judge, repetitions=1)

    assert [run.failure for run in runs] == [None] * len(cases)
    for record in judge.records:
        assert record.agent_lines[1:] == [SCRIPTED_REPLY] * (len(record.agent_lines) - 1)
    baseline_path = tmp_path / "baseline.json"
    exit_code = conclude(
        runs,
        model.services,
        compare_with=UNMEASURED,
        report_path=tmp_path / "report.md",
        baseline_path=baseline_path,
    )
    assert exit_code == EXIT_OK
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "No regression." in report
    assert "| invents-nothing | security | — | 1.00 | 0.00 | new |" in report
    measured = EvalBaseline.model_validate_json(baseline_path.read_text(encoding="utf-8"))
    assert measured.measured
    assert measured.metrics["invents-nothing"].score == 1.0


def test_a_regression_fails_and_keeps_the_baseline(tmp_path: Path) -> None:
    baseline = UNMEASURED.model_copy(
        update={"metrics": {"invents-nothing": MetricScore(kind=MetricKind.SECURITY, score=1.0)}}
    )
    runs: list[CaseRun] = [
        case_run(
            "booking-request-on-the-test-line",
            {"invents-nothing": 0.2},
            replies=("Listo, te agendé mañana a las tres.",),
        )
    ]
    baseline_path = tmp_path / "baseline.json"
    exit_code = conclude(
        runs,
        _scripted_model().services,
        compare_with=baseline,
        report_path=tmp_path / "report.md",
        baseline_path=baseline_path,
    )
    assert exit_code == EXIT_REGRESSION
    assert not baseline_path.exists()
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "REGRESSION: invents-nothing" in report
    assert "Judge `invents-nothing` 0.20: because" in report


@pytest.mark.parametrize("provider", list(LanguageModelProvider))
def test_the_evals_run_with_every_provider_the_service_accepts(
    provider: LanguageModelProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", provider.value)
    monkeypatch.setenv(f"{provider.value.upper()}_API_KEY", "test-key")
    model = ModelEvalSettings().language_model()
    assert model is not None and model.provider is provider


def test_the_evals_need_both_keys() -> None:
    assert main([]) == EXIT_CANNOT_RUN


def test_the_baseline_is_measured_with_the_default_model_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("LLM_MODEL", "another-model")
    assert main(["--write-baseline"]) == EXIT_CANNOT_RUN
