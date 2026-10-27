# ADR 0016: Quality margins from the measured noise between runs

*   **Status:** Accepted
*   **Date:** 2026-10-27
*   **Amends:** 0010

## Context
ADR 0010 lets a security measure drop by nothing and every quality measure by 0.05 against the baseline, a margin set before any run had been measured. Four runs of the model evals on 2026-10-27, with the same prompt and model, scored `brief-replies` 0.89, 0.98, 0.94 and 0.91: the unchanged agent spreads by 0.09, wider than its margin. A pull request that changed nothing about brevity failed the evals check on that measure, while the other quality measures (`natural-spanish`, `admits-test-line`, `speakable-replies`) scored 1.00 in every run. A margin narrower than the noise fails runs that changed nothing, and teaches reviewers to ignore the check.

## Decision
This ADR changes only the quality margin of ADR 0010; the rest of ADR 0010, as amended by ADR 0013, holds.
*   **A quality measure may drop by 0.05, or by the spread observed between runs of the unchanged agent when that spread is wider.** The measures with their own margin and the runs that justify it are listed in `evals/quality_criteria.py` (`QUALITY_MARGINS`); today `brief-replies` may drop by 0.10.
*   **Security measures keep a margin of 0**, whatever their spread: a security measure that varies is investigated, never given room.
*   **Margins are reviewed as the dataset grows**, from the runs measured since the last review.

## Alternatives considered
*   **Keep 0.05 for every quality measure.** Not chosen: `brief-replies` fails runs that changed nothing, and a check that fails on noise stops being read.
*   **More repetitions per case.** Not chosen alone: five repetitions instead of three would narrow the spread to about 0.07 at two thirds more cost per run, still wider than 0.05.
*   **Widen every quality margin to 0.10.** Not chosen: the stable measures would lose sensitivity they have.
*   **Count brevity in words instead of sentences.** Not chosen now: it changes what the measure means; it can be weighed on its own when the prompt's instruction (one or two sentences per turn) changes.

## Consequences
*   Easier: the evals check fails on changes, not on the noise of a measure.
*   Harder: a real drop in brevity smaller than 0.10 passes; brevity is quality, not safety, and each run's report still shows the score. The evals decision is read in ADR 0010 with ADRs 0013 and 0016.
