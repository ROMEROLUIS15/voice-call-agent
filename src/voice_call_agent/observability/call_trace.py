"""`CallTrace`: what one call did, how fast, with what, what failed and what it cost.

It carries no transcript and no raw phone number: identifiers, versions, latencies, counts.
"""

from datetime import date, datetime, time
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from voice_call_agent.observability.error_taxonomy import ErrorCode, ErrorKind
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome


class ServiceVersions(BaseModel):
    """Exactly what produced the agent's behaviour during a call."""

    model_config = ConfigDict(frozen=True)

    prompt_version: str
    """Version of the caller-facing content (system prompt and phrases)."""
    locale: str
    llm_provider: str
    llm_model: str
    stt_model: str
    tts_voice: str


class WriteAction(StrEnum):
    PROPOSE_BOOKING = "propose_booking"
    CONFIRM_BOOKING = "confirm_booking"


class WriteDecision(BaseModel):
    """What the write guards decided about a proposal or a confirmation (ADR 0011).

    No client name and no caller words: free text cannot be redacted reliably. The caller turn
    count shows whether the caller spoke between a proposal and its confirmation (INV-2).
    """

    model_config = ConfigDict(frozen=True)

    action: WriteAction
    outcome: str
    """`proposed` or `booked`, or the reason it was refused or rejected."""
    proposal_id: UUID | None
    caller_turn: int
    """Final caller transcripts so far in the call."""
    service_id: str | None = None
    day: date | None = None
    start: time | None = None


class TurnLatency(BaseModel):
    """One measured turn, in milliseconds. `other_ms` is pipeline time no service owns."""

    started_at: datetime | None = None
    stt_ms: float
    llm_ms: float
    tts_ms: float
    other_ms: float
    total_ms: float


class ProviderUsage(BaseModel):
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    stt_audio_seconds: float = 0.0
    tts_characters: int = 0


class CostEstimate(BaseModel):
    usd: float
    complete: bool
    """False when a price was unknown: the estimate then covers only the priced parts."""
    price_table_version: str


class RecordedError(BaseModel):
    code: ErrorCode
    kind: ErrorKind
    count: int


class CallTrace(BaseModel):
    """The trace of one call, written when it ends."""

    call_id: str
    channel_label: str
    business_id: str | None
    identity_verified: bool
    outcome: CallOutcome
    started_at: datetime
    duration_s: float
    services: ServiceVersions
    greeting_ms: float | None
    turns: list[TurnLatency]
    caller_turns: int
    errors: list[RecordedError]
    writes: list[WriteDecision] = Field(default_factory=list)
    usage: ProviderUsage
    llm_upstreams: dict[str, int] = Field(default_factory=dict)
    """Responses served by each upstream provider, when the provider routes (OpenRouter)."""
    cost: CostEstimate

    @property
    def real_failure(self) -> bool:
        """Whether this service or a provider failed during the call."""
        return any(error.kind is ErrorKind.REAL_FAILURE for error in self.errors)
