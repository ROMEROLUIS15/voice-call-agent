"""Google Gemini language model with an explicit request timeout."""

from collections.abc import Callable

from google.genai.types import HttpOptions
from pipecat.services.ai_service import AIService
from pipecat.services.google.llm import GoogleLLMService

from voice_call_agent.settings.sections import LanguageModelSettings


def google_model_factory(settings: LanguageModelSettings) -> Callable[[str], AIService]:
    api_key = settings.api_key.get_secret_value()
    timeout_ms = int(settings.request_timeout_seconds * 1000)

    def create(system_prompt: str) -> AIService:
        model_settings = GoogleLLMService.Settings(system_instruction=system_prompt)
        if settings.model:
            model_settings.model = settings.model
        return GoogleLLMService(
            api_key=api_key,
            settings=model_settings,
            # The google-genai client takes its timeout in milliseconds.
            http_options=HttpOptions(timeout=timeout_ms),
            stream_idle_timeout_secs=settings.request_timeout_seconds,
        )

    return create
