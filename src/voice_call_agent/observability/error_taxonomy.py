"""Typed error taxonomy: every failure has a code, a severity and a kind.

A *real failure* means this service or a provider failed and someone may need to act. An
*expected outcome* is a normal result of the domain or of a protection doing its job
(a slot already taken, a forged webhook refused); it is counted, not alerted on as a failure.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ErrorKind(StrEnum):
    REAL_FAILURE = "real_failure"
    EXPECTED_OUTCOME = "expected_outcome"


class ErrorSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCode(StrEnum):
    # Providers and the pipeline.
    STT_EXCEPTION = "STT_EXCEPTION"
    LLM_EXCEPTION = "LLM_EXCEPTION"
    TTS_EXCEPTION = "TTS_EXCEPTION"
    PIPELINE_EXCEPTION = "PIPELINE_EXCEPTION"
    CALL_TASK_FAILED = "CALL_TASK_FAILED"
    CALLS_CUT_AT_SHUTDOWN = "CALLS_CUT_AT_SHUTDOWN"
    # Call entries and their external APIs.
    CALL_ADMISSION_FAILED = "CALL_ADMISSION_FAILED"
    GRAPH_API_REJECT_FAILED = "GRAPH_API_REJECT_FAILED"
    TWILIO_HANGUP_FAILED = "TWILIO_HANGUP_FAILED"
    UNHANDLED_REQUEST_ERROR = "UNHANDLED_REQUEST_ERROR"
    TRACE_EXPORT_FAILED = "TRACE_EXPORT_FAILED"
    # Scheduling backend (phase 1 on).
    SCHEDULING_BACKEND_UNAVAILABLE = "SCHEDULING_BACKEND_UNAVAILABLE"
    SCHEDULING_BACKEND_REJECTED = "SCHEDULING_BACKEND_REJECTED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    # Domain outcomes, mirrored from `WriteRejectionReason`.
    SLOT_CONFLICT = "SLOT_CONFLICT"
    OUTSIDE_HOURS = "OUTSIDE_HOURS"
    INVALID_ARGS = "INVALID_ARGS"
    NOT_FOUND = "NOT_FOUND"
    IDENTITY_REQUIRED = "IDENTITY_REQUIRED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    # Capacity.
    CALL_REJECTED_NO_SLOT = "CALL_REJECTED_NO_SLOT"
    # Protections doing their job.
    WEBHOOK_SIGNATURE_INVALID = "WEBHOOK_SIGNATURE_INVALID"
    WEBHOOK_REPLAY_REJECTED = "WEBHOOK_REPLAY_REJECTED"
    WEBHOOK_EVENT_STALE = "WEBHOOK_EVENT_STALE"
    WEBHOOK_PAYLOAD_IGNORED = "WEBHOOK_PAYLOAD_IGNORED"
    STREAM_HANDSHAKE_REJECTED = "STREAM_HANDSHAKE_REJECTED"
    # An error code, not a secret (ruff S105 and bandit B105 match the word TOKEN).
    STREAM_TOKEN_INVALID = "STREAM_TOKEN_INVALID"  # noqa: S105  # nosec B105
    STREAM_REPLAY_REJECTED = "STREAM_REPLAY_REJECTED"
    RATE_LIMITED = "RATE_LIMITED"
    REQUEST_INVALID = "REQUEST_INVALID"


class ErrorSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: ErrorCode
    kind: ErrorKind
    severity: ErrorSeverity
    security_event: bool = False
    """Counted for the security-rejection alert (a spike may be an attack or a misconfiguration)."""
    description: str


def _failure(code: ErrorCode, severity: ErrorSeverity, description: str) -> ErrorSpec:
    return ErrorSpec(
        code=code, kind=ErrorKind.REAL_FAILURE, severity=severity, description=description
    )


def _outcome(
    code: ErrorCode, description: str, *, security_event: bool = False, warning: bool = False
) -> ErrorSpec:
    return ErrorSpec(
        code=code,
        kind=ErrorKind.EXPECTED_OUTCOME,
        severity=ErrorSeverity.WARNING if warning else ErrorSeverity.INFO,
        security_event=security_event,
        description=description,
    )


_E, _W, _C = ErrorSeverity.ERROR, ErrorSeverity.WARNING, ErrorSeverity.CRITICAL

ERROR_CATALOG: dict[ErrorCode, ErrorSpec] = {
    spec.code: spec
    for spec in (
        _failure(ErrorCode.STT_EXCEPTION, _E, "speech-to-text service failed"),
        _failure(ErrorCode.LLM_EXCEPTION, _E, "language model service failed"),
        _failure(ErrorCode.TTS_EXCEPTION, _E, "text-to-speech service failed"),
        _failure(ErrorCode.PIPELINE_EXCEPTION, _E, "pipeline processor failed"),
        _failure(ErrorCode.CALL_TASK_FAILED, _E, "call ended with an unhandled error"),
        _failure(ErrorCode.CALLS_CUT_AT_SHUTDOWN, _W, "shutdown grace exceeded; calls cut"),
        _failure(ErrorCode.CALL_ADMISSION_FAILED, _E, "could not admit the WhatsApp call"),
        _failure(ErrorCode.GRAPH_API_REJECT_FAILED, _W, "rejecting the WhatsApp call failed"),
        _failure(ErrorCode.TWILIO_HANGUP_FAILED, _W, "ending the call through Twilio failed"),
        _failure(ErrorCode.UNHANDLED_REQUEST_ERROR, _E, "unhandled error serving a request"),
        _failure(ErrorCode.TRACE_EXPORT_FAILED, _W, "a call trace could not be exported"),
        _failure(ErrorCode.SCHEDULING_BACKEND_UNAVAILABLE, _E, "scheduling backend unavailable"),
        _failure(ErrorCode.SCHEDULING_BACKEND_REJECTED, _C, "scheduling backend refused a request"),
        _failure(ErrorCode.IDEMPOTENCY_KEY_REUSED, _C, "idempotency key reused with another body"),
        _outcome(ErrorCode.SLOT_CONFLICT, "slot no longer available"),
        _outcome(ErrorCode.OUTSIDE_HOURS, "requested time outside opening hours"),
        _outcome(ErrorCode.INVALID_ARGS, "backend rejected the arguments"),
        _outcome(ErrorCode.NOT_FOUND, "appointment not found for this caller"),
        _outcome(ErrorCode.IDENTITY_REQUIRED, "second factor required on the phone line"),
        _outcome(ErrorCode.IDENTITY_MISMATCH, "second factor did not match"),
        _outcome(ErrorCode.CALL_REJECTED_NO_SLOT, "no call slot free; call rejected", warning=True),
        _outcome(
            ErrorCode.WEBHOOK_SIGNATURE_INVALID,
            "webhook with a missing or invalid signature",
            security_event=True,
            warning=True,
        ),
        _outcome(
            ErrorCode.WEBHOOK_REPLAY_REJECTED, "repeated webhook delivery", security_event=True
        ),
        _outcome(ErrorCode.WEBHOOK_EVENT_STALE, "stale webhook event", security_event=True),
        _outcome(ErrorCode.WEBHOOK_PAYLOAD_IGNORED, "webhook without call events; ignored"),
        _outcome(
            ErrorCode.STREAM_HANDSHAKE_REJECTED,
            "media stream handshake failed",
            security_event=True,
        ),
        _outcome(
            ErrorCode.STREAM_TOKEN_INVALID,
            "media stream with an invalid admission token",
            security_event=True,
            warning=True,
        ),
        _outcome(
            ErrorCode.STREAM_REPLAY_REJECTED,
            "second media stream for the same call",
            security_event=True,
            warning=True,
        ),
        _outcome(ErrorCode.RATE_LIMITED, "rate limit exceeded", security_event=True),
        _outcome(ErrorCode.REQUEST_INVALID, "malformed request"),
    )
}
