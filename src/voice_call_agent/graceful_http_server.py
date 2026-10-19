"""HTTP server that drains calls before it shuts down."""

import asyncio
import socket
from types import FrameType

import uvicorn
from starlette.types import ASGIApp

from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.settings.sections import HttpHardeningSettings, ServerSettings


class GracefulHttpServer(uvicorn.Server):
    """uvicorn server whose first shutdown signal only starts draining calls.

    On shutdown uvicorn closes every open WebSocket at once (code 1012), which would cut every
    phone-line call in progress. So the first SIGINT/SIGTERM stops accepting calls and waits for
    the active ones (up to the grace period); uvicorn's own shutdown starts afterwards. A second
    signal falls back to uvicorn's behaviour.
    """

    def __init__(
        self, config: uvicorn.Config, supervisor: CallSupervisor, grace_seconds: float
    ) -> None:
        super().__init__(config)
        self._supervisor = supervisor
        self._grace_seconds = grace_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._drain_requested = False
        self._drain_task: asyncio.Task[None] | None = None

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        self._loop = asyncio.get_running_loop()
        await super().startup(sockets)

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        """Signal handler installed by uvicorn."""
        if self._loop is None or self._drain_requested:
            super().handle_exit(sig, frame)
            return
        self._drain_requested = True
        # Signal handlers run between bytecodes; hand the work to the event loop.
        self._loop.call_soon_threadsafe(self._start_drain)

    def _start_drain(self) -> None:
        self._drain_task = asyncio.create_task(self._drain_then_exit())

    async def _drain_then_exit(self) -> None:
        try:
            await self._supervisor.drain(self._grace_seconds)
        finally:
            self.should_exit = True


def server_config(
    app: ASGIApp, server: ServerSettings, http: HttpHardeningSettings
) -> uvicorn.Config:
    """uvicorn settings of the service, hardened (constitution §15)."""
    return uvicorn.Config(
        app,
        host=server.host,
        port=server.port,
        log_config=None,  # uvicorn's records go through the single structured sink.
        server_header=False,  # Never announce the stack.
        proxy_headers=True,
        forwarded_allow_ips=http.trusted_proxy_addresses,  # X-Forwarded-* from these only.
        ws_max_size=http.max_websocket_message_bytes,
    )
