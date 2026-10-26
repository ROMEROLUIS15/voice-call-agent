"""Admission of incoming WhatsApp calls against this instance's call slots."""

from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.whatsapp.api import WhatsAppConnectCall

from voice_call_agent.call_session.session_builders import build_whatsapp_session
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.pipecat_webrtc_transport import (
    WEBRTC_AUDIO_FORMAT,
    build_webrtc_transport,
)
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import CallAcceptor
from voice_call_agent.call_transports.whatsapp_calling.calls_webhook_filter import CallEvents
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode
from voice_call_agent.speech_pipeline.conversation_runner import ConversationRunner


async def admit_call_events(
    events: CallEvents,
    *,
    acceptor: CallAcceptor,
    supervisor: CallSupervisor,
    conversation_runner: ConversationRunner,
) -> None:
    """Accept an incoming call if a call slot is free, reject it otherwise.

    The call slot is taken before accepting and handed to the call's supervised task, which
    releases it when the call ends; if the call never starts, it is released here.
    """
    if not events.connect_calls:
        await acceptor.process_call_events(events.webhook, None)  # Only `terminate` events.
        return
    slot = supervisor.try_reserve()
    if slot is None:
        for call in events.connect_calls:
            report_error(ErrorCode.CALL_REJECTED_NO_SLOT, call_id=call.id, entry="whatsapp")
            await acceptor.reject(call.id)
        return

    launched = False

    async def start_conversation(
        connection: SmallWebRTCConnection, call: WhatsAppConnectCall
    ) -> None:
        nonlocal launched
        session = build_whatsapp_session(call.id, call.from_, call.to)
        transport = build_webrtc_transport(connection)
        supervisor.launch(slot, conversation_runner.run(transport, session, WEBRTC_AUDIO_FORMAT))
        launched = True

    try:
        await acceptor.process_call_events(events.webhook, start_conversation)
    finally:
        if not launched:
            slot.release()
