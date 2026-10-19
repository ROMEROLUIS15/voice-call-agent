"""Everything that shapes the agent's replies or their scoring, summarized in one digest.

The baseline records the inputs it was measured with; `tests/evals/test_behavior_fingerprint.py`
fails when they change, so no change to the prompt, the phrases, the model, its generation
settings, the voice, the dataset or the metrics lands without new evals (constitution §16).
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
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.settings.sections import LanguageModelProvider, LanguageModelSettings
from voice_call_agent.settings.service_settings import ServiceSettings

_EVALS_DIR = Path(__file__).parent
_SCORING_SOURCES = ("quality_criteria.py", "task_metrics.py", "judge_scoring.py")
"""What decides a score: criteria, margins, repetitions, deterministic checks and the judge."""


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
    return {
        "provider": settings.provider.value,
        "request_timeout_seconds": str(settings.request_timeout_seconds),
    } | {name: str(value) for name, value in sorted(generation.items())}


def behavior_inputs() -> dict[str, str]:
    """What the baseline was measured with: readable where it fits, a digest where it does not."""
    configuration = model_configuration(default_language_model())
    return {
        "conversation_content": load_conversation_content().version,
        "language_model": f"{configuration['provider']} {configuration['model']}",
        "generation_settings": _digest(configuration),
        "stt_model": _default("stt_model"),
        "tts_voice": _default("tts_voice"),
        "golden_dataset": golden_dataset_version(),
        "scoring": _digest({name: _normalized(_EVALS_DIR / name) for name in _SCORING_SOURCES}),
        "judge_model": JUDGE_MODEL,
    }


def behavior_fingerprint(inputs: dict[str, str]) -> str:
    return _digest(inputs)


def _normalized(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _digest(values: dict[str, str]) -> str:
    canonical = json.dumps(values, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
