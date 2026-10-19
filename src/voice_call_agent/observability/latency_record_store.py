"""Storage of per-call latency records."""

import asyncio
from pathlib import Path
from typing import Protocol

from voice_call_agent.observability.turn_latency import CallLatencyRecord


class LatencyRecordSink(Protocol):
    """Where finished calls publish their latency record."""

    async def write(self, record: CallLatencyRecord) -> None: ...


class JsonlLatencyRecordSink:
    """One `CallLatencyRecord` per line in a local file. Safe with concurrent calls.

    Each instance writes its own file; a production deployment replaces it with a trace exporter.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = asyncio.Lock()

    async def write(self, record: CallLatencyRecord) -> None:
        """Append the record. The file I/O runs in a thread, off the event loop."""
        line = record.model_dump_json() + "\n"
        async with self._lock:
            await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as file:
            file.write(line)


def read_latency_records(path: Path) -> list[CallLatencyRecord]:
    """Read the records written by `JsonlLatencyRecordSink`."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return [CallLatencyRecord.model_validate_json(line) for line in lines if line.strip()]
