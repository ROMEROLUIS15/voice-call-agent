"""Service settings read from environment variables (and from `.env` in development).

An entry (phone line, WhatsApp) is enabled only when its group of variables is complete; a
partial group is a startup error, not an entry that fails on its first call.
"""

from pathlib import Path
from typing import Self

from pydantic import HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from voice_call_agent.settings.sections import (
    CallSupervisionSettings,
    LanguageModelProvider,
    LanguageModelSettings,
    LatencyLogSettings,
    LogFormat,
    LogSettings,
    ServerSettings,
    SpeechSettings,
    TwilioMediaStreamsSettings,
    WhatsAppCallingSettings,
)
from voice_call_agent.settings.settings_errors import IncompleteSettingsError


class ServiceSettings(BaseSettings):
    """Environment variables of the service. Documented in `.env.example`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        hide_input_in_errors=True,
    )

    host: str = "127.0.0.1"
    port: int = 8000

    deepgram_api_key: SecretStr
    stt_model: str = "flux-general-multi"
    tts_voice: str = "aura-2-selena-es"

    llm_provider: LanguageModelProvider = LanguageModelProvider.GROQ
    llm_model: str | None = None
    llm_request_timeout_seconds: float = 10.0
    groq_api_key: SecretStr | None = None
    google_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None

    public_base_url: HttpUrl | None = None
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_handshake_timeout_seconds: float = 5.0
    twilio_api_timeout_seconds: float = 5.0

    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_verify_token: SecretStr | None = None
    whatsapp_graph_api_timeout_seconds: float = 5.0

    max_concurrent_calls: int = 10
    shutdown_grace_seconds: float = 300.0

    latency_log_path: Path = Path("var/latency.jsonl")
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON

    @model_validator(mode="after")
    def _check_groups(self) -> Self:
        if self._llm_api_key() is None:
            raise IncompleteSettingsError(f"Missing API key for LLM provider '{self.llm_provider}'")
        _require_complete_group(
            "Twilio Media Streams",
            self.public_base_url,
            self.twilio_account_sid,
            self.twilio_auth_token,
        )
        _require_complete_group(
            "WhatsApp Calling",
            self.whatsapp_access_token,
            self.whatsapp_phone_number_id,
            self.whatsapp_app_secret,
            self.whatsapp_verify_token,
        )
        return self

    def server(self) -> ServerSettings:
        return ServerSettings(host=self.host, port=self.port)

    def speech(self) -> SpeechSettings:
        return SpeechSettings(
            deepgram_api_key=self.deepgram_api_key,
            stt_model=self.stt_model,
            tts_voice=self.tts_voice,
        )

    def language_model(self) -> LanguageModelSettings:
        api_key = self._llm_api_key()
        if api_key is None:  # Already rejected by the validator; repeated for the type checker.
            raise IncompleteSettingsError(f"Missing API key for LLM provider '{self.llm_provider}'")
        return LanguageModelSettings(
            provider=self.llm_provider,
            api_key=api_key,
            model=self.llm_model,
            request_timeout_seconds=self.llm_request_timeout_seconds,
        )

    def twilio_media_streams(self) -> TwilioMediaStreamsSettings | None:
        """Phone-line entry settings, or `None` when the entry is disabled."""
        if not (self.public_base_url and self.twilio_account_sid and self.twilio_auth_token):
            return None
        return TwilioMediaStreamsSettings(
            public_base_url=self.public_base_url,
            account_sid=self.twilio_account_sid,
            auth_token=self.twilio_auth_token,
            handshake_timeout_seconds=self.twilio_handshake_timeout_seconds,
            api_timeout_seconds=self.twilio_api_timeout_seconds,
        )

    def whatsapp_calling(self) -> WhatsAppCallingSettings | None:
        """WhatsApp entry settings, or `None` when the entry is disabled."""
        if not (
            self.whatsapp_access_token
            and self.whatsapp_phone_number_id
            and self.whatsapp_app_secret
            and self.whatsapp_verify_token
        ):
            return None
        return WhatsAppCallingSettings(
            access_token=self.whatsapp_access_token,
            phone_number_id=self.whatsapp_phone_number_id,
            app_secret=self.whatsapp_app_secret,
            verify_token=self.whatsapp_verify_token,
            graph_api_timeout_seconds=self.whatsapp_graph_api_timeout_seconds,
        )

    def call_supervision(self) -> CallSupervisionSettings:
        return CallSupervisionSettings(
            max_concurrent_calls=self.max_concurrent_calls,
            shutdown_grace_seconds=self.shutdown_grace_seconds,
        )

    def latency_log(self) -> LatencyLogSettings:
        return LatencyLogSettings(path=self.latency_log_path)

    def logging_output(self) -> LogSettings:
        return LogSettings(level=self.log_level, output_format=self.log_format)

    def _llm_api_key(self) -> SecretStr | None:
        keys = {
            LanguageModelProvider.GROQ: self.groq_api_key,
            LanguageModelProvider.GOOGLE: self.google_api_key,
            LanguageModelProvider.OPENAI: self.openai_api_key,
        }
        return keys[self.llm_provider]


def _require_complete_group(group: str, *values: object) -> None:
    present = [value is not None for value in values]
    if any(present) and not all(present):
        raise IncompleteSettingsError(f"Incomplete {group} settings: set all of them or none")
