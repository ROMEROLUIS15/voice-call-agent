"""Destinations of finished call traces."""

import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from voice_call_agent.observability.call_trace import CallTrace
from voice_call_agent.observability.error_reporting import report_error
from voice_call_agent.observability.error_taxonomy import ErrorCode


class CallTraceSink(Protocol):
    """Where a finished call publishes its trace."""

    async def write(self, trace: CallTrace) -> None: ...


class JsonlCallTraceSink:
    """One `CallTrace` per line in a local file. Safe with concurrent calls.

    Each instance writes its own file; error tracking (Sentry) aggregates across instances.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def write(self, trace: CallTrace) -> None:
        """Append the trace. The file I/O runs in a thread, off the event loop."""
        line = trace.model_dump_json() + "\n"
        async with self._lock:
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(line)


async def publish_trace(trace: CallTrace, sinks: Sequence[CallTraceSink]) -> None:
    """Write the trace to every sink; a failing sink never hides the others nor the call."""
    for sink in sinks:
        try:
            await sink.write(trace)
        except Exception as error:
            report_error(
                ErrorCode.TRACE_EXPORT_FAILED,
                error=error,
                call_id=trace.call_id,
                sink=type(sink).__name__,
            )


def read_call_traces(path: Path) -> list[CallTrace]:
    """Read the traces written by `JsonlCallTraceSink`."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [CallTrace.model_validate_json(line) for line in lines if line.strip()]
