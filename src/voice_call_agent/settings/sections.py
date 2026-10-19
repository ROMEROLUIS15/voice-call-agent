"""Typed configuration sections. Each component receives only the section it needs."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True)


class ServerSettings(_Section):
    """HTTP server bind address."""

    host: str
    port: int


class SpeechSettings(_Section):
    """Speech-to-text and text-to-speech."""

    deepgram_api_key: SecretStr
    stt_model: str
    tts_voice: str


class LanguageModelProvider(StrEnum):
    """Supported language model providers."""

    GROQ = "groq"
    GOOGLE = "google"
    OPENAI = "openai"


class LanguageModelSettings(_Section):
    """Language model used for the conversation."""

    provider: LanguageModelProvider
    api_key: SecretStr
    model: str | None
    """`None` keeps Pipecat's default model for the provider."""
    request_timeout_seconds: float = Field(gt=0)


class TwilioMediaStreamsSettings(_Section):
    """Phone-line entry."""

    public_base_url: HttpUrl
    """Exact public URL Twilio calls (ngrok in development); Twilio signs webhooks with it."""
    account_sid: str
    auth_token: SecretStr
    handshake_timeout_seconds: float = Field(gt=0)
    """Maximum wait for the Media Stream `start` event after the WebSocket opens."""
    api_timeout_seconds: float = Field(gt=0)
    """Timeout of each Twilio REST request (ending a call)."""


class WhatsAppCallingSettings(_Section):
    """WhatsApp Cloud API Calling entry."""

    access_token: SecretStr
    phone_number_id: str
    app_secret: SecretStr
    """Meta app secret; signs every webhook (`X-Hub-Signature-256`)."""
    verify_token: SecretStr
    """Token Meta echoes when subscribing the webhook."""
    graph_api_timeout_seconds: float = Field(gt=0)
    """Timeout of each Graph API request (pre-accept, accept, reject, terminate)."""


class CallSupervisionSettings(_Section):
    """Per-instance concurrency limit and shutdown behaviour."""

    max_concurrent_calls: int = Field(ge=1)
    shutdown_grace_seconds: float = Field(ge=0)
    """How long a shutdown waits for in-progress calls before cutting them."""


class LatencyLogSettings(_Section):
    """Where per-call latency records are stored."""

    path: Path


class LogFormat(StrEnum):
    """Log output format."""

    JSON = "json"
    TEXT = "text"


class LogSettings(_Section):
    """Log level and format."""

    level: str
    output_format: LogFormat
