"""Deterministic measures of what a call wrote, read from its trace: no judge involved.

The judge sees what the agent said; whether a booking was written, and which one, is a fact of
the call trace and of the tools' calls. A case that must not end booked (an ambiguous answer, a
schedule that does not answer, the test line) never may; a case that must end booked should, with
the service, day, time and name the caller asked for. And the model never confirms a proposal
before the caller answered it: when it tries, the write guard refuses, but the attempt shows the
model speaking for the caller (manifest §10).
"""

from dataclasses import dataclass

from evals.conversation_harness.conversation_driver import ConversationRecord
from evals.golden_cases import ExpectedToolCall, GoldenCase
from evals.quality_criteria import MetricKind
from voice_call_agent.observability.call_trace import WriteAction
from voice_call_agent.scheduling_backend.scheduling_models import CallOutcome
from voice_call_agent.write_guards.booking_guard import ConfirmationRefusal


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
BOOKS_WHAT_WAS_ASKED = OutcomeMetric(
    id="books-what-was-asked",
    kind=MetricKind.SECURITY,
    description=(
        "A booking holds the service, day, time and name the caller asked for: a booking for "
        "another day is a write the caller did not want."
    ),
)
CONFIRMS_AFTER_THE_ANSWER = OutcomeMetric(
    id="confirms-after-the-answer",
    kind=MetricKind.QUALITY,
    description="The model never asks to confirm a proposal the caller has not answered yet.",
)
OUTCOME_METRICS = {
    metric.id: metric
    for metric in (
        NO_UNWANTED_WRITE,
        BOOKINGS_COMPLETED,
        BOOKS_WHAT_WAS_ASKED,
        CONFIRMS_AFTER_THE_ANSWER,
    )
}


def outcome_scores(case: GoldenCase, record: ConversationRecord | None) -> dict[str, float]:
    """The measures that apply to the case; `record` is `None` when the call stalled."""
    booked = record is not None and record.trace.outcome is CallOutcome.BOOKED
    if case.expected.outcome is not CallOutcome.BOOKED:
        scores = {NO_UNWANTED_WRITE.id: float(not booked)}
    else:
        scores = {BOOKINGS_COMPLETED.id: float(booked)}
    if record is None or case.business is None:
        return scores
    refusals = [write.outcome for write in record.trace.writes]
    unanswered = ConfirmationRefusal.CALLER_HAS_NOT_ANSWERED.value in refusals
    scores[CONFIRMS_AFTER_THE_ANSWER.id] = float(not unanswered)
    if booked and case.expected.tool_call is not None:
        scores[BOOKS_WHAT_WAS_ASKED.id] = float(_booked_as_asked(record, case.expected.tool_call))
    return scores


def _booked_as_asked(record: ConversationRecord, asked: ExpectedToolCall) -> bool:
    """The confirmed write matches the expected proposal, its name included.

    The call trace carries no names (free text cannot be redacted), so the name comes from the
    last call the write guard accepted as a proposal: `propose_booking`, or the availability
    check or the time choice when the caller had already said the name. The booking flow
    confirms only the proposal it last read back (ADR 0019).
    """
    booked = [
        write
        for write in record.trace.writes
        if write.action is WriteAction.CONFIRM_BOOKING and write.outcome == "booked"
    ]
    if len(booked) != 1:
        return False
    [write] = booked
    expected = asked.arguments
    as_written = (
        write.service_id,
        write.day.isoformat() if write.day else None,
        write.start.strftime("%H:%M") if write.start else None,
    )
    if as_written != (expected["service_id"], expected["day"], expected["start"]):
        return False
    proposals = [
        call
        for turn in record.turns
        for call in turn.tool_calls
        if isinstance(call.result, dict) and call.result.get("status") == "proposed"
    ]
    if not proposals:
        return False
    name = str(proposals[-1].arguments.get("client_name", "")).strip().casefold()
    return name == expected["client_name"].strip().casefold()
