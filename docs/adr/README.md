# Architecture Decision Records

Cross-cutting decisions of the voice call agent. Decisions local to one module live in that module's manifest (`docs/specs/call-module/manifest.md` §11). Constitution §8.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-separate-service-from-the-scheduling-backend.md) | Separate service from the scheduling backend | Accepted |
| [0002](0002-python-and-pipecat-for-the-voice-engine.md) | Python and Pipecat for the voice engine | Accepted |
| [0003](0003-cascaded-speech-architecture.md) | Cascaded speech architecture (STT → LLM → TTS) | Accepted |
| [0004](0004-two-call-entries-over-one-engine.md) | Two call entries over one engine | Accepted |
| [0006](0006-names-by-function-and-ports-for-external-systems.md) | Names by function and ports for external systems | Accepted |
| [0007](0007-own-security-headers-middleware.md) | Own security headers middleware | Accepted |
| [0008](0008-security-checks-shared-by-developers-and-ci.md) | Security checks shared by developers and CI | Accepted |
| [0009](0009-error-tracking-and-call-traces-with-sentry.md) | Error tracking and per-call traces with Sentry | Accepted |
| [0010](0010-golden-dataset-and-two-level-evals.md) | Golden dataset and evals at two levels, with a judge model | Accepted, amended by 0013 |
| [0011](0011-write-proposals-validated-by-code.md) | Write proposals validated by code; the model judges the caller's confirmation | Accepted |
| [0012](0012-pull-requests-with-required-checks.md) | Changes reach main through pull requests with required checks | Accepted |
| [0013](0013-evals-fingerprint-of-what-the-evals-measure.md) | Evals fingerprint of what the evals measure, and the first baseline with the booking prompt | Accepted |
| [0014](0014-one-phone-number-shared-by-every-business.md) | One phone number shared by every business | Accepted |

## Process

*   File name: `NNNN-title-in-english.md`, numbered in sequence, never reused.
*   Status: `Proposed`, `Accepted`, `Accepted, amended by NNNN`, or `Superseded by NNNN`.
*   Every ADR records its context, the decision, the alternatives considered and its consequences (constitution §8).
*   Add the ADR to the table above in the same change.

## Changing an ADR

An ADR is **published** once it reaches the default branch of the public repository.

*   **Before it is published**, an ADR is edited freely.
*   **Once published**, only editorial corrections are allowed: wording, links, or removing sensitive data. Each one is listed in a `## Revisions` section at the end of the ADR, with its date and what changed. The decision does not change.
*   **A different decision** takes a new ADR whose header says `Supersedes NNNN`; the earlier ADR's status becomes `Superseded by NNNN`. Both stay in the index.
*   **A change to part of a decision** takes a new ADR whose header says `Amends NNNN` and that records only what changes, with its context, alternatives and consequences. The earlier ADR stays in force for everything else and its status becomes `Accepted, amended by NNNN`: the decision is read in both. When amendments make the earlier ADR hard to follow, a new ADR supersedes it with the whole decision.

## Template

```markdown
# ADR NNNN: Title

*   **Status:** Proposed
*   **Date:** YYYY-MM-DD
*   **Supersedes:** NNNN (only when it replaces an earlier ADR)
*   **Amends:** NNNN (only when it changes part of an earlier ADR)

## Context
What forces the decision.

## Decision
What was decided.

## Alternatives considered
Each option and why it was not chosen.

## Consequences
What gets easier, what gets harder, and how the costs are mitigated.

## Revisions
Only once published, for editorial corrections: YYYY-MM-DD · what changed.
```
