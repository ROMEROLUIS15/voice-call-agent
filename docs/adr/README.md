# Architecture Decision Records

Cross-cutting decisions of the voice call agent. Decisions local to one module live in that module's manifest (`docs/specs/call-module/manifest.md` §11). Constitution §8.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-separate-service-from-the-scheduling-backend.md) | Separate service from the scheduling backend | Accepted |
| [0002](0002-python-and-pipecat-for-the-voice-engine.md) | Python and Pipecat for the voice engine | Accepted |
| [0003](0003-cascaded-speech-architecture.md) | Cascaded speech architecture (STT → LLM → TTS) | Accepted |
| [0004](0004-two-call-entries-over-one-engine.md) | Two call entries over one engine | Accepted |
| [0005](0005-english-repository-with-localized-caller-content.md) | English repository with localized caller content | Accepted |
| [0006](0006-names-by-function-and-ports-for-external-systems.md) | Names by function and ports for external systems | Accepted |
| [0007](0007-own-security-headers-middleware.md) | Own security headers middleware | Accepted |
| [0008](0008-security-checks-shared-by-developers-and-ci.md) | Security checks shared by developers and CI | Accepted |
| [0009](0009-error-tracking-and-call-traces-with-sentry.md) | Error tracking and per-call traces with Sentry | Accepted |
| [0010](0010-golden-dataset-and-two-level-evals.md) | Golden dataset and evals at two levels, with a judge model | Accepted |

## Process

*   File name: `NNNN-title-in-english.md`, numbered in sequence, never reused.
*   Status: `Proposed`, `Accepted`, or `Superseded by NNNN`. An accepted ADR is not rewritten; a new ADR supersedes it and both link to each other.
*   Every ADR records its context, the decision, the alternatives considered and its consequences (constitution §8).
*   Add the ADR to the table above in the same change.

## Template

```markdown
# ADR NNNN: Title

*   **Status:** Proposed
*   **Date:** YYYY-MM-DD

## Context
What forces the decision.

## Decision
What was decided.

## Alternatives considered
Each option and why it was not chosen.

## Consequences
What gets easier, what gets harder, and how the costs are mitigated.
```
