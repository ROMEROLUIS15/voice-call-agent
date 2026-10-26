"""Groq's model through OpenRouter, with an explicit request timeout.

For networks Groq refuses (manifest §10): OpenRouter forwards each request to Groq only, so the
model and its provider stay the ones measured in phase 0.
"""

from collections.abc import Callable, Mapping

from openai import AsyncOpenAI
from pipecat.services.ai_service import AIService
from pipecat.services.openrouter.llm import (
    OpenRouterLLMService,
    OpenRouterLLMSettings,
    OpenRouterProviderPreferences,
)

from voice_call_agent.adapters.language_model_providers.openai_compatible_timeouts import (
    with_request_timeout,
)
from voice_call_agent.settings.sections import LanguageModelSettings

DEFAULT_MODEL = "openai/gpt-oss-120b"
"""OpenRouter's id for the model the service uses on Groq (manifest §7)."""
ONLY_GROQ = OpenRouterProviderPreferences(only=["groq"], allow_fallbacks=False)
"""Never another provider: a different one would answer with other latency and data terms."""


class TimeBoundOpenRouterLLMService(OpenRouterLLMService):
    """`OpenRouterLLMService` whose HTTP client has an explicit request timeout."""

    def __init__(
        self, *, api_key: str, settings: OpenRouterLLMSettings, request_timeout_seconds: float
    ) -> None:
        # The base initializer calls `create_client`, so the timeout is stored first.
        self._request_timeout_seconds = request_timeout_seconds
        super().__init__(api_key=api_key, settings=settings)

    def create_client(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        organization: str | None = None,
        project: str | None = None,
        default_headers: Mapping[str, str] | None = None,
        **kwargs: object,
    ) -> AsyncOpenAI:
        # Pipecat's `create_client` carries no annotations.
        client = super().create_client(  # type: ignore[no-untyped-call]
            api_key=api_key,
            base_url=base_url,
            organization=organization,
            project=project,
            default_headers=default_headers,
            **kwargs,
        )
        return with_request_timeout(client, self._request_timeout_seconds)


def openrouter_model_factory(settings: LanguageModelSettings) -> Callable[[str], AIService]:
    api_key = settings.api_key.get_secret_value()

    def create(system_prompt: str) -> AIService:
        model_settings = OpenRouterLLMSettings(
            system_instruction=system_prompt,
            model=settings.model or DEFAULT_MODEL,
            provider=ONLY_GROQ,
        )
        if not settings.model:
            # The same low reasoning effort as on Groq directly (manifest §7), in OpenRouter's
            # own request field.
            model_settings.extra = {"extra_body": {"reasoning": {"effort": "low"}}}
        return TimeBoundOpenRouterLLMService(
            api_key=api_key,
            settings=model_settings,
            request_timeout_seconds=settings.request_timeout_seconds,
        )

    return create
