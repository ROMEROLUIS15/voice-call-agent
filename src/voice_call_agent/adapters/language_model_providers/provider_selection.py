"""Selection of the language model provider."""

from collections.abc import Callable
from dataclasses import dataclass

from pipecat.services.ai_service import AIService

from voice_call_agent.settings.sections import LanguageModelProvider, LanguageModelSettings


def language_model_factory(settings: LanguageModelSettings) -> Callable[[str], AIService]:
    """Per-call factory of the configured provider's model.

    Called once at startup: each provider SDK is heavy, so only the selected one is imported,
    and never on the event loop of a call in progress.
    """
    match settings.provider:
        case LanguageModelProvider.GROQ:
            from voice_call_agent.adapters.language_model_providers.groq_model import (
                groq_model_factory,
            )

            return groq_model_factory(settings)
        case LanguageModelProvider.GOOGLE:
            from voice_call_agent.adapters.language_model_providers.google_model import (
                google_model_factory,
            )

            return google_model_factory(settings)
        case LanguageModelProvider.OPENAI:
            from voice_call_agent.adapters.language_model_providers.openai_model import (
                openai_model_factory,
            )

            return openai_model_factory(settings)
        case LanguageModelProvider.OPENROUTER:
            from voice_call_agent.adapters.language_model_providers.openrouter_model import (
                openrouter_model_factory,
            )

            return openrouter_model_factory(settings)


@dataclass(frozen=True)
class LanguageModelChoice:
    """The configured model, as recorded in every call trace."""

    provider: str
    model: str
    """The configured model, or Pipecat's default for the provider when none is configured."""
    create: Callable[[str], AIService]


def select_language_model(settings: LanguageModelSettings) -> LanguageModelChoice:
    """Factory and resolved model id of the configured provider. Called once at startup."""
    create = language_model_factory(settings)
    return LanguageModelChoice(
        provider=settings.provider.value,
        model=settings.model or _default_model(create),
        create=create,
    )


def _default_model(create: Callable[[str], AIService]) -> str:
    # Building a service opens no connection; its settings carry the provider's default model.
    model = create("").settings.model
    return model if isinstance(model, str) else "unknown"
