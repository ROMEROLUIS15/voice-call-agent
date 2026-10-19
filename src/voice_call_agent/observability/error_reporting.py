"""The single way to report an error: structured log, error tracking, and the call's trace.

`report_error` never raises. Attributes must be identifiers or categories (codes, provider
names, ids): never personal data, which error tracking would scrub anyway.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol

import sentry_sdk
from loguru import logger

from voice_call_agent.observability.error_taxonomy import (
    ERROR_CATALOG,
    ErrorCode,
    ErrorKind,
    ErrorSeverity,
    ErrorSpec,
)

type ErrorAttribute = str | int | float | bool

_LOG_LEVEL = {
    ErrorSeverity.INFO: "INFO",
    ErrorSeverity.WARNING: "WARNING",
    ErrorSeverity.ERROR: "ERROR",
    ErrorSeverity.CRITICAL: "CRITICAL",
}


class CallErrorRecorder(Protocol):
    """The trace of the call in progress, which keeps every error reported during it."""

    @property
    def call_id(self) -> str: ...

    def record_error(self, spec: ErrorSpec) -> None: ...


_PER_CALL_ATTRIBUTES = frozenset({"call_id"})
"""Tag issues and logs, never metrics: one value per call would explode their cardinality."""


# Task-local, not global: each call's tasks inherit the context of the call that created them.
_active_call: ContextVar[CallErrorRecorder | None] = ContextVar("active_call", default=None)


@contextmanager
def errors_recorded_by(recorder: CallErrorRecorder) -> Iterator[None]:
    """Attribute every error reported inside this block (and its tasks) to the call."""
    token = _active_call.set(recorder)
    try:
        yield
    finally:
        _active_call.reset(token)


def report_error(
    code: ErrorCode, *, error: BaseException | None = None, **attributes: ErrorAttribute
) -> None:
    """Log the error with its code and send it to error tracking and to the call's trace.

    Inside a call, the error carries the call's id, which leads from an issue to its trace.
    """
    spec = ERROR_CATALOG[code]
    recorder = _active_call.get()
    if recorder is not None:
        recorder.record_error(spec)
        attributes.setdefault("call_id", recorder.call_id)
    log = logger.bind(
        error_code=code.value,
        error_kind=spec.kind.value,
        security_event=spec.security_event,
        **attributes,
    )
    log.opt(exception=error).log(_LOG_LEVEL[spec.severity], spec.description)
    _send_to_error_tracking(spec, error, attributes)


def _send_to_error_tracking(
    spec: ErrorSpec, error: BaseException | None, attributes: dict[str, ErrorAttribute]
) -> None:
    """Every error is counted; only real failures become issues. A no-op without a DSN."""
    sentry_sdk.metrics.count(
        "voice.error",
        1,
        attributes={
            "error_code": spec.code.value,
            "error_kind": spec.kind.value,
            "security_event": spec.security_event,
            **{k: v for k, v in attributes.items() if k not in _PER_CALL_ATTRIBUTES},
        },
    )
    if spec.kind is not ErrorKind.REAL_FAILURE:
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("error_code", spec.code.value)
        for name, value in attributes.items():
            scope.set_tag(name, str(value))
        scope.fingerprint = [spec.code.value]
        # Captured on the current scope, which inside `new_scope` is this forked one.
        if error is not None:
            sentry_sdk.capture_exception(error)
        else:
            sentry_sdk.capture_message(spec.description, level=spec.severity.value)
