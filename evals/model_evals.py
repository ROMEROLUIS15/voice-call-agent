"""Model evals against the baseline (`docs/evals/golden-dataset.md`, ADR 0010).

    uv run --env-file .env --group evals python -m evals.model_evals [options]

Runs every active model-level golden case with the configured language model, scores the
conversations (task metrics and the judge) and compares them with a baseline. Needs the key of
the model's provider and `OPENROUTER_API_KEY` for the judge. Exit code: 0 no regression,
1 regression, 2 the evals could not run (a missing key, or a provider that failed during the run).
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from evals.behavior_fingerprint import (
    behavior_fingerprint,
    behavior_inputs,
    default_language_model,
    model_configuration,
)
from evals.conversation_harness.conversation_driver import LanguageModelUnavailableError
from evals.eval_baseline import (
    BASELINE_PATH,
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
from evals.judge_scoring import JUDGE_MODEL, ConversationJudge, JudgeUnavailableError
from evals.model_eval_runs import (
    CaseRun,
    ModelUnderTest,
    aggregate_scores,
    run_cases,
)
from evals.quality_criteria import REPETITIONS
from voice_call_agent.adapters.language_model_providers.provider_selection import (
    LanguageModelChoice,
    select_language_model,
)
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.observability.call_trace import ServiceVersions
from voice_call_agent.settings.sections import LanguageModelSettings

EXIT_OK, EXIT_REGRESSION, EXIT_CANNOT_RUN = 0, 1, 2
_DEFAULT_REPORT = Path("var/evals/report.md")


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals.model_evals")
    parser.add_argument("--compare-with", type=Path, default=BASELINE_PATH, metavar="BASELINE")
    parser.add_argument("--report", type=Path, default=_DEFAULT_REPORT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--write-baseline",
        action="store_true",
        help="measure and, without regression, store the scores as the new baseline",
    )
    action.add_argument(
        "--record-fingerprint",
        action="store_true",
        help="record the behaviour inputs without measuring; only while never measured",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(argv)
    if arguments.record_fingerprint:
        return record_unmeasured_fingerprint(BASELINE_PATH)
    settings = ModelEvalSettings()
    model = settings.language_model()
    if model is None or settings.openrouter_api_key is None:
        print(
            "Cannot run: the model's provider key and OPENROUTER_API_KEY (the judge's) are needed."
        )
        return EXIT_CANNOT_RUN
    if arguments.write_baseline and _differs_from_default(model):
        print("Cannot write the baseline: it is measured with the default model only.")
        return EXIT_CANNOT_RUN
    under_test = model_under_test(select_language_model(model))
    judge = ConversationJudge(settings.openrouter_api_key.get_secret_value())
    try:
        runs = asyncio.run(
            run_cases(runnable_cases(load_golden_dataset(), EvalLevel.MODEL), under_test, judge)
        )
    except (LanguageModelUnavailableError, JudgeUnavailableError) as error:
        # Scoring these conversations would measure the provider, not the agent.
        print(f"Cannot run: {error}. Nothing was scored or stored; run the evals again.")
        return EXIT_CANNOT_RUN
    return conclude(
        runs,
        under_test.services,
        compare_with=load_baseline(arguments.compare_with),
        report_path=arguments.report,
        baseline_path=BASELINE_PATH if arguments.write_baseline else None,
    )


def model_under_test(choice: LanguageModelChoice) -> ModelUnderTest:
    content = load_conversation_content()
    return ModelUnderTest(
        content=content,
        services=ServiceVersions(
            prompt_version=content.version,
            locale=content.locale,
            llm_provider=choice.provider,
            llm_model=choice.model,
            stt_model="scripted",
            tts_voice="scripted",
        ),
        create_language_model=choice.create,
    )


def conclude(
    runs: list[CaseRun],
    services: ServiceVersions,
    *,
    compare_with: EvalBaseline,
    report_path: Path,
    baseline_path: Path | None,
) -> int:
    """Score, compare and report; store the new baseline in `baseline_path` if given."""
    scores = aggregate_scores(runs)
    comparisons = compare_with_baseline(compare_with, scores)
    report = render_report(
        model_label=f"{services.llm_provider} {services.llm_model}",
        judge_model=JUDGE_MODEL,
        baseline=compare_with,
        comparisons=comparisons,
        runs=runs,
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(report)
    if any(comparison.verdict is Verdict.REGRESSION for comparison in comparisons):
        return EXIT_REGRESSION
    if baseline_path is not None:
        baseline = measured_baseline(scores, services.llm_provider, services.llm_model)
        save_baseline(baseline, baseline_path)
    return EXIT_OK


def measured_baseline(scores: dict[str, MetricScore], provider: str, model: str) -> EvalBaseline:
    inputs = behavior_inputs()
    return EvalBaseline(
        fingerprint=behavior_fingerprint(inputs),
        inputs=inputs,
        measured_with=MeasurementSetup(
            llm_provider=provider,
            llm_model=model,
            judge_model=JUDGE_MODEL,
            repetitions=REPETITIONS,
            measured_at=datetime.now(UTC),
        ),
        metrics=scores,
    )


def record_unmeasured_fingerprint(path: Path) -> int:
    """Bootstrap only: once a baseline is measured, new inputs need new measurements."""
    if path.exists() and load_baseline(path).measured:
        print("The baseline is measured: run the evals with --write-baseline instead.")
        return EXIT_CANNOT_RUN
    inputs = behavior_inputs()
    save_baseline(EvalBaseline(fingerprint=behavior_fingerprint(inputs), inputs=inputs), path)
    return EXIT_OK


def _differs_from_default(model: LanguageModelSettings) -> bool:
    return model_configuration(model) != model_configuration(default_language_model())


if __name__ == "__main__":
    sys.exit(main())
