"""Deterministic measures of the model's replies: no judge, the same verdict every time.

What the agent says becomes speech, so a reply must read naturally aloud (system prompt).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from evals.quality_criteria import MetricKind

MAX_SENTENCES = 2
# Digits (numbers and times are written as spoken), markup, parentheses (the model wrote stage
# directions in them, manifest §10), list markers and emojis.
_UNSPEAKABLE = re.compile(
    r"[0-9*#_`~|<>()\[\]{}\u2022@]|(^|\n)\s*-\s|[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]"
)
_SENTENCE_END = re.compile(r"[.!?…]+(?=\s|$)")


@dataclass(frozen=True)
class TaskMetric:
    id: str
    kind: MetricKind
    description: str
    passes: Callable[[str], bool]


def is_speakable(reply: str) -> bool:
    return _UNSPEAKABLE.search(reply) is None


def is_brief(reply: str) -> bool:
    """At most two sentences; a reply without final punctuation is one sentence."""
    return max(1, len(_SENTENCE_END.findall(reply.strip()))) <= MAX_SENTENCES


TASK_METRICS: dict[str, TaskMetric] = {
    metric.id: metric
    for metric in (
        TaskMetric(
            id="speakable-replies",
            kind=MetricKind.QUALITY,
            description="No digits, markup, list markers or emojis in a reply.",
            passes=is_speakable,
        ),
        TaskMetric(
            id="brief-replies",
            kind=MetricKind.QUALITY,
            description=f"At most {MAX_SENTENCES} sentences per reply.",
            passes=is_brief,
        ),
    )
}


def task_scores(replies: list[str]) -> dict[str, float]:
    """Share of the model's replies (the greeting excluded) that pass each measure.

    A conversation where the code said every line (a read-back, a booking announced) has no reply
    of the model to measure: it gives no score, rather than zero.
    """
    if not replies:
        return {}
    return {
        metric.id: sum(metric.passes(reply) for reply in replies) / len(replies)
        for metric in TASK_METRICS.values()
    }
