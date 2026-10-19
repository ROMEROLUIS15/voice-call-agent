"""OpenAI language model with an explicit request timeout."""

from collections.abc import Callable, Mapping

from openai import AsyncOpenAI
from pipecat.services.ai_service import AIService
from pipecat.services.openai.base_llm import OpenAILLMSettings
from pipecat.services.openai.llm import OpenAILLMService

from voice_call_agent.adapters.language_model_providers.openai_compatible_timeouts import (
    with_request_timeout,
)
from voice_call_agent.settings.sections import LanguageModelSettings


class TimeBoundOpenAILLMService(OpenAILLMService):
    """`OpenAILLMService` whose HTTP client has an explicit request timeout."""

    def __init__(
        self, *, api_key: str, settings: OpenAILLMSettings, request_timeout_seconds: float
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


def openai_model_factory(settings: LanguageModelSettings) -> Callable[[str], AIService]:
    api_key = settings.api_key.get_secret_value()

    def create(system_prompt: str) -> AIService:
        model_settings = OpenAILLMSettings(system_instruction=system_prompt)
        if settings.model:
            model_settings.model = settings.model
        return TimeBoundOpenAILLMService(
            api_key=api_key,
            settings=model_settings,
            request_timeout_seconds=settings.request_timeout_seconds,
        )

    return create
