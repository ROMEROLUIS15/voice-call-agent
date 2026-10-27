"""The model evals report, in Markdown: for a pull request summary or a terminal."""

from collections import Counter

from evals.eval_baseline import EvalBaseline, MetricComparison, Verdict
from evals.judge_scoring import JUDGE_PASS_THRESHOLD
from evals.model_eval_runs import CaseRun

_ROLE_LABEL = {"assistant": "Agent", "user": "Caller"}


def render_report(
    *,
    model_label: str,
    judge_model: str,
    baseline: EvalBaseline,
    comparisons: list[MetricComparison],
    runs: list[CaseRun],
) -> str:
    regressions = [c.metric_id for c in comparisons if c.verdict is Verdict.REGRESSION]
    lines = [
        "# Model evals",
        "",
        f"Model under test: `{model_label}` · judge: `{judge_model}` · "
        f"{max((run.repetition for run in runs), default=0)} repetitions per case.",
        _baseline_line(baseline),
        _upstreams_line(runs),
        "",
        f"**{'REGRESSION: ' + ', '.join(regressions) if regressions else 'No regression.'}**",
        "",
        "| Measure | Kind | Baseline | Now | Allowed drop | Verdict |",
        "|---|---|---|---|---|---|",
        *(_comparison_row(comparison) for comparison in comparisons),
        "",
        "## Cases (first repetition, and every judge score below the threshold)",
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
    low_scores = [s for s in run.judge_scores if s.score < JUDGE_PASS_THRESHOLD]
    if run.repetition != 1 and not low_scores and run.failure is None:
        return []
    lines = ["", f"### {run.case.id} · repetition {run.repetition}", ""]
    if run.failure is not None:
        lines.append(f"Conversation failed: {run.failure}")
    elif run.repetition == 1:
        for turn in run.turns:
            lines.extend(f"- Tool `{call.name}`: {call.result}" for call in turn.tool_calls)
            lines.append(f"- {_ROLE_LABEL[turn.role]}: {turn.text}")
    lines.extend(
        f"- Judge `{score.criterion_id}` {score.score:.2f}: {score.reason}" for score in low_scores
    )
    return lines
