"""No change to what shapes the agent's replies lands without regenerating the evals baseline."""

from pathlib import Path

from pydantic import SecretStr

from evals.behavior_fingerprint import (
    behavior_fingerprint,
    behavior_inputs,
    default_language_model,
    model_configuration,
)
from evals.eval_baseline import (
    EvalBaseline,
    MeasurementSetup,
    load_baseline,
    save_baseline,
)
from evals.model_evals import EXIT_CANNOT_RUN, EXIT_OK, record_unmeasured_fingerprint
from tests.evals.eval_runs_factory import MEASURED_AT

REGENERATE = (
    "What shapes the agent's replies changed (inputs above). Run the model evals and store "
    "the new baseline: uv run --env-file .env --group evals python -m evals.model_evals "
    "--write-baseline (docs/evals/golden-dataset.md)."
)


def test_the_baseline_was_measured_with_the_current_behavior() -> None:
    baseline = load_baseline()
    assert baseline.inputs == behavior_inputs(), REGENERATE
    assert baseline.fingerprint == behavior_fingerprint(baseline.inputs)


def test_the_model_configuration_follows_the_configured_model() -> None:
    default = default_language_model()
    other = default.model_copy(update={"model": "another-model", "api_key": SecretStr("x")})
    assert model_configuration(other)["model"] == "another-model"
    assert model_configuration(other) != model_configuration(default)


def test_the_fingerprint_is_recorded_without_measuring_only_until_measured(
    tmp_path: Path,
) -> None:
    path = tmp_path / "baseline.json"
    assert record_unmeasured_fingerprint(path) == EXIT_OK
    assert not load_baseline(path).measured

    measured = EvalBaseline(
        fingerprint="old",
        inputs={},
        measured_with=MeasurementSetup(
            llm_provider="groq",
            llm_model="m",
            judge_model="j",
            repetitions=3,
            measured_at=MEASURED_AT,
        ),
    )
    save_baseline(measured, path)
    assert record_unmeasured_fingerprint(path) == EXIT_CANNOT_RUN
    assert load_baseline(path).fingerprint == "old"
