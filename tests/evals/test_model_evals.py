"""The model evals pipeline, with a scripted model and a fixed judge instead of providers."""

from dataclasses import replace
from datetime import date, time
from pathlib import Path
from uuid import uuid4

import pytest
from pipecat.services.ai_service import AIService

from evals import model_evals as model_evals_module
from evals.behavior_fingerprint import behavior_fingerprint, behavior_inputs
from evals.conversation_harness.call_transcript import SpokenTurn
from evals.conversation_harness.conversation_driver import ConversationRecord
from evals.conversation_harness.scripted_language_model import SCRIPTED_REPLY, ScriptedLanguageModel
from evals.conversation_harness.scripted_speech import RecordedToolCall
from evals.eval_baseline import (
    EvalBaseline,
    MeasurementSetup,
    MetricScore,
    Verdict,
    compare_with_baseline,
    load_baseline,
    save_baseline,
)
from evals.eval_report import render_report
from evals.eval_settings import ModelEvalSettings
from evals.golden_cases import EvalLevel, load_golden_dataset, runnable_cases
from evals.model_eval_runs import CaseRun, ModelUnderTest, aggregate_scores, run_cases
from evals.model_evals import EXIT_CANNOT_RUN, EXIT_OK, EXIT_REGRESSION, conclude, main
from evals.outcome_metrics import outcome_scores
from evals.quality_criteria import QUALITY_CRITERIA, QUALITY_MARGINS, MetricKind, regression_margin
from evals.task_metrics import TASK_METRICS, is_brief, is_speakable
from tests.call_trace_factory import make_call_trace
from tests.evals.eval_runs_factory import MEASURED_AT, FixedScoreJudge, case_run, golden_case
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.call_trace import ServiceVersions, WriteAction, WriteDecision
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome
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
        ("¿A qué hora te gustaría? (esperando respuesta)", False),
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
                "admits-test-line": MetricScore(kind=MetricKind.QUALITY, score=0.9),
            }
        }
    )
    current = {
        "invents-nothing": MetricScore(kind=MetricKind.SECURITY, score=0.99),
        "natural-spanish": MetricScore(kind=MetricKind.QUALITY, score=0.86),
        "admits-test-line": MetricScore(kind=MetricKind.QUALITY, score=0.84),
        "speakable-replies": MetricScore(kind=MetricKind.QUALITY, score=1.0),
    }
    verdicts = {c.metric_id: c.verdict for c in compare_with_baseline(baseline, current)}
    assert verdicts == {
        "invents-nothing": Verdict.REGRESSION,
        "natural-spanish": Verdict.OK,
        "admits-test-line": Verdict.REGRESSION,
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


def test_a_quality_drop_with_a_reason_stores_the_baseline_and_a_security_drop_never(
    tmp_path: Path,
) -> None:
    baseline = UNMEASURED.model_copy(
        update={
            "metrics": {
                "brief-replies": MetricScore(kind=MetricKind.QUALITY, score=1.0),
                "invents-nothing": MetricScore(kind=MetricKind.SECURITY, score=1.0),
            }
        }
    )
    reason = "new cases where the agent asks one more question"
    quality_drop = [case_run("booking-request-on-the-test-line", {"invents-nothing": 1.0})]
    quality_drop = [replace(run, task_scores={"brief-replies": 0.5}) for run in quality_drop]
    stored = tmp_path / "stored.json"
    exit_code = conclude(
        quality_drop,
        _scripted_model().services,
        compare_with=baseline,
        report_path=tmp_path / "report.md",
        baseline_path=stored,
        accept_drop=reason,
    )
    assert exit_code == EXIT_OK
    assert load_baseline(stored).accepted_drop == reason
    assert reason in (tmp_path / "report.md").read_text(encoding="utf-8")

    security_drop = [case_run("booking-request-on-the-test-line", {"invents-nothing": 0.2})]
    refused = tmp_path / "refused.json"
    exit_code = conclude(
        security_drop,
        _scripted_model().services,
        compare_with=baseline,
        report_path=tmp_path / "report.md",
        baseline_path=refused,
        accept_drop=reason,
    )
    assert exit_code == EXIT_REGRESSION
    assert not refused.exists()


def test_a_drop_is_accepted_only_when_writing_the_baseline() -> None:
    assert main(["--accept-drop", "a reason"]) == EXIT_CANNOT_RUN


@pytest.mark.parametrize("provider", list(LanguageModelProvider))
def test_the_evals_run_with_every_provider_the_service_accepts(
    provider: LanguageModelProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", provider.value)
    monkeypatch.setenv(f"{provider.value.upper()}_API_KEY", "test-key")
    model = ModelEvalSettings().language_model()
    assert model is not None and model.provider is provider


ASKED = ("haircut", date(2026, 10, 27), time(15, 0), "Ana Ejemplo")
"""What `book-appointment-over-whatsapp` asks for."""


def _record(
    outcome: CallOutcome,
    booking: tuple[str, date, time, str] | None = None,
    refusals: tuple[str, ...] = (),
) -> ConversationRecord:
    writes = [
        WriteDecision(
            action=WriteAction.CONFIRM_BOOKING, outcome=refusal, proposal_id=None, caller_turn=1
        )
        for refusal in refusals
    ]
    calls: list[RecordedToolCall] = []
    if booking is not None:
        service_id, day, start, name = booking
        proposal_id = uuid4()
        writes.append(
            WriteDecision(
                action=WriteAction.CONFIRM_BOOKING,
                outcome="booked",
                proposal_id=proposal_id,
                caller_turn=2,
                service_id=service_id,
                day=day,
                start=start,
            )
        )
        arguments: dict[str, object] = {"client_name": name}
        calls.append(RecordedToolCall("propose_booking", arguments, {"status": "proposed"}))
    trace = make_call_trace().model_copy(update={"outcome": outcome, "writes": writes})
    return ConversationRecord(
        trace=trace,
        agent_lines=[],
        code_lines=[],
        turns=(SpokenTurn("assistant", "", tuple(calls)),),
        system_prompt="",
        synthesized_ms=0.0,
        played_ms=0.0,
        business=None,
    )


BOOKED_AS_ASKED = {"bookings-completed": 1.0, "confirms-after-the-answer": 1.0}


@pytest.mark.parametrize(
    ("case_id", "record", "scores"),
    [
        (
            "book-appointment-over-whatsapp",
            _record(CallOutcome.BOOKED, ASKED),
            BOOKED_AS_ASKED | {"books-what-was-asked": 1.0},
        ),
        (
            "book-appointment-over-whatsapp",
            _record(CallOutcome.BOOKED, (*ASKED[:1], date(2026, 10, 28), *ASKED[2:])),
            BOOKED_AS_ASKED | {"books-what-was-asked": 0.0},  # Another day.
        ),
        (
            "book-appointment-over-whatsapp",
            _record(CallOutcome.BOOKED, (*ASKED[:3], "Otra Persona")),
            BOOKED_AS_ASKED | {"books-what-was-asked": 0.0},  # Another name.
        ),
        (
            "book-appointment-over-whatsapp",
            _record(CallOutcome.BOOKED, ASKED, refusals=("caller_has_not_answered",)),
            BOOKED_AS_ASKED | {"books-what-was-asked": 1.0, "confirms-after-the-answer": 0.0},
        ),
        (
            "book-appointment-over-whatsapp",
            _record(CallOutcome.INFO_ONLY),
            {"bookings-completed": 0.0, "confirms-after-the-answer": 1.0},
        ),
        ("book-appointment-over-whatsapp", None, {"bookings-completed": 0.0}),  # It stalled.
        (
            "no-write-without-confirmation",
            _record(CallOutcome.INFO_ONLY),
            {"no-unwanted-write": 1.0, "confirms-after-the-answer": 1.0},
        ),
        (
            "no-write-without-confirmation",
            _record(CallOutcome.BOOKED, ASKED),
            {"no-unwanted-write": 0.0, "confirms-after-the-answer": 1.0},
        ),
        (
            "booking-request-on-the-test-line",
            _record(CallOutcome.INFO_ONLY),
            {"no-unwanted-write": 1.0},
        ),
    ],
)
def test_what_the_call_wrote_is_scored_against_the_case(
    case_id: str, record: ConversationRecord | None, scores: dict[str, float]
) -> None:
    assert outcome_scores(golden_case(case_id), record) == scores


def test_a_noisy_quality_measure_has_its_own_margin_and_security_none() -> None:
    assert regression_margin("brief-replies", MetricKind.QUALITY) == 0.10
    assert regression_margin("natural-spanish", MetricKind.QUALITY) == 0.05
    assert regression_margin("brief-replies", MetricKind.SECURITY) == 0.0
    for metric_id in QUALITY_MARGINS:  # Only quality measures may widen their margin.
        assert metric_id in TASK_METRICS or QUALITY_CRITERIA[metric_id].kind is MetricKind.QUALITY
    baseline = UNMEASURED.model_copy(
        update={"metrics": {"brief-replies": MetricScore(kind=MetricKind.QUALITY, score=0.98)}}
    )
    [ok] = compare_with_baseline(
        baseline, {"brief-replies": MetricScore(kind=MetricKind.QUALITY, score=0.89)}
    )
    [regressed] = compare_with_baseline(
        baseline, {"brief-replies": MetricScore(kind=MetricKind.QUALITY, score=0.87)}
    )
    assert (ok.verdict, regressed.verdict) == (Verdict.OK, Verdict.REGRESSION)


def test_an_unwanted_write_is_a_security_measure() -> None:
    runs = [
        replace(
            case_run("no-write-without-confirmation", {}), task_scores={"no-unwanted-write": 0.0}
        ),
        replace(
            case_run("no-write-without-confirmation", {}), task_scores={"no-unwanted-write": 1.0}
        ),
    ]
    score = aggregate_scores(runs)["no-unwanted-write"]
    assert (score.kind, score.score) == (MetricKind.SECURITY, 0.5)


def test_the_report_counts_the_upstreams_that_served_the_model() -> None:
    groq = replace(case_run("booking-request-on-the-test-line", {}), llm_upstreams={"Groq": 3})
    mixed = replace(groq, llm_upstreams={"Groq": 1, "Cerebras": 1})
    report = render_report(
        model_label="openrouter m",
        judge_model="j",
        baseline=UNMEASURED,
        comparisons=[],
        runs=[groq, mixed],
    )
    assert "Upstream providers: Cerebras 1, Groq 4 responses." in report


def test_the_evals_need_both_keys() -> None:
    assert main([]) == EXIT_CANNOT_RUN


def test_the_baseline_is_measured_with_the_default_model_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-judge-key")
    monkeypatch.setenv("LLM_MODEL", "another-model")
    assert main(["--write-baseline"]) == EXIT_CANNOT_RUN


def test_a_pull_request_measures_only_when_the_behaviour_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    inputs = behavior_inputs()
    unchanged = tmp_path / "unchanged.json"
    save_baseline(EvalBaseline(fingerprint=behavior_fingerprint(inputs), inputs=inputs), unchanged)
    changed = tmp_path / "changed.json"
    save_baseline(EvalBaseline(fingerprint="measured-before", inputs=inputs), changed)
    assert main(["--only-if-changed", "--compare-with", str(unchanged)]) == EXIT_OK
    # A changed fingerprint goes on to measure, and without the keys it cannot run.
    monkeypatch.setattr(model_evals_module, "BASELINE_PATH", changed)
    assert main(["--only-if-changed", "--compare-with", str(changed)]) == EXIT_CANNOT_RUN


def test_a_change_that_carries_its_measured_baseline_is_not_measured_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    inputs = behavior_inputs()
    base = tmp_path / "base.json"
    save_baseline(EvalBaseline(fingerprint="measured-before", inputs=inputs), base)
    carried = tmp_path / "carried.json"
    setup = MeasurementSetup(
        llm_provider="openrouter",
        llm_model="m",
        judge_model="j",
        repetitions=3,
        measured_at=MEASURED_AT,
    )
    fingerprint = behavior_fingerprint(inputs)
    save_baseline(
        EvalBaseline(fingerprint=fingerprint, inputs=inputs, measured_with=setup), carried
    )
    monkeypatch.setattr(model_evals_module, "BASELINE_PATH", carried)
    assert main(["--only-if-changed", "--compare-with", str(base)]) == EXIT_OK
    # Only recorded, not measured: it is measured.
    save_baseline(EvalBaseline(fingerprint=fingerprint, inputs=inputs), carried)
    assert main(["--only-if-changed", "--compare-with", str(base)]) == EXIT_CANNOT_RUN
