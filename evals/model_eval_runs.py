"""Runs the model-level golden cases and turns their conversations into scores."""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from statistics import mean
from typing import Protocol

from pipecat.services.ai_service import AIService

from evals.conversation_harness.call_transcript import SpokenTurn
from evals.conversation_harness.conversation_driver import (
    ConversationRecord,
    ConversationStalledError,
    hold_conversation,
)
from evals.eval_baseline import MetricScore
from evals.golden_cases import GoldenCase
from evals.judge_scoring import JUDGE_PASS_THRESHOLD, JudgeScore
from evals.quality_criteria import QUALITY_CRITERIA, REPETITIONS, MetricKind
from evals.task_metrics import TASK_METRICS, task_scores
from voice_call_agent.conversation_content.content_loader import ConversationContent
from voice_call_agent.observability.call_trace import ServiceVersions

_CONCURRENT_CONVERSATIONS = 3
"""Keeps the provider's rate limits out of the measurement."""


class ConversationScorer(Protocol):
    async def score(self, case: GoldenCase, record: ConversationRecord) -> list[JudgeScore]: ...


@dataclass(frozen=True)
class CaseRun:
    """One repetition of one case."""

    case: GoldenCase
    repetition: int
    agent_lines: list[str]
    task_scores: dict[str, float]
    judge_scores: list[JudgeScore]
    failure: str | None = None
    turns: tuple[SpokenTurn, ...] = ()
    """The call in order, as the judge read it."""
    llm_upstreams: dict[str, int] = field(default_factory=dict)
    """Responses served by each upstream provider of the model under test."""


@dataclass(frozen=True)
class ModelUnderTest:
    content: ConversationContent
    services: ServiceVersions
    create_language_model: Callable[[str], AIService]


async def run_cases(
    cases: list[GoldenCase],
    model: ModelUnderTest,
    judge: ConversationScorer,
    repetitions: int = REPETITIONS,
) -> list[CaseRun]:
    """Every case `repetitions` times, a few conversations at a time."""
    slots = asyncio.Semaphore(_CONCURRENT_CONVERSATIONS)

    async def run(case: GoldenCase, repetition: int) -> CaseRun:
        async with slots:
            return await _run_case(case, repetition, model, judge)

    return list(
        await asyncio.gather(
            *(run(case, repetition) for case in cases for repetition in range(1, repetitions + 1))
        )
    )


async def _run_case(
    case: GoldenCase, repetition: int, model: ModelUnderTest, judge: ConversationScorer
) -> CaseRun:
    try:
        record = await hold_conversation(
            case,
            content=model.content,
            services=model.services,
            create_language_model=model.create_language_model,
        )
    except ConversationStalledError as error:
        # A model that stalls the call scores zero on everything this case measures.
        return CaseRun(
            case=case,
            repetition=repetition,
            agent_lines=[],
            task_scores=task_scores([]),
            judge_scores=[JudgeScore(c, 0.0, str(error)) for c in case.expected.quality],
            failure=str(error),
        )
    return CaseRun(
        case=case,
        repetition=repetition,
        agent_lines=record.agent_lines,
        task_scores=task_scores(record.agent_lines[1:]),
        judge_scores=await judge.score(case, record),
        turns=record.turns,
        llm_upstreams=record.trace.llm_upstreams,
    )


def aggregate_scores(runs: list[CaseRun]) -> dict[str, MetricScore]:
    """Mean over every run that measures it; a security criterion counts as met or not."""
    values: defaultdict[str, list[float]] = defaultdict(list)
    for run in runs:
        for metric_id, score in run.task_scores.items():
            values[metric_id].append(score)
        for judged in run.judge_scores:
            criterion = QUALITY_CRITERIA[judged.criterion_id]
            met = judged.score >= JUDGE_PASS_THRESHOLD
            values[criterion.id].append(
                float(met) if criterion.kind is MetricKind.SECURITY else judged.score
            )
    kinds = {metric.id: metric.kind for metric in TASK_METRICS.values()} | {
        criterion.id: criterion.kind for criterion in QUALITY_CRITERIA.values()
    }
    return {
        metric_id: MetricScore(kind=kinds[metric_id], score=round(mean(scores), 4))
        for metric_id, scores in sorted(values.items())
    }
