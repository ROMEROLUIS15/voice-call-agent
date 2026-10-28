"""Everything that shapes the agent's replies or their scoring, summarized in one digest.

The baseline records the inputs it was measured with; `tests/evals/test_behavior_fingerprint.py`
fails when they change, so no change to the prompt, the phrases, the model, its generation
settings, the dataset, the businesses it runs against or the metrics lands without new evals
(constitution §16). Only what the
model evals exercise counts: they run with scripted speech, so the speech-to-text model and the
voice are left out (ADR 0013).
"""

import hashlib
import json
from pathlib import Path

from pydantic import SecretStr

from evals.golden_cases import golden_dataset_version
from evals.judge_scoring import JUDGE_MODEL
from voice_call_agent.adapters.language_model_providers.provider_selection import (
    language_model_factory,
)
from voice_call_agent.booking_flow.booking_graph import booking_functions
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.practice_schedule.practice_catalog import load_practice_catalog
from voice_call_agent.settings.sections import LanguageModelProvider, LanguageModelSettings
from voice_call_agent.settings.service_settings import ServiceSettings

_EVALS_DIR = Path(__file__).parent
_SCORING_SOURCES = (
    "quality_criteria.py",
    "task_metrics.py",
    "outcome_metrics.py",
    "judge_scoring.py",
    "conversation_harness/call_transcript.py",
)
"""What decides a score: criteria, margins, repetitions, deterministic checks, the judge and
the transcript it reads."""


def _default(setting: str) -> str:
    return str(ServiceSettings.model_fields[setting].default)


def default_language_model() -> LanguageModelSettings:
    """The language model the service uses when the environment does not choose another."""
    model = ServiceSettings.model_fields["llm_model"].default
    return LanguageModelSettings(
        provider=LanguageModelProvider(_default("llm_provider")),
        api_key=SecretStr("not-used"),  # Building a service opens no connection.
        model=None if model is None else str(model),
        request_timeout_seconds=float(_default("llm_request_timeout_seconds")),
    )


def model_configuration(settings: LanguageModelSettings) -> dict[str, str]:
    """Provider, model and generation settings, as the service builds the model (prompt aside)."""
    service = language_model_factory(settings)("")
    generation = service.settings.given_fields()
    generation.pop("system_instruction", None)
    # The provider's name under its own key: OpenRouter's settings have a `provider` field too
    # (its routing preferences), which would otherwise replace it.
    return {
        "llm_provider": settings.provider.value,
        "request_timeout_seconds": str(settings.request_timeout_seconds),
    } | {name: str(value) for name, value in sorted(generation.items())}


def agent_tools() -> dict[str, object]:
    """Each function of the booking flow, as the model receives it: name, description and
    arguments (ADR 0019)."""
    return dict(booking_functions())


def behavior_inputs() -> dict[str, str]:
    """What the baseline was measured with: readable where it fits, a digest where it does not."""
    configuration = model_configuration(default_language_model())
    return {
        "conversation_content": load_conversation_content().version,
        "language_model": f"{configuration['llm_provider']} {configuration['model']}",
        "generation_settings": _digest(configuration),
        "agent_tools": _digest({name: json.dumps(tool) for name, tool in agent_tools().items()}),
        "golden_dataset": golden_dataset_version(),
        # The booking prompt the model receives is built from these businesses.
        "practice_businesses": _digest({"catalog": _practice_catalog_the_model_sees()}),
        "scoring": _digest({name: _normalized(_EVALS_DIR / name) for name in _SCORING_SOURCES}),
        "judge_model": JUDGE_MODEL,
    }


def behavior_fingerprint(inputs: dict[str, str]) -> str:
    return _digest(inputs)


def _practice_catalog_the_model_sees() -> str:
    """The practice businesses without the numbers that reach them: a number decides which
    business a call reaches, never what its model is told or does."""
    catalog = load_practice_catalog()
    unnumbered = tuple(
        business.model_copy(update={"dialed_numbers": ()}) for business in catalog.businesses
    )
    return catalog.model_copy(update={"businesses": unnumbered}).model_dump_json()


def _normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _digest(values: dict[str, str]) -> str:
    canonical = json.dumps(values, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
