"""What a reference conversation must show, read from its record and its call trace."""

from evals.conversation_harness.conversation_driver import ConversationRecord
from evals.golden_cases import GoldenCase
from voice_call_agent.observability.error_taxonomy import ErrorKind


def conversation_failures(case: GoldenCase, record: ConversationRecord, greeting: str) -> list[str]:
    """Every expectation of the case the conversation missed, readable; empty when it passed."""
    expected, trace = case.expected, record.trace
    real_failures = [error.code for error in trace.errors if error.kind is ErrorKind.REAL_FAILURE]
    checks: list[tuple[str, object, object]] = [
        ("channel", trace.channel_label, case.channel.value),
        ("identity verified", trace.identity_verified, expected.identity_verified),
        ("outcome", trace.outcome, expected.outcome),
        ("caller turns in the trace", trace.caller_turns, len(case.turns)),
        ("turns with measured latency", len(trace.turns), len(case.turns)),
        ("greeting latency measured", trace.greeting_ms is not None, True),
        ("first thing the agent says", record.agent_lines[:1], [greeting]),
        ("agent lines (greeting + one per turn)", len(record.agent_lines), len(case.turns) + 1),
        ("agent stopped when interrupted", record.agent_interrupted, expected.agent_interrupted),
        ("write decisions", [write.outcome for write in trace.writes], list(expected.writes)),
        ("real failures", sorted(real_failures), sorted(expected.real_failures)),
    ]
    return [
        f"{name}: expected {wanted!r}, got {actual!r}"
        for name, actual, wanted in checks
        if actual != wanted
    ]
