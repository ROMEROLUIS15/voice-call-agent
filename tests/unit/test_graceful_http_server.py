import asyncio
import signal

import uvicorn
from fastapi import FastAPI

from voice_call_agent.call_supervision.call_supervisor import CallSupervisor
from voice_call_agent.graceful_http_server import GracefulHttpServer


def _server(supervisor: CallSupervisor, grace_seconds: float) -> GracefulHttpServer:
    return GracefulHttpServer(uvicorn.Config(FastAPI()), supervisor, grace_seconds)


async def test_first_signal_drains_calls_before_uvicorn_shuts_down() -> None:
    supervisor = CallSupervisor(max_concurrent_calls=1)
    slot = supervisor.try_reserve()
    assert slot is not None
    call_finished = asyncio.Event()

    async def call() -> None:
        await asyncio.sleep(0.05)
        call_finished.set()

    supervisor.launch(slot, call())
    server = _server(supervisor, grace_seconds=5)
    server._loop = asyncio.get_running_loop()

    server.handle_exit(signal.SIGTERM, None)
    assert not server.should_exit  # uvicorn's shutdown would cut the call's WebSocket.
    await asyncio.sleep(0)  # The loop runs the callback the signal handler scheduled.

    assert server._drain_task is not None
    await asyncio.wait_for(server._drain_task, timeout=1)
    assert supervisor.is_draining
    assert server.should_exit
    assert call_finished.is_set()  # uvicorn may shut down only after the call ended.


def test_second_signal_falls_back_to_uvicorn() -> None:
    server = _server(CallSupervisor(max_concurrent_calls=1), grace_seconds=5)
    server._drain_requested = True
    server.handle_exit(signal.SIGTERM, None)
    assert server.should_exit


def test_signal_before_startup_falls_back_to_uvicorn() -> None:
    server = _server(CallSupervisor(max_concurrent_calls=1), grace_seconds=5)
    server.handle_exit(signal.SIGINT, None)
    assert server.should_exit
