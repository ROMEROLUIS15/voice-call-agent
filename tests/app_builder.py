"""The real ASGI app wired with recording doubles instead of providers and external APIs."""

from dataclasses import dataclass, field

from fastapi import FastAPI

from tests.recording_doubles import (
    RecordingCallAcceptor,
    RecordingCallTerminator,
    RecordingConversationRunner,
)
from tests.settings_factory import make_service_settings
from voice_call_agent.asgi_app import ServiceComponents, build_asgi_app
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor


@dataclass
class AppUnderTest:
    runner: RecordingConversationRunner = field(default_factory=RecordingConversationRunner)
    terminator: RecordingCallTerminator = field(default_factory=RecordingCallTerminator)
    acceptor: RecordingCallAcceptor = field(default_factory=RecordingCallAcceptor)
    supervisor: CallSupervisor = field(default_factory=lambda: CallSupervisor(5))

    def build(self, **settings_overrides: object) -> FastAPI:
        components = ServiceComponents(
            supervisor=self.supervisor,
            conversation_runner=self.runner,
            call_terminator=self.terminator,
            call_acceptor=self.acceptor,
            shutdown_grace_seconds=1,
        )
        return build_asgi_app(make_service_settings(**settings_overrides), components)
