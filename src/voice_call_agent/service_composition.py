"""Composition root: the only place that picks concrete providers and adapters."""

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.transcriptions.language import Language

from voice_call_agent.adapters.deepgram_speech.service_factories import (
    aura_tts_factory,
    flux_stt_factory,
)
from voice_call_agent.adapters.language_model_providers.provider_selection import (
    language_model_factory,
)
from voice_call_agent.asgi_app import ServiceComponents
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.replay_guard import InMemoryReplayGuard
from voice_call_agent.call_transports.twilio_media_streams.call_termination import (
    TwilioCallTerminator,
)
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import (
    WhatsAppCallAcceptor,
)
from voice_call_agent.conversation_content.content_loader import load_conversation_content
from voice_call_agent.http_hardening.request_rate_limit import build_rate_limiter
from voice_call_agent.observability.latency_record_store import JsonlLatencyRecordSink
from voice_call_agent.settings.service_settings import ServiceSettings
from voice_call_agent.speech_pipeline.conversation_runner import PipecatConversationRunner
from voice_call_agent.speech_pipeline.pipeline_assembly import SpeechServiceFactories


def compose_service(settings: ServiceSettings) -> ServiceComponents:
    """Build every dependency of the service from its settings."""
    content = load_conversation_content()
    speech = settings.speech()
    factories = SpeechServiceFactories(
        create_stt=flux_stt_factory(speech, Language(content.locale)),
        create_language_model=language_model_factory(settings.language_model()),
        create_tts=aura_tts_factory(speech),
        create_vad=SileroVADAnalyzer,
    )
    runner = PipecatConversationRunner(
        factories=factories,
        content=content,
        latency_sink=JsonlLatencyRecordSink(settings.latency_log().path),
    )
    supervision = settings.call_supervision()
    protection = settings.webhook_protection()
    twilio = settings.twilio_media_streams()
    whatsapp = settings.whatsapp_calling()
    return ServiceComponents(
        supervisor=CallSupervisor(supervision.max_concurrent_calls),
        conversation_runner=runner,
        call_terminator=(
            TwilioCallTerminator(twilio.account_sid, twilio.auth_token, twilio.api_timeout_seconds)
            if twilio is not None
            else None
        ),
        call_acceptor=WhatsAppCallAcceptor(whatsapp) if whatsapp is not None else None,
        replay_guard=InMemoryReplayGuard(protection.replay_window_seconds),
        rate_limiter=build_rate_limiter(protection.rate_limit_storage_uri),
        shutdown_grace_seconds=supervision.shutdown_grace_seconds,
    )
