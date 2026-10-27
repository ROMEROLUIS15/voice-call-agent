"""Which upstream provider served each language model response, attributed to the call.

A routing provider (OpenRouter) answers through one of several upstream providers, whose latency
and price differ; the call trace counts the responses each one served.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol


class UpstreamRecorder(Protocol):
    """The trace of the call in progress."""

    def record_llm_upstream(self, upstream: str) -> None: ...


# Task-local, not global: each call's tasks inherit the context of the call that created them.
_active_call: ContextVar[UpstreamRecorder | None] = ContextVar(
    "active_call_upstreams", default=None
)


@contextmanager
def upstreams_recorded_by(recorder: UpstreamRecorder) -> Iterator[None]:
    """Attribute every upstream reported inside this block (and its tasks) to the call."""
    token = _active_call.set(recorder)
    try:
        yield
    finally:
        _active_call.reset(token)


def report_llm_upstream(upstream: str) -> None:
    """Count one response served by `upstream` (as the provider names it) in the call's trace."""
    recorder = _active_call.get()
    if recorder is not None:
        recorder.record_llm_upstream(upstream)
