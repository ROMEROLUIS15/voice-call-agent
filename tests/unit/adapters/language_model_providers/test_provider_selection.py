from typing import cast

import pytest
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.groq.llm import GroqLLMService, GroqLLMSettings
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openrouter.llm import OpenRouterLLMService, OpenRouterLLMSettings
from pipecat.services.settings import LLMSettings
from pydantic import SecretStr

from voice_call_agent.adapters.language_model_providers.provider_selection import (
    language_model_factory,
    select_language_model,
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
        (LanguageModelProvider.OPENROUTER, OpenRouterLLMService),
    ],
)
def test_provider_selects_its_service_with_the_prompt(
    provider: LanguageModelProvider, service_class: type
) -> None:
    service = language_model_factory(_settings(provider))("system prompt")
    assert isinstance(service, service_class)
    assert cast(LLMSettings, service._settings).system_instruction == "system prompt"


@pytest.mark.parametrize(
    "provider",
    [LanguageModelProvider.GROQ, LanguageModelProvider.OPENAI, LanguageModelProvider.OPENROUTER],
)
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


def test_default_groq_model_reasons_with_low_effort() -> None:
    service = language_model_factory(_settings(LanguageModelProvider.GROQ))("p")
    assert cast(GroqLLMSettings, service._settings).reasoning_effort == "low"


def test_another_groq_model_keeps_groqs_default_effort() -> None:
    service = language_model_factory(_settings(LanguageModelProvider.GROQ, "test-model"))("p")
    assert cast(GroqLLMSettings, service._settings).reasoning_effort is None  # Not sent.


def test_selection_resolves_the_default_model_for_traces() -> None:
    choice = select_language_model(_settings(LanguageModelProvider.GROQ))
    assert choice.provider == "groq"
    assert choice.model == "openai/gpt-oss-120b"  # Pipecat's default for Groq.
    assert select_language_model(_settings(LanguageModelProvider.GROQ, "custom")).model == "custom"


TOGETHER_THEN_VENICE = OpenRouterLLMService.ProviderPreferences(
    order=["together", "venice"],
    only=["together", "venice"],
    allow_fallbacks=False,
    require_parameters=True,
    data_collection="deny",
)


def test_openrouter_sends_the_model_to_together_then_venice_with_low_effort() -> None:
    choice = select_language_model(_settings(LanguageModelProvider.OPENROUTER))
    assert (choice.provider, choice.model) == ("openrouter", "deepseek/deepseek-v4.1-flash")
    settings = cast(OpenRouterLLMSettings, choice.create("p")._settings)
    assert settings.provider == TOGETHER_THEN_VENICE
    assert settings.extra == {"extra_body": {"reasoning": {"effort": "low"}}}


def test_another_openrouter_model_goes_to_any_provider_that_collects_no_data() -> None:
    service = language_model_factory(_settings(LanguageModelProvider.OPENROUTER, "other"))("p")
    settings = cast(OpenRouterLLMSettings, service._settings)
    assert settings.model == "other"
    assert settings.provider == OpenRouterLLMService.ProviderPreferences(
        require_parameters=True, data_collection="deny"
    )
    assert settings.extra == {"extra_body": {"reasoning": {"effort": "low"}}}
