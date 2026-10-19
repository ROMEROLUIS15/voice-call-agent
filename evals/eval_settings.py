"""Environment of the model evals: the model under test and the judge's key (`.env.example`).

Only environment variables are read, never a `.env` file: run locally with
`uv run --env-file .env --group evals python -m evals.model_evals`.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from voice_call_agent.settings.sections import LanguageModelProvider, LanguageModelSettings
from voice_call_agent.settings.service_settings import ServiceSettings

_SERVICE_DEFAULTS = ServiceSettings.model_fields


class ModelEvalSettings(BaseSettings):
    """The same variables as the service, so the evals measure what production runs."""

    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: LanguageModelProvider = _SERVICE_DEFAULTS["llm_provider"].default
    llm_model: str | None = _SERVICE_DEFAULTS["llm_model"].default
    llm_request_timeout_seconds: float = _SERVICE_DEFAULTS["llm_request_timeout_seconds"].default
    groq_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    """Key of the provider's model when the provider is Google, and always of the judge."""
    openai_api_key: SecretStr | None = None

    def language_model(self) -> LanguageModelSettings | None:
        """The model under test, or `None` without its provider's key."""
        api_key = {
            LanguageModelProvider.GROQ: self.groq_api_key,
            LanguageModelProvider.GOOGLE: self.google_api_key,
            LanguageModelProvider.OPENAI: self.openai_api_key,
        }[self.llm_provider]
        if api_key is None:
            return None
        return LanguageModelSettings(
            provider=self.llm_provider,
            api_key=api_key,
            model=self.llm_model,
            request_timeout_seconds=self.llm_request_timeout_seconds,
        )
