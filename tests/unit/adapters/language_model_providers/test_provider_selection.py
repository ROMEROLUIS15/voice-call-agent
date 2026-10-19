from typing import cast

import pytest
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.settings import LLMSettings
from pydantic import SecretStr

from voice_call_agent.adapters.language_model_providers.provider_selection import (
    language_model_factory,
)
from voice_call_agent.settings.sections import LanguageModelProvider, LanguageModelSettings


def _settings(provider: LanguageModelProvider, model: str | None = None) -> LanguageModelSettings:
    return LanguageModelSettings(
        provider=provider, api_key=SecretStr("key"), model=model, request_timeout_seconds=7.5
    )


@pytest.mark.parametrize(
    ("provider", "service_class"),
    [
        (LanguageModelProvider.GROQ, GroqLLMService),
        (LanguageModelProvider.GOOGLE, GoogleLLMService),
        (LanguageModelProvider.OPENAI, OpenAILLMService),
    ],
)
def test_provider_selects_its_service_with_the_prompt(
    provider: LanguageModelProvider, service_class: type
) -> None:
    service = language_model_factory(_settings(provider))("system prompt")
    assert isinstance(service, service_class)
    assert cast(LLMSettings, service._settings).system_instruction == "system prompt"


@pytest.mark.parametrize("provider", [LanguageModelProvider.GROQ, LanguageModelProvider.OPENAI])
def test_openai_compatible_clients_have_an_explicit_timeout(
    provider: LanguageModelProvider,
) -> None:
    service = language_model_factory(_settings(provider))("prompt")
    assert isinstance(service, OpenAILLMService)  # Groq's service extends OpenAI's.
    assert service._client.timeout == 7.5
    assert service._client.max_retries == 1


def test_google_client_has_an_explicit_timeout() -> None:
    service = language_model_factory(_settings(LanguageModelProvider.GOOGLE))("prompt")
    assert isinstance(service, GoogleLLMService)
    assert service._http_options.timeout == 7500  # milliseconds


def test_explicit_model_overrides_the_default() -> None:
    service = language_model_factory(_settings(LanguageModelProvider.GROQ, "test-model"))("p")
    assert cast(LLMSettings, service._settings).model == "test-model"
