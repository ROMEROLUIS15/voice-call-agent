"""Call traces and service versions for tests."""

from datetime import UTC, datetime

from voice_call_agent.observability.call_trace import (
    CallTrace,
    CostEstimate,
    ProviderUsage,
    RecordedError,
    ServiceVersions,
    TurnLatency,
)
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome

SERVICES = ServiceVersions(
    prompt_version="es-0123456789ab",
    locale="es",
    llm_provider="groq",
    llm_model="openai/gpt-oss-120b",
    stt_model="flux-general-multi",
    tts_voice="aura-2-selena-es",
)


def make_turn(
    total_ms: float, *, stt: float = 200, llm: float = 300, tts: float = 150
) -> TurnLatency:
    return TurnLatency(
        started_at=datetime(2026, 10, 19, 10, 0, tzinfo=UTC),
        stt_ms=stt,
        llm_ms=llm,
        tts_ms=tts,
        other_ms=0,
        total_ms=total_ms,
    )


def make_call_trace(
    channel: str = "twilio",
    totals: tuple[float, ...] = (),
    errors: tuple[RecordedError, ...] = (),
    call_id: str = "CA1",
) -> CallTrace:
    return CallTrace(
        call_id=call_id,
        channel_label=channel,
        business_id=None,
        identity_verified=channel == "whatsapp",
        outcome=CallOutcome.INFO_ONLY,
        started_at=datetime(2026, 10, 19, 10, 0, tzinfo=UTC),
        duration_s=60,
        services=SERVICES,
        greeting_ms=None,
        turns=[make_turn(total) for total in totals],
        caller_turns=len(totals),
        errors=list(errors),
        usage=ProviderUsage(),
        cost=CostEstimate(usd=0.0, complete=True, price_table_version="test"),
    )
