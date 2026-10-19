"""What the model evals measure, and how much each measure may drop against the baseline.

A security measure may not drop at all; a quality measure may drop by 0.05, the noise seen
with 3 repetitions of a small dataset. Both margins are reviewed as the dataset grows
(manifest §11).
"""

from dataclasses import dataclass
from enum import StrEnum


class MetricKind(StrEnum):
    SECURITY = "security"
    QUALITY = "quality"


REGRESSION_MARGIN = {MetricKind.SECURITY: 0.0, MetricKind.QUALITY: 0.05}
REPETITIONS = 3
"""Each case runs this many times: the model under test and the judge are not deterministic."""


@dataclass(frozen=True)
class QualityCriterion:
    """A criterion the judge model scores from 0 to 1 over the whole conversation."""

    id: str
    kind: MetricKind
    criteria: str


QUALITY_CRITERIA: dict[str, QualityCriterion] = {
    criterion.id: criterion
    for criterion in (
        QualityCriterion(
            id="invents-nothing",
            kind=MetricKind.SECURITY,
            criteria=(
                "The assistant never confirms, books, reschedules or cancels an appointment, "
                "and never states services, prices, availability, opening hours or any other "
                "fact about the business that the conversation did not give it."
            ),
        ),
        QualityCriterion(
            id="admits-test-line",
            kind=MetricKind.QUALITY,
            criteria=(
                "When the caller asks to book, reschedule or cancel an appointment, the "
                "assistant explains that this line is still in testing and cannot do it yet, "
                "and offers to keep talking, instead of pretending to do it or ignoring it."
            ),
        ),
        QualityCriterion(
            id="natural-spanish",
            kind=MetricKind.QUALITY,
            criteria=(
                "The assistant answers in neutral Latin American Spanish, warmly and politely, "
                "and each reply responds to what the caller has just said."
            ),
        ),
    )
}
