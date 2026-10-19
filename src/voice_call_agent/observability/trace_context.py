"""Labels a call is published under in traces, logs and metrics."""

from pydantic import BaseModel, ConfigDict


class CallTraceContext(BaseModel):
    """Identifies a call in traces.

    `channel_label` is an opaque label for grouping metrics by channel; no module outside
    `call_transports/` and `call_session/` may make decisions with it (INV-8).
    """

    model_config = ConfigDict(frozen=True)

    call_id: str
    channel_label: str
