"""Per-call logger. Every field that could identify the caller is redacted here."""

from typing import TYPE_CHECKING

from loguru import logger

from voice_call_agent.observability.personal_data_redaction import redact_phone_number
from voice_call_agent.observability.trace_context import CallTraceContext

if TYPE_CHECKING:
    from loguru import Logger


def bind_call_logger(context: CallTraceContext) -> "Logger":
    """Logger whose records carry the call's id and channel label."""
    return logger.bind(call_id=context.call_id, channel=context.channel_label)


def log_call_started(
    call_logger: "Logger", caller_phone: str | None, identity_verified: bool
) -> None:
    """Log the start of a call without exposing the caller's number."""
    call_logger.bind(
        caller=redact_phone_number(caller_phone), identity_verified=identity_verified
    ).info("call started")
