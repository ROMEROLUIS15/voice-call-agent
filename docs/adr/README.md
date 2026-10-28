# Architecture Decision Records

Cross-cutting decisions of the voice call agent. Decisions local to one module live in that module's manifest (`docs/specs/call-module/manifest.md` §11). Constitution §8.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-separate-service-from-the-scheduling-backend.md) | Separate service from the scheduling backend | Accepted |
| [0002](0002-python-and-pipecat-for-the-voice-engine.md) | Python and Pipecat for the voice engine | Accepted |
| [0003](0003-cascaded-speech-architecture.md) | Cascaded speech architecture (STT → LLM → TTS) | Accepted |
| [0004](0004-two-call-entries-over-one-engine.md) | Two call entries over one engine | Accepted, amended by 0015 |
| [0006](0006-names-by-function-and-ports-for-external-systems.md) | Names by function and ports for external systems | Accepted |
| [0007](0007-own-security-headers-middleware.md) | Own security headers middleware | Accepted |
| [0008](0008-security-checks-shared-by-developers-and-ci.md) | Security checks shared by developers and CI | Accepted |
| [0009](0009-error-tracking-and-call-traces-with-sentry.md) | Error tracking and per-call traces with Sentry | Accepted |
| [0010](0010-golden-dataset-and-two-level-evals.md) | Golden dataset and evals at two levels, with a judge model | Accepted, amended by 0013 and 0016 |
| [0011](0011-write-proposals-validated-by-code.md) | Write proposals validated by code; the model judges the caller's confirmation | Accepted, changed 2026-10-27 |
| [0012](0012-pull-requests-with-required-checks.md) | Changes reach main through pull requests with required checks | Accepted |
| [0013](0013-evals-fingerprint-of-what-the-evals-measure.md) | Evals fingerprint of what the evals measure, and the first baseline with the booking prompt | Accepted |
| [0015](0015-browser-practice-entry-for-development.md) | Browser practice entry for development | Accepted, amended by 0017 |
| [0016](0016-quality-margins-from-measured-noise.md) | Quality margins from the measured noise between runs | Accepted |
| [0017](0017-practice-lines-and-conversation-transcripts.md) | Practice lines and conversation transcripts in development | Accepted |
| [0019](0019-pipecat-first-the-conversation-is-a-flows-graph.md) | Pipecat first: the conversation is a Pipecat Flows graph | Accepted |

## Process

*   File name: `NNNN-title-in-english.md`, numbered in sequence, never reused.
*   Status: `Proposed`, `Accepted`, `Accepted, changed YYYY-MM-DD`, `Accepted, amended by NNNN` (earlier ADRs), or `Superseded by NNNN`.
*   Every ADR records its context, the decision, the alternatives considered and its consequences (constitution §8).
*   Add the ADR to the table above in the same change.

## Changing an ADR

An ADR is **published** once it reaches the default branch of the public repository.

*   **Before it is published**, an ADR is edited freely.
*   **Once published**, editorial corrections (wording, links, removing sensitive data) are listed in a `## Revisions` section at the end of the ADR, with their date.
*   **A change to part of a decision** is made in the ADR itself: its text says the current decision, and a dated entry in its `## Changes` section says what changed, why, and where the reason is recorded (a new ADR, the manifest or the pull request). The decision is read in one place, not across a chain of amendments. ADRs that already say `Amends NNNN` keep that history.
*   **A different decision** takes a new ADR whose header says `Supersedes NNNN`; the earlier ADR's status becomes `Superseded by NNNN`. Both stay in the index.

## Template

```markdown
# ADR NNNN: Title

*   **Status:** Proposed
*   **Date:** YYYY-MM-DD
*   **Supersedes:** NNNN (only when it replaces an earlier ADR)

## Context
What forces the decision.

## Decision
What was decided.

## Alternatives considered
Each option and why it was not chosen.

## Consequences
What gets easier, what gets harder, and how the costs are mitigated.

## Changes
Only once published, when part of the decision changes: YYYY-MM-DD · what changed, why, and where the reason is recorded.

## Revisions
Only once published, for editorial corrections: YYYY-MM-DD · what changed.
```
