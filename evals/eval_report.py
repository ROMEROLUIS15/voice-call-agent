"""The model evals report, in Markdown: for a pull request summary or a terminal."""

from collections import Counter

from evals.eval_baseline import EvalBaseline, MetricComparison, Verdict
from evals.model_eval_runs import CaseRun
from evals.task_metrics import TASK_METRICS

_ROLE_LABEL = {"assistant": "Agent", "user": "Caller"}


def render_report(
    *,
    model_label: str,
    judge_model: str,
    baseline: EvalBaseline,
    comparisons: list[MetricComparison],
    runs: list[CaseRun],
    accepted_drop: str | None = None,
) -> str:
    """`accepted_drop`: why the quality drops below were accepted into the new baseline."""
    regressions = [c.metric_id for c in comparisons if c.verdict is Verdict.REGRESSION]
    verdict = f"REGRESSION: {', '.join(regressions)}" if regressions else "No regression."
    if regressions and accepted_drop is not None:
        verdict = f"Quality drop accepted ({', '.join(regressions)}): {accepted_drop}"
    lines = [
        "# Model evals",
        "",
        f"Model under test: `{model_label}` · judge: `{judge_model}` · "
        f"{max((run.repetition for run in runs), default=0)} repetitions per case.",
        _baseline_line(baseline),
        _upstreams_line(runs),
        "",
        f"**{verdict}**",
        "",
        "| Measure | Kind | Baseline | Now | Allowed drop | Verdict |",
        "|---|---|---|---|---|---|",
        *(_comparison_row(comparison) for comparison in comparisons),
        "",
        "## Cases (first repetition, and every repetition that lowered a measure)",
    ]
    for run in runs:
        lines.extend(_case_section(run))
    return "\n".join(lines) + "\n"


def _baseline_line(baseline: EvalBaseline) -> str:
    setup = baseline.measured_with
    if setup is None:
        return "Baseline: not measured yet, so nothing is compared (`--write-baseline`)."
    return (
        f"Baseline: `{setup.llm_provider} {setup.llm_model}`, judge `{setup.judge_model}`, "
        f"measured {setup.measured_at:%Y-%m-%d}."
    )


def _upstreams_line(runs: list[CaseRun]) -> str:
    """Which upstream providers served the model under test, when its provider routes."""
    served: Counter[str] = Counter()
    for run in runs:
        served.update(run.llm_upstreams)
    if not served:
        return "Upstream providers: not reported (the provider does not route)."
    return (
        "Upstream providers: "
        + ", ".join(f"{name} {count}" for name, count in sorted(served.items()))
        + " responses."
    )


def _comparison_row(comparison: MetricComparison) -> str:
    baseline = "—" if comparison.baseline is None else f"{comparison.baseline:.2f}"
    return (
        f"| {comparison.metric_id} | {comparison.kind.value} | {baseline} | "
        f"{comparison.current:.2f} | {comparison.margin:.2f} | {comparison.verdict.value} |"
    )


def _case_section(run: CaseRun) -> list[str]:
    """The conversation and every score below 1.00 that lowered a measure: a measure is the
    mean of its scores, so any of them lowers it, not only those under the judge's threshold."""
    low_judge = [s for s in run.judge_scores if s.score < 1.0]
    low_tasks = {metric: score for metric, score in run.task_scores.items() if score < 1.0}
    if run.repetition != 1 and not low_judge and not low_tasks and run.failure is None:
        return []
    lines = ["", f"### {run.case.id} · repetition {run.repetition}", ""]
    if run.failure is not None:
        lines.append(f"Conversation failed: {run.failure}")
    else:
        for turn in run.turns:
            lines.extend(f"- Tool `{call.name}`: {call.result}" for call in turn.tool_calls)
            lines.append(f"- {_ROLE_LABEL[turn.role]}: {turn.text}")
    lines.extend(
        f"- Judge `{score.criterion_id}` {score.score:.2f}: {score.reason}" for score in low_judge
    )
    lines.extend(_task_line(run, metric, score) for metric, score in low_tasks.items())
    return lines


def _task_line(run: CaseRun, metric_id: str, score: float) -> str:
    """A deterministic measure below 1.00, with the model's replies that failed it when it
    judges replies."""
    metric = TASK_METRICS.get(metric_id)
    if metric is None:
        return f"- `{metric_id}` {score:.2f}"
    failed = [reply for reply in run.model_replies if not metric.passes(reply)]
    return f"- `{metric_id}` {score:.2f}, failed by: {' / '.join(failed)}"
