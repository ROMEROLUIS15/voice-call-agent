"""Test doubles that record what the code under test asked them to do."""

import asyncio

from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.whatsapp.api import WhatsAppWebhookRequest

from voice_call_agent.call_session.session import CallSession
from voice_call_agent.call_transports.whatsapp_calling.call_acceptance import OnCallAccepted
from voice_call_agent.speech_pipeline.audio_format import AudioFormat


class RecordingConversationRunner:
    """Records each conversation; `hold` keeps it running until released."""

    def __init__(self, hold: bool = False) -> None:
        self.calls: list[tuple[CallSession, AudioFormat]] = []
        self.release = asyncio.Event()
        if not hold:
            self.release.set()

    async def run(
        self, transport: BaseTransport, session: CallSession, audio_format: AudioFormat
    ) -> None:
        self.calls.append((session, audio_format))
        await self.release.wait()


class RecordingCallTerminator:
    def __init__(self) -> None:
        self.ended: list[str] = []

    async def end_call(self, call_sid: str) -> None:
        self.ended.append(call_sid)


class RecordingCallAcceptor:
    """Records webhooks and rejections; never talks to the Graph API."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.processed: list[WhatsAppWebhookRequest] = []
        self.rejected: list[str] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def process_call_events(
        self, webhook: WhatsAppWebhookRequest, on_accepted: OnCallAccepted | None
    ) -> None:
        self.processed.append(webhook)

    async def reject(self, call_id: str) -> None:
        self.rejected.append(call_id)
