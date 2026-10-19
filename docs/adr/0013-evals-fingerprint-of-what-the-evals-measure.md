# ADR 0013: Evals fingerprint of what the evals measure, and the first baseline with the booking prompt

*   **Status:** Accepted
*   **Date:** 2026-10-19
*   **Amends:** 0010

## Context
ADR 0010 guards the evals baseline with a fingerprint of the inputs it was measured with. Two of those inputs, the speech-to-text model and the voice, never reach the model evals: they run with scripted speech-to-text and a recording text-to-speech, so changing either would demand a paid run that cannot detect any effect. And the phase 0 prompt is provisional (a test line that books nothing): a baseline measured with it would gate prompt changes that phase 2 replaces anyway.

## Decision
This ADR changes only these two points of ADR 0010; the rest of ADR 0010 holds.
*   **The fingerprint covers only what the model evals exercise:** conversation content version, model and generation settings, dataset version, scoring code and judge model. The speech-to-text model and the voice leave it; they stay in every call trace, and their effect is measured with real calls.
*   **The first baseline is measured with the booking prompt of phase 2.** Until then `--record-fingerprint` records the inputs unmeasured; once measured, the fingerprint changes only with new measurements.

## Alternatives considered
*   **Keep ADR 0010 unchanged.** Not chosen: a voice change would demand a paid run that measures nothing, and a baseline of the provisional prompt would gate changes that phase 2 replaces.
*   **Measure the baseline now, with the phase 0 prompt.** Not chosen: its scores (admitting that the line is in testing, for instance) stop meaning anything once the booking prompt replaces it.
*   **A new ADR that supersedes 0010 and restates it whole.** Not chosen: most of ADR 0010 does not change, and two copies of the same decision drift apart.

## Consequences
*   Easier: the provisional prompt can change during phase 0 without paid runs; a voice or speech-to-text change needs no model evals.
*   Harder: until the booking prompt exists nothing is compared, so a phase 0 prompt change is reviewed through its snapshot only. The evals decision is read in ADR 0010 together with this amendment.
