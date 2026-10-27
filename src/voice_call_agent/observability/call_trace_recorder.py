"""Builds a call's `CallTrace` from the pipeline's observers and the errors reported during it."""

import time
from collections import Counter
from datetime import UTC, datetime

from pipecat.observers.base_observer import BaseObserver

from voice_call_agent.observability.call_trace import (
    CallTrace,
    RecordedError,
    ServiceVersions,
    WriteDecision,
)
from voice_call_agent.observability.cost_estimation import PriceTable, estimate_cost
from voice_call_agent.observability.error_taxonomy import ErrorCode, ErrorSpec
from voice_call_agent.observability.latency_tracking import CallLatencyTracker
from voice_call_agent.observability.pipeline_observers import (
    ProviderErrorObserver,
    SilentReplyObserver,
    UsageObserver,
)
from voice_call_agent.observability.trace_context import CallTraceContext
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome


class CallTraceRecorder:
    """Records one call. Errors arrive through `record_error` (see `errors_recorded_by`), and
    the upstream provider of each response through `record_llm_upstream`."""

    def __init__(
        self, context: CallTraceContext, services: ServiceVersions, prices: PriceTable
    ) -> None:
        self._context = context
        self._services = services
        self._prices = prices
        self._started_at = datetime.now(UTC)
        self._started = time.monotonic()
        self._latency = CallLatencyTracker(context)
        self._usage = UsageObserver()
        self._errors: Counter[ErrorCode] = Counter()
        self._upstreams: Counter[str] = Counter()
        self._writes: list[WriteDecision] = []
        self._specs: dict[ErrorCode, ErrorSpec] = {}
        self.observers: list[BaseObserver] = [
            self._latency.observer,
            self._usage,
            ProviderErrorObserver(),
            SilentReplyObserver(),
        ]

    @property
    def call_id(self) -> str:
        return self._context.call_id

    @property
    def caller_turns(self) -> int:
        """Final caller transcripts so far: the write guards read it during the call."""
        return self._usage.caller_turns

    def record_write(self, decision: WriteDecision) -> None:
        self._writes.append(decision)

    def record_llm_upstream(self, upstream: str) -> None:
        self._upstreams[upstream] += 1

    def record_error(self, spec: ErrorSpec) -> None:
        self._errors[spec.code] += 1
        self._specs[spec.code] = spec

    def finish(self, outcome: CallOutcome | None = None) -> CallTrace:
        """Close the trace. Unknown outcome: booked if a booking was written, info only if the
        caller spoke, else abandoned."""
        duration_s = time.monotonic() - self._started
        if outcome is None:
            outcome = self._outcome()
        return CallTrace(
            call_id=self._context.call_id,
            channel_label=self._context.channel_label,
            business_id=self._context.business_id,
            identity_verified=self._context.identity_verified,
            outcome=outcome,
            started_at=self._started_at,
            duration_s=duration_s,
            services=self._services,
            greeting_ms=self._latency.greeting_ms,
            turns=list(self._latency.turns),
            caller_turns=self._usage.caller_turns,
            errors=[
                RecordedError(code=code, kind=self._specs[code].kind, count=count)
                for code, count in sorted(self._errors.items())
            ],
            writes=list(self._writes),
            usage=self._usage.usage.model_copy(),
            llm_upstreams=dict(sorted(self._upstreams.items())),
            cost=estimate_cost(
                usage=self._usage.usage,
                llm_upstreams=self._upstreams,
                services=self._services,
                duration_s=duration_s,
                channel_label=self._context.channel_label,
                prices=self._prices,
            ),
        )

    def _outcome(self) -> CallOutcome:
        if any(write.outcome == "booked" for write in self._writes):
            return CallOutcome.BOOKED
        return CallOutcome.INFO_ONLY if self._usage.caller_turns else CallOutcome.ABANDONED
