"""Golden case runs and a judge for testing the model evals without any provider."""

from datetime import UTC, datetime

from evals.conversation_harness.conversation_driver import ConversationRecord
from evals.golden_cases import GoldenCase, load_golden_dataset
from evals.judge_scoring import JudgeScore
from evals.model_eval_runs import CaseRun
from evals.task_metrics import task_scores

MEASURED_AT = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def golden_case(case_id: str) -> GoldenCase:
    return next(case for case in load_golden_dataset() if case.id == case_id)


def case_run(
    case_id: str, judged: dict[str, float], repetition: int = 1, replies: tuple[str, ...] = ()
) -> CaseRun:
    return CaseRun(
        case=golden_case(case_id),
        repetition=repetition,
        agent_lines=["Hola.", *replies],
        task_scores=task_scores(list(replies)),
        judge_scores=[JudgeScore(c, score, "because") for c, score in judged.items()],
    )


class FixedScoreJudge:
    """Gives every criterion of a case the same score."""

    def __init__(self, score: float) -> None:
        self._score = score
        self.records: list[ConversationRecord] = []

    async def score(self, case: GoldenCase, record: ConversationRecord) -> list[JudgeScore]:
        self.records.append(record)
        return [JudgeScore(c, self._score, "fixed") for c in case.expected.quality]
