"""No change to what shapes the agent's replies lands without regenerating the evals baseline."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from evals import behavior_fingerprint as behavior_fingerprint_module
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
from voice_call_agent.practice_schedule.practice_catalog import load_practice_catalog

REGENERATE = (
    "What shapes the agent's replies changed (inputs above). Run the model evals and store "
    "the new baseline: uv run --env-file .env --group evals python -m evals.model_evals "
    "--write-baseline (docs/evals/golden-dataset.md)."
)


def test_the_baseline_was_measured_with_the_current_behavior() -> None:
    baseline = load_baseline()
    assert baseline.inputs == behavior_inputs(), REGENERATE
    assert baseline.fingerprint == behavior_fingerprint(baseline.inputs)


def test_the_numbers_that_reach_a_business_do_not_change_the_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A number decides which business a call reaches, never what its model is told."""
    catalog = load_practice_catalog()
    renumbered = catalog.model_copy(
        update={
            "businesses": tuple(
                business.model_copy(update={"dialed_numbers": ("+12025550199",)})
                if business.id == catalog.default_business
                else business
                for business in catalog.businesses
            )
        }
    )
    before = behavior_inputs()["practice_businesses"]
    monkeypatch.setattr(behavior_fingerprint_module, "load_practice_catalog", lambda: renumbered)
    assert behavior_inputs()["practice_businesses"] == before


def test_the_language_model_input_names_the_provider_and_the_model() -> None:
    """OpenRouter's settings carry a `provider` field of their own (its routing preferences)."""
    assert behavior_inputs()["language_model"] == "openrouter deepseek/deepseek-v4.1-flash"


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
