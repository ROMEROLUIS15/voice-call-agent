"""Selection of the language model provider."""

from collections.abc import Callable

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
