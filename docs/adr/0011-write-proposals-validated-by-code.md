# ADR 0011: Write proposals validated by code; the model judges the caller's confirmation

*   **Status:** Accepted, changed 2026-10-27
*   **Date:** 2026-10-19

## Context
The agent writes to a system of record. A write must use real values (the call's business, a service of its catalog, a slot the backend offers) and the caller must have agreed to it. The earlier specification enforced that agreement in code twice: the write tools were withheld until the code recognised an explicit confirmation in the caller's previous turn, and every value had to appear in what the caller said. Both require the code to understand spoken Spanish: relative dates ("el jueves que viene"), times in words, service synonyms, transcription errors, and the many ways of saying yes ("dale", "ajá, eso", "perfecto, hágale") or a yes with a change ("sí, pero a las cuatro"). That is what the language model does well; rules in code for it grow with every failing case and block legitimate bookings.

## Decision
*   The model converses, asks for what is missing and proposes the write with a tool (`propose_booking` and, in v1.1, its reschedule and cancel counterparts).
*   The code validates the proposal against the backend at that moment: the business is the call's (`CallSession`), the service belongs to the catalog the backend returned, the slot is in the availability the code reads for that day. It keeps the pending proposal and returns its id with a summary (service, day, time, name) that the agent reads aloud.
*   The model judges whether the caller's answer is a yes and, if so, confirms that proposal id. The code executes only a pending proposal of this call, unchanged since it was validated, after a caller turn that followed its read-back, and at most once: the proposal id is the idempotency key (contract §5).
*   No rule in code classifies the caller's words or looks for the values in the transcript.

## Alternatives considered
*   **Withhold the write tools until the code recognises an explicit confirmation.** Not chosen: recognising a yes in code is a list of phrases that grows case by case and fails on legitimate answers.
*   **Require every value to appear in the transcript (mention guards).** Not chosen: parsing spoken dates, times and service names duplicates the model's work and breaks on transcription errors; the caller's confirmation after the read-back is the stronger evidence.
*   **A second model that classifies the confirmation.** Not chosen: more latency inside a 1 s budget, another model to evaluate, and the same kind of error.
*   **The code speaks the read-back as a fixed phrase.** Not chosen for now: it guarantees the wording but sounds rigid. It is the fallback if the evals show the model misreading the summary.

## Consequences
*   Easier: a natural conversation; no language rules in code; one small component (`write_guards/`) holds the only call state that protects writes: pending proposals, writes done and the identity factor.
*   Harder: whether an answer is a yes is probabilistic. It is measured by golden cases with margin 0 (`no-write-without-confirmation`), the call trace records the caller's answer and the decision, and the risk is accepted in the threat model (R-08) until a trace shows a write the caller did not confirm.

## Changes
2026-10-27 · The conversation becomes a Pipecat Flows graph (ADR 0019): the write functions are offered only in the nodes that need them, and the confirmation node reads the proposal back with a fixed phrase from the code, the fallback this ADR named, because the model misread summaries and spoke for the caller. The validation of writes and the model's judgement of the caller's yes do not change.
