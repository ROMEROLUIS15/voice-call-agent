import asyncio
import json

from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.whatsapp.api import WhatsAppConnectCallValue, WhatsAppWebhookRequest

from tests.recording_doubles import RecordingCallAcceptor, RecordingConversationRunner
from tests.whatsapp_payloads import JsonObject, connect_payload, terminate_payload
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.pipecat_webrtc_transport import (
    WEBRTC_AUDIO_FORMAT,
)
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import OnCallAccepted
from voice_call_agent.call_transports.whatsapp_calling.call_admission import admit_call_events
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import (
    CallEvents,
    extract_call_events,
)


class AcceptingCallAcceptor(RecordingCallAcceptor):
    """Accepts every `connect` event, as the Graph API would after pre-accept and accept."""

    async def process_call_events(
        self, webhook: WhatsAppWebhookRequest, on_accepted: OnCallAccepted | None
    ) -> None:
        await super().process_call_events(webhook, on_accepted)
        value = webhook.entry[0].changes[0].value
        if on_accepted is not None and isinstance(value, WhatsAppConnectCallValue):
            await on_accepted(SmallWebRTCConnection(), value.calls[0])


def _events(payload: JsonObject) -> CallEvents:
    events = extract_call_events(json.dumps(payload).encode())
    assert events is not None
    return events


async def test_accepted_call_runs_with_a_verified_identity() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    runner = RecordingConversationRunner(hold=True)
    await admit_call_events(
        _events(connect_payload()),
        acceptor=AcceptingCallAcceptor(),
        supervisor=supervisor,
        conversation_runner=runner,
    )
    await asyncio.sleep(0)

    [(session, audio_format)] = runner.calls
    assert session.identity_verified
    assert audio_format == WEBRTC_AUDIO_FORMAT
    assert supervisor.active_calls == 1  # The slot belongs to the running call.

    runner.release.set()
    await supervisor.drain(grace_seconds=1)
    assert supervisor.active_calls == 0


async def test_call_is_rejected_when_full() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    held = supervisor.try_reserve()
    acceptor = RecordingCallAcceptor()
    await admit_call_events(
        _events(connect_payload("wacid.full")),
        acceptor=acceptor,
        supervisor=supervisor,
        conversation_runner=RecordingConversationRunner(),
    )
    assert acceptor.rejected == ["wacid.full"]
    assert acceptor.processed == []
    assert held is not None


async def test_slot_is_released_when_the_call_never_starts() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    await admit_call_events(
        _events(connect_payload()),
        acceptor=RecordingCallAcceptor(),  # Never invokes `on_accepted`.
        supervisor=supervisor,
        conversation_runner=RecordingConversationRunner(),
    )
    assert supervisor.active_calls == 0


async def test_terminate_event_takes_no_call_slot() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    supervisor.try_reserve()  # Full: a terminate must still be processed.
    acceptor = RecordingCallAcceptor()
    await admit_call_events(
        _events(terminate_payload()),
        acceptor=acceptor,
        supervisor=supervisor,
        conversation_runner=RecordingConversationRunner(),
    )
    assert len(acceptor.processed) == 1
    assert acceptor.rejected == []
