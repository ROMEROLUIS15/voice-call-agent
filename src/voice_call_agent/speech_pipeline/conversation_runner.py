"""One call from greeting to hang-up, with its trace.

This module does not know which channel the call came from (INV-8): it receives a Pipecat
transport already built by `call_transports/`, the `CallSession` and that transport's audio format.
"""

from collections.abc import Sequence
from typing import Protocol

from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.transports.base_transport import BaseTransport
from pipecat.workers.runner import WorkerRunner

from voice_call_agent.call_session.session import CallSession
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.call_logging import bind_call_logger, log_call_started
from voice_call_agent.observability.call_trace import ServiceVersions
from voice_call_agent.observability.call_trace_recorder import CallTraceRecorder
from voice_call_agent.observability.call_trace_store import CallTraceSink, publish_trace
from voice_call_agent.observability.cost_estimation import PriceTable
from voice_call_agent.observability.error_reporting import errors_recorded_by
from voice_call_agent.speech_pipeline.audio_format import AudioFormat
from voice_call_agent.speech_pipeline.pipeline_assembly import (
    SpeechServiceFactories,
    assemble_speech_pipeline,
)


class ConversationRunner(Protocol):
    """What a call transport invokes to hold a conversation."""

    async def run(
        self, transport: BaseTransport, session: CallSession, audio_format: AudioFormat
    ) -> None: ...


class PipecatConversationRunner:
    """Holds the conversation over a Pipecat pipeline and publishes the call's trace."""

    def __init__(
        self,
        *,
        factories: SpeechServiceFactories,
        content: ConversationContent,
        services: ServiceVersions,
        prices: PriceTable,
        trace_sinks: Sequence[CallTraceSink],
    ) -> None:
        self._factories = factories
        self._content = content
        self._services = services
        self._prices = prices
        self._trace_sinks = trace_sinks

    async def run(
        self, transport: BaseTransport, session: CallSession, audio_format: AudioFormat
    ) -> None:
        """Run until the caller hangs up (or the call is cancelled), then publish its trace."""
        context = session.trace_context()
        call_logger = bind_call_logger(context)
        log_call_started(call_logger, session.caller_phone, session.identity_verified)
        recorder = CallTraceRecorder(context, self._services, self._prices)
        # Errors reported anywhere in this call's tasks land in its trace.
        with errors_recorded_by(recorder):
            try:
                await self._converse(transport, audio_format, recorder)
            finally:
                trace = recorder.finish()
                await publish_trace(trace, self._trace_sinks)
                call_logger.bind(
                    duration_s=round(trace.duration_s, 1),
                    turns=len(trace.turns),
                    outcome=trace.outcome.value,
                    real_failure=trace.real_failure,
                    cost_usd=trace.cost.usd,
                ).info("call ended")

    async def _converse(
        self, transport: BaseTransport, audio_format: AudioFormat, recorder: CallTraceRecorder
    ) -> None:
        pipeline = await assemble_speech_pipeline(
            transport, self._factories, self._content.system_prompt
        )
        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=audio_format.input_sample_rate_hz,
                audio_out_sample_rate=audio_format.output_sample_rate_hz,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=recorder.observers,
        )
        # Signals belong to the HTTP server, which drains calls before stopping.
        runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
        self._greet_on_connect_and_stop_on_hang_up(transport, worker, runner)
        await runner.add_workers(worker)
        await runner.run()

    def _greet_on_connect_and_stop_on_hang_up(
        self, transport: BaseTransport, worker: PipelineWorker, runner: WorkerRunner
    ) -> None:
        async def greet(_transport: BaseTransport, _client: object) -> None:
            await worker.queue_frames([TTSSpeakFrame(self._content.greeting)])

        async def stop(_transport: BaseTransport, _client: object) -> None:
            await runner.cancel()

        transport.add_event_handler("on_client_connected", greet)
        transport.add_event_handler("on_client_disconnected", stop)
