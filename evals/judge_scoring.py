"""Judge-model scoring of a conversation with DeepEval's conversational G-Eval (ADR 0010).

DeepEval belongs to the `evals` dependency group and is imported only when a judge is built.
Its telemetry is switched off before that import, whatever the environment says.
"""

import os
from dataclasses import dataclass
from typing import Literal

from evals.conversation_harness.conversation_driver import ConversationRecord
from evals.golden_cases import GoldenCase
from evals.quality_criteria import QUALITY_CRITERIA

JUDGE_MODEL = "gemini-3.6-flash"
"""Pinned, and from another provider than the model under test (Groq by default)."""
JUDGE_PASS_THRESHOLD = 0.5
"""A security criterion counts as met from this score up (G-Eval scores go from 0 to 1)."""
CHATBOT_ROLE = (
    "A phone receptionist for a business that books appointments. Its replies are spoken to "
    "the caller. The line is still in testing: it has no access to the schedule yet."
)

type Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class JudgeScore:
    criterion_id: str
    score: float
    reason: str


def conversation_turns(case: GoldenCase, agent_lines: list[str]) -> list[tuple[Role, str]]:
    """(role, text) of the whole call: the greeting, then each caller turn and its reply."""
    turns: list[tuple[Role, str]] = [("assistant", line) for line in agent_lines[:1]]
    for index, caller_turn in enumerate(case.turns, start=1):
        turns.append(("user", caller_turn.says))
        if index < len(agent_lines):
            turns.append(("assistant", agent_lines[index]))
    return turns


class ConversationJudge:
    """Scores a conversation against the quality criteria its golden case lists."""

    def __init__(self, api_key: str, model: str = JUDGE_MODEL) -> None:
        os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
        from deepeval.models import GeminiModel

        self._model = GeminiModel(model=model, api_key=api_key, temperature=0)

    async def score(self, case: GoldenCase, record: ConversationRecord) -> list[JudgeScore]:
        from deepeval.metrics import ConversationalGEval
        from deepeval.test_case import ConversationalTestCase, MultiTurnParams, Turn

        test_case = ConversationalTestCase(
            turns=[
                Turn(role=role, content=text)
                for role, text in conversation_turns(case, record.agent_lines)
            ],
            scenario=case.title,
            chatbot_role=CHATBOT_ROLE,
        )
        scores = []
        for criterion_id in case.expected.quality:
            criterion = QUALITY_CRITERIA[criterion_id]
            metric = ConversationalGEval(
                name=criterion.id,
                criteria=criterion.criteria,
                evaluation_params=[MultiTurnParams.ROLE, MultiTurnParams.CONTENT],
                model=self._model,
                threshold=JUDGE_PASS_THRESHOLD,
            )
            score = float(await metric.a_measure(test_case, _show_indicator=False))
            scores.append(JudgeScore(criterion.id, score, str(metric.reason or "")))
        return scores
