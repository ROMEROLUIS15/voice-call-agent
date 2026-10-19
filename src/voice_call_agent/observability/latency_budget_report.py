"""p50/p95 per channel and segment, checked against the latency budget of manifest §6.

Usage: `uv run python -m voice_call_agent.observability.latency_budget_report [var/latency.jsonl]`
"""

import math
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

from pydantic import BaseModel

from voice_call_agent.observability.latency_record_store import read_latency_records
from voice_call_agent.observability.turn_latency import CallLatencyRecord, TurnLatency


class LatencyBudget(BaseModel):
    """p50 target and p95 limit of a segment, in ms."""

    p50_ms: float
    p95_ms: float


# Manifest §6. Changing a value here requires changing it there.
LATENCY_BUDGETS: dict[str, LatencyBudget] = {
    "stt_ms": LatencyBudget(p50_ms=300, p95_ms=600),
    "llm_ms": LatencyBudget(p50_ms=400, p95_ms=800),
    "tts_ms": LatencyBudget(p50_ms=200, p95_ms=400),
    "total_ms": LatencyBudget(p50_ms=1000, p95_ms=1600),
}


class SegmentSummary(BaseModel):
    """Measured percentiles of a segment and whether they meet its budget."""

    segment: str
    p50_ms: float
    p95_ms: float
    within_budget: bool


class ChannelSummary(BaseModel):
    """Summary of one channel."""

    channel_label: str
    calls: int
    turns: int
    segments: list[SegmentSummary]


def nearest_rank_percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile, without interpolation: few calls never yield unmeasured values."""
    if not values:
        raise ValueError("nearest_rank_percentile() needs at least one value")
    ordered = sorted(values)
    rank = max(math.ceil(q / 100 * len(ordered)), 1)
    return ordered[rank - 1]


def summarize_by_channel(records: Iterable[CallLatencyRecord]) -> list[ChannelSummary]:
    """Group turns by channel and compute p50/p95 of each segment."""
    calls: dict[str, int] = defaultdict(int)
    turns: dict[str, list[TurnLatency]] = defaultdict(list)
    for record in records:
        calls[record.channel_label] += 1
        turns[record.channel_label].extend(record.turns)
    return [
        ChannelSummary(
            channel_label=label,
            calls=calls[label],
            turns=len(turns[label]),
            segments=_summarize_segments(turns[label]),
        )
        for label in sorted(calls)
    ]


def _summarize_segments(turns: list[TurnLatency]) -> list[SegmentSummary]:
    if not turns:
        return []
    summaries = []
    for segment, budget in LATENCY_BUDGETS.items():
        values = [getattr(turn, segment) for turn in turns]
        p50, p95 = nearest_rank_percentile(values, 50), nearest_rank_percentile(values, 95)
        summaries.append(
            SegmentSummary(
                segment=segment,
                p50_ms=p50,
                p95_ms=p95,
                within_budget=p50 <= budget.p50_ms and p95 <= budget.p95_ms,
            )
        )
    return summaries


def render_budget_table(summaries: list[ChannelSummary]) -> str:
    """Plain-text table for the terminal."""
    lines: list[str] = []
    for channel in summaries:
        lines.append(f"{channel.channel_label}: {channel.calls} calls, {channel.turns} turns")
        for s in channel.segments:
            mark = "OK  " if s.within_budget else "OVER"
            budget = LATENCY_BUDGETS[s.segment]
            lines.append(
                f"  {mark} {s.segment:<9} p50 {s.p50_ms:6.0f} ms (≤ {budget.p50_ms:.0f})"
                f"   p95 {s.p95_ms:6.0f} ms (≤ {budget.p95_ms:.0f})"
            )
    return "\n".join(lines) if lines else "No calls recorded."


def main(argv: list[str]) -> int:
    """Command-line entry. The report is program output on stdout, not a log."""
    path = Path(argv[1]) if len(argv) > 1 else Path("var/latency.jsonl")
    if not path.exists():
        sys.stderr.write(f"{path} does not exist\n")
        return 1
    sys.stdout.write(render_budget_table(summarize_by_channel(read_latency_records(path))) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
