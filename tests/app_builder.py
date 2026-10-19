"""The real ASGI app wired with recording doubles instead of providers and external APIs."""

from dataclasses import dataclass, field

from starlette.types import ASGIApp

from tests.recording_doubles import (
    RecordingCallAcceptor,
    RecordingCallTerminator,
    RecordingConversationRunner,
)
from tests.settings_factory import make_service_settings
from voice_call_agent.asgi_app import ServiceComponents, build_asgi_app
from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.call_transports.replay_guard import InMemoryReplayGuard
from voice_call_agent.http_hardening.request_rate_limit import build_rate_limiter


@dataclass
class AppUnderTest:
    runner: RecordingConversationRunner = field(default_factory=RecordingConversationRunner)
    terminator: RecordingCallTerminator = field(default_factory=RecordingCallTerminator)
    acceptor: RecordingCallAcceptor = field(default_factory=RecordingCallAcceptor)
    supervisor: CallSupervisor = field(default_factory=lambda: CallSupervisor(5))
    replay_guard: InMemoryReplayGuard = field(default_factory=lambda: InMemoryReplayGuard(300))

    def build(self, **settings_overrides: object) -> ASGIApp:
        components = ServiceComponents(
            supervisor=self.supervisor,
            conversation_runner=self.runner,
            call_terminator=self.terminator,
            call_acceptor=self.acceptor,
            replay_guard=self.replay_guard,
            rate_limiter=build_rate_limiter("async+memory://"),
            shutdown_grace_seconds=1,
        )
        return build_asgi_app(make_service_settings(**settings_overrides), components)
