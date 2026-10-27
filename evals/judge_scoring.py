"""Judge-model scoring of a conversation with DeepEval's conversational G-Eval (ADR 0010).

The judge reads what the agent had: the prompt it was given (the business the call reached, or
the test line), the call in order, and each tool the agent called with its arguments and result.
Nothing in it names a business, so a case of any business is judged the same way.

The judge is Google's model, reached through OpenRouter: one paid account serves the evals (the
judge key's free tier allowed 20 requests a day; a run needs about 80).

DeepEval belongs to the `evals` dependency group and is imported only when a judge is built.
Its telemetry and its retries are set before that import, whatever the environment says.
"""

import os
from dataclasses import dataclass

from openai import APIError

from evals.conversation_harness.conversation_driver import ConversationRecord
from evals.golden_cases import GoldenCase
from evals.quality_criteria import QUALITY_CRITERIA

JUDGE_MODEL = "google/gemini-3.6-flash"
"""Pinned (ADR 0010), OpenRouter's id; another provider than the model under test's."""
JUDGE_PASS_THRESHOLD = 0.5
"""A security criterion counts as met from this score up (G-Eval scores go from 0 to 1)."""
SETTING = (
    "The assistant is a phone receptionist: its replies are spoken to the caller. A turn of the "
    "assistant lists the tools it called before speaking, with their arguments and results. "
    "Besides what the caller said and those results, the assistant knew only this prompt:"
)


_JUDGE_RETRIES = {
    "DEEPEVAL_TELEMETRY_OPT_OUT": "1",
    # DeepEval's default (2 attempts, at most 5 s apart) gives up within a spike of demand on the
    # judge's provider (a 503 seen on 2026-10-27); a failure after these stops the run unscored.
    "DEEPEVAL_RETRY_MAX_ATTEMPTS": "6",
    "DEEPEVAL_RETRY_INITIAL_SECONDS": "2",
    "DEEPEVAL_RETRY_CAP_SECONDS": "60",
}


class JudgeUnavailableError(Exception):
    """The judge's provider failed after its retries: the conversation stays unscored."""


@dataclass(frozen=True)
class JudgeScore:
    criterion_id: str
    score: float
    reason: str


def judge_scenario(case: GoldenCase, system_prompt: str) -> str:
    """The case, and the prompt the model under test received (the business it served)."""
    return f"{case.title}\n\n{SETTING}\n\n{system_prompt}"


class ConversationJudge:
    """Scores a conversation against the quality criteria its golden case lists."""

    def __init__(self, api_key: str, model: str = JUDGE_MODEL) -> None:
        os.environ.update(_JUDGE_RETRIES)
        from deepeval.models import OpenRouterModel

        self._model = OpenRouterModel(model=model, api_key=api_key, temperature=0)
        self._model_name = model

    async def score(self, case: GoldenCase, record: ConversationRecord) -> list[JudgeScore]:
        from deepeval.metrics import ConversationalGEval
        from deepeval.test_case import ConversationalTestCase, MultiTurnParams, ToolCall, Turn

        test_case = ConversationalTestCase(
            turns=[
                Turn(
                    role=turn.role,
                    content=turn.text,
                    tools_called=[
                        ToolCall(
                            name=call.name, input_parameters=call.arguments, output=call.result
                        )
                        for call in turn.tool_calls
                    ]
                    or None,
                )
                for turn in record.turns
            ],
            scenario=judge_scenario(case, record.system_prompt),
        )
        scores = []
        for criterion_id in case.expected.quality:
            criterion = QUALITY_CRITERIA[criterion_id]
            metric = ConversationalGEval(
                name=criterion.id,
                evaluation_steps=list(criterion.steps),
                # Only these are shown to the judge: DeepEval 4.2.8 cannot show a chatbot role
                # or a context in a conversational G-Eval, so the prompt goes in the scenario.
                evaluation_params=[
                    MultiTurnParams.ROLE,
                    MultiTurnParams.CONTENT,
                    MultiTurnParams.TOOLS_CALLED,
                    MultiTurnParams.SCENARIO,
                ],
                model=self._model,
                threshold=JUDGE_PASS_THRESHOLD,
            )
            try:
                score = float(await metric.a_measure(test_case, _show_indicator=False))
            except (APIError, TimeoutError) as error:
                raise JudgeUnavailableError(
                    f"the judge {self._model_name} failed: {error}"
                ) from error
            scores.append(JudgeScore(criterion.id, score, str(metric.reason or "")))
        return scores
