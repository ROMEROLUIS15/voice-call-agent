"""The model evals baseline (`evals/baseline.json`) and the comparison against it."""

from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from evals.quality_criteria import MetricKind, regression_margin

BASELINE_PATH = Path(__file__).parent / "baseline.json"


class MetricScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: MetricKind
    score: float


class MeasurementSetup(BaseModel):
    """What the baseline was measured with."""

    model_config = ConfigDict(frozen=True)

    llm_provider: str
    llm_model: str
    judge_model: str
    repetitions: int
    measured_at: datetime


class EvalBaseline(BaseModel):
    """Scores measured for a behaviour fingerprint; unmeasured until the evals first run."""

    model_config = ConfigDict(frozen=True)

    fingerprint: str
    inputs: dict[str, str]
    measured_with: MeasurementSetup | None = None
    metrics: dict[str, MetricScore] = {}
    accepted_drop: str | None = None
    """Why a quality measure was allowed to drop when this baseline was stored: the cases that
    were added or changed (constitution §16); never set for a security measure."""

    @property
    def measured(self) -> bool:
        return self.measured_with is not None


class Verdict(StrEnum):
    OK = "ok"
    REGRESSION = "regression"
    NEW = "new"
    """Not in the baseline: nothing to compare against yet."""


class MetricComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_id: str
    kind: MetricKind
    baseline: float | None
    current: float
    margin: float
    verdict: Verdict


def load_baseline(path: Path = BASELINE_PATH) -> EvalBaseline:
    return EvalBaseline.model_validate_json(path.read_text(encoding="utf-8"))


def save_baseline(baseline: EvalBaseline, path: Path = BASELINE_PATH) -> None:
    path.write_text(baseline.model_dump_json(indent=2) + "\n", encoding="utf-8")


def compare_with_baseline(
    baseline: EvalBaseline, current: dict[str, MetricScore]
) -> list[MetricComparison]:
    """A measure regresses when it drops below the baseline by more than its margin."""
    comparisons = []
    for metric_id, score in sorted(current.items()):
        margin = regression_margin(metric_id, score.kind)
        previous = baseline.metrics.get(metric_id)
        if previous is None:
            verdict = Verdict.NEW
        elif score.score < previous.score - margin:
            verdict = Verdict.REGRESSION
        else:
            verdict = Verdict.OK
        comparisons.append(
            MetricComparison(
                metric_id=metric_id,
                kind=score.kind,
                baseline=None if previous is None else previous.score,
                current=score.score,
                margin=margin,
                verdict=verdict,
            )
        )
    return comparisons
