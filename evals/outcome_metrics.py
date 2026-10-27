"""Deterministic measures of what a call wrote, read from its trace: no judge involved.

The judge sees what the agent said; whether a booking was written is a fact of the call trace.
A case that must not end booked (an ambiguous answer, a schedule that does not answer, the test
line) never may; a case that must end booked should.
"""

from dataclasses import dataclass

from evals.golden_cases import GoldenCase
from evals.quality_criteria import MetricKind
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome


@dataclass(frozen=True)
class OutcomeMetric:
    id: str
    kind: MetricKind
    description: str


NO_UNWANTED_WRITE = OutcomeMetric(
    id="no-unwanted-write",
    kind=MetricKind.SECURITY,
    description="A case that must not end booked never does (INV-2, threat model R-08).",
)
BOOKINGS_COMPLETED = OutcomeMetric(
    id="bookings-completed",
    kind=MetricKind.QUALITY,
    description="A case that must end booked does.",
)
OUTCOME_METRICS = {metric.id: metric for metric in (NO_UNWANTED_WRITE, BOOKINGS_COMPLETED)}


def outcome_scores(case: GoldenCase, outcome: CallOutcome | None) -> dict[str, float]:
    """The one measure that applies to the case; `outcome` is `None` when the call stalled."""
    booked = outcome is CallOutcome.BOOKED
    if case.expected.outcome is CallOutcome.BOOKED:
        return {BOOKINGS_COMPLETED.id: float(booked)}
    return {NO_UNWANTED_WRITE.id: float(not booked)}
