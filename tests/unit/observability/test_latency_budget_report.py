from datetime import UTC, datetime
from pathlib import Path

import pytest

from voice_call_agent.observability.latency_budget_report import (
    main,
    nearest_rank_percentile,
    render_budget_table,
    summarize_by_channel,
)
from voice_call_agent.observability.turn_latency import CallLatencyRecord, TurnLatency


def _record(channel: str, totals: list[float]) -> CallLatencyRecord:
    return CallLatencyRecord(
        call_id="x",
        channel_label=channel,
        started_at=datetime(2026, 10, 18, tzinfo=UTC),
        duration_s=60,
        greeting_ms=None,
        turns=[
            TurnLatency(stt_ms=200, llm_ms=300, tts_ms=150, other_ms=0, total_ms=total)
            for total in totals
        ],
    )


def test_nearest_rank_percentile() -> None:
    values = [float(v) for v in range(1, 21)]  # 1..20
    assert nearest_rank_percentile(values, 50) == 10
    assert nearest_rank_percentile(values, 95) == 19
    assert nearest_rank_percentile([7.0], 95) == 7


def test_percentile_of_nothing_is_an_error() -> None:
    with pytest.raises(ValueError):
        nearest_rank_percentile([], 50)


def test_summary_is_per_channel_and_checks_the_budget() -> None:
    summaries = summarize_by_channel(
        [_record("twilio", [900, 1000, 1100]), _record("whatsapp", [700, 800, 2000])]
    )
    by_channel = {s.channel_label: s for s in summaries}
    twilio_total = next(s for s in by_channel["twilio"].segments if s.segment == "total_ms")
    whatsapp_total = next(s for s in by_channel["whatsapp"].segments if s.segment == "total_ms")

    assert twilio_total.within_budget  # p50 1000 ≤ 1000, p95 1100 ≤ 1600
    assert not whatsapp_total.within_budget  # p95 2000 > 1600
    assert "whatsapp: 1 calls, 3 turns" in render_budget_table(summaries)


def test_call_without_turns_still_counts() -> None:
    [summary] = summarize_by_channel([_record("twilio", [])])
    assert summary.calls == 1
    assert summary.segments == []


def test_missing_file_exits_with_an_error(tmp_path: Path) -> None:
    assert main(["report", str(tmp_path / "missing.jsonl")]) == 1
