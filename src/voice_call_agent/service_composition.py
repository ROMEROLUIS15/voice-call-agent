"""Composition root: the only place that picks concrete providers and adapters."""

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.transcriptions.language import Language

from voice_call_agent.adapters.cronix_scheduling_api.cronix_backend import CronixSchedulingBackend
from voice_call_agent.adapters.cronix_scheduling_api.signed_api import SignedApi
from voice_call_agent.adapters.deepgram_speech.service_factories import (
    aura_tts_factory,
    flux_stt_factory,
)
from voice_call_agent.adapters.language_model_providers.provider_selection import (
    select_language_model,
)
from voice_call_agent.asgi_app import ServiceComponents
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.browser_webrtc.practice_routes import PracticeLine
from voice_call_agent.call_transports.replay_guard import InMemoryReplayGuard
from voice_call_agent.call_transports.twilio_media_streams.call_termination import (
    TwilioCallTerminator,
)
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import (
    WhatsAppCallAcceptor,
)
from voice_call_agent.conversation_content.content_loader import (
    ConversationContent,
    load_conversation_content,
)
from voice_call_agent.http_hardening.request_rate_limit import build_rate_limiter
from voice_call_agent.observability.call_trace import ServiceVersions
from voice_call_agent.observability.call_trace_store import CallTraceSink, JsonlCallTraceSink
from voice_call_agent.observability.conversation_transcript import TextFileTranscriptSink
from voice_call_agent.observability.cost_estimation import load_price_table
from voice_call_agent.observability.sentry_trace_export import SentryCallTraceSink
from voice_call_agent.practice_schedule.in_memory_schedule import InMemorySchedule
from voice_call_agent.practice_schedule.practice_catalog import (
    PracticeCatalog,
    load_practice_catalog,
)
from voice_call_agent.settings.sections import SchedulingBackendKind
from voice_call_agent.settings.service_settings import ServiceSettings
from voice_call_agent.speech_pipeline.conversation_runner import PipecatConversationRunner
from voice_call_agent.speech_pipeline.pipeline_assembly import SpeechServiceFactories


def compose_service(settings: ServiceSettings) -> ServiceComponents:
    """Build every dependency of the service from its settings."""
    content = load_conversation_content()
    speech = settings.speech()
    language_model = select_language_model(settings.language_model())
    factories = SpeechServiceFactories(
        create_stt=flux_stt_factory(speech, Language(content.locale)),
        create_language_model=language_model.create,
        create_tts=aura_tts_factory(speech),
        create_vad=SileroVADAnalyzer,
    )
    trace_sinks: list[CallTraceSink] = [JsonlCallTraceSink(settings.call_trace_log().path)]
    trace_sinks.append(SentryCallTraceSink())  # A no-op unless error tracking is configured.
    practice_catalog = _practice_catalog(settings)
    schedule = _scheduling_backend(settings, content, practice_catalog)
    runner = PipecatConversationRunner(
        factories=factories,
        content=content,
        services=ServiceVersions(
            prompt_version=content.version,
            locale=content.locale,
            llm_provider=language_model.provider,
            llm_model=language_model.model,
            stt_model=speech.stt_model,
            tts_voice=speech.tts_voice,
        ),
        prices=load_price_table(),
        trace_sinks=trace_sinks,
        scheduling_backend=schedule,
        transcript_sink=_transcript_sink(settings),
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
        business_resolver=schedule,
        practice_lines=_practice_lines(practice_catalog),
    )


def _scheduling_backend(
    settings: ServiceSettings, content: ConversationContent, catalog: PracticeCatalog | None
) -> CronixSchedulingBackend | InMemorySchedule | None:
    """Cronix's API, the practice schedule, or no backend, as `SCHEDULING_BACKEND` says."""
    api = settings.scheduling_api()
    if api is not None:
        return CronixSchedulingBackend(
            SignedApi(api), lambda name: content.business_greeting.format(business_name=name)
        )
    return InMemorySchedule(catalog) if catalog is not None else None


def _practice_catalog(settings: ServiceSettings) -> PracticeCatalog | None:
    """The practice schedule's businesses when chosen; none otherwise."""
    if settings.scheduling_backend is SchedulingBackendKind.PRACTICE:
        return load_practice_catalog()
    return None


def _transcript_sink(settings: ServiceSettings) -> TextFileTranscriptSink | None:
    """Development only: each call leaves what was said in a local file (ADR 0017)."""
    transcripts = settings.conversation_transcripts()
    return TextFileTranscriptSink(transcripts.directory) if transcripts is not None else None


def _practice_lines(catalog: PracticeCatalog | None) -> tuple[PracticeLine, ...]:
    if catalog is None:
        return ()
    return tuple(
        PracticeLine(number=number, business_name=business.name)
        for business in catalog.businesses
        for number in business.dialed_numbers
    )
