"""Builders of Pipecat latency breakdowns for tests."""

from pipecat.observers.user_bot_latency_observer import (
    LatencyBreakdown,
    LatencyContribution,
    LatencyOwnerKind,
    MeasuredFrom,
)


def breakdown(*parts: tuple[str, float], measured_from: MeasuredFrom) -> LatencyBreakdown:
    """A breakdown whose contributions are `(key, seconds)` pairs."""
    return LatencyBreakdown(
        contributions=[
            LatencyContribution(
                key=key,
                label=key,
                owner="test",
                owner_kind=LatencyOwnerKind.SERVICE,
                start_time=0.0,
                duration_secs=secs,
            )
            for key, secs in parts
        ],
        measured_from=measured_from,
        total_secs=sum(secs for _, secs in parts),
    )
