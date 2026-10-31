# ADR 0019: Pipecat first: the conversation is a Pipecat Flows graph

*   **Status:** Accepted
*   **Date:** 2026-10-27

## Context
The agent runs on Pipecat, and its booking conversation is one prompt that offers every tool at once. Pipecat's documentation names that shape as the problem: "Pipecat Flows structures a conversation as a flow: a graph of nodes, where each node focuses the LLM on a single task with only the tools it needs. This approach solves a common problem: monolithic prompts with many tools lead to hallucinations and lower accuracy" (Pipecat Flows overview). Practice calls and the model evals showed those failures: dates worked out wrong, the model answering for the caller, proposals announced in words instead of made with the tool, and a confirmation skipped after the caller's yes. Law zero of the constitution ("the code does not script the conversation") kept that structure out.

The repository also built its own versions of pieces Pipecat ships: a conversation harness with fixed scripts and a judge, while Pipecat Evals runs scripted scenarios and simulated callers that adapt to the agent (a measurement failed because a fixed script ran out of turns when the agent asked one more question); transcripts read from the model's context, while Pipecat documents them with turn events. Pipecat 1.14.0, the pinned version, includes `pipecat.flows`, `pipecat.evals` and the observers.

## Decision
*   **Pipecat's documented patterns come first.** Its built-ins (Flows, Evals, observers, turn and mute strategies, OpenTelemetry tracing) are used before any code of our own. Own code exists only for a gap Pipecat leaves, and says at the code which gap it fills.
*   **The conversation is a Pipecat Flows graph**, written in Python: its nodes depend on the business's catalog and on the availability the backend returns, and its functions need strict schemas, which are Pipecat's own reasons to build a flow in code rather than in a config. Each node has one task and only its functions. The code states the facts the model gets wrong when it works them out (the calendar of the coming days, dates and times said aloud) and reads the proposal back in a confirmation node that waits for the caller (a pre-action that says it, `respond_immediately=False`); transitions follow the functions' results. The write guard of ADR 0011 still validates every write, and the model still judges the caller's yes by calling the confirmation function, which only the confirmation node offers.
*   **Migration order:** the booking conversation as a Flows graph; Pipecat Evals with scripted and simulated scenarios in place of the conversation harness, keeping the checks of what each call wrote; Pipecat's observers, turn events and tracing in place of own observability where they cover it; then the model, chosen with simulated scenarios.

## Alternatives considered
*   **Keep one prompt and make it stricter.** Not chosen: Pipecat's documentation and the measurements point to the structure, not to the wording.
*   **A declarative flow config (YAML).** Not chosen: Pipecat recommends starting declarative, except when nodes are built at runtime or functions need strict schemas, which is this case.
*   **Keep the own harness and observability.** Not chosen: simulated callers cover the paths a fixed script cannot, and every piece Pipecat maintains is one we do not.

## Consequences
*   Easier: small prompts per node; a function cannot be called outside its node; Pipecat's improvements reach pieces we no longer maintain.
*   Harder: the booking conversation and the evals are rewritten; Flows and Evals change with Pipecat, read in its changelog at each upgrade; a graph is more code to read than one prompt.

## Changes
2026-10-28 · The code's lines (the greeting, the read-back) are a custom pre-action instead of Flows' `tts_say`: Flows waits for `tts_say` to finish before applying the node, and a caller who speaks over it drops the frame it waits for (Pipecat issue #5263), so the confirmation node never applied. A start is taken only after the caller answers the offer.

2026-10-29 · The free times to choose from are also a line of the code, said on entering the choose-time node, and the model waits for the choice: rewording the ranges, the model misstated where they ended.

2026-10-31 · The booking done is also a line of the code, said once the backend confirmed it, and the model waits for the caller: announcing it took a second model round of about 0.4 s, and that the booking exists is a fact the code holds.

2026-10-31 · The question for the name is also a line of the code, said once a time is chosen, and the model waits for the answer: asking it took a second model round. A name the caller already said goes with the availability check or the time choice (an optional `client_name`), which then propose at once and skip the question.

2026-10-31 · A weekday and a date that disagree are found by the code, not the model: the model passes the weekday and the day number as the caller said them to `check_availability`, and the code compares them with the calendar. When they disagree nothing is offered, and a which-day node, whose question the code says, waits for the caller to choose. In the evals the model booked one of the two days without asking, though its task told it to ask. The month is passed too: the date named is the next one from today with the caller's day number and month, never the model's date (a practice call asked about a past October day for "viernes veintisiete de diciembre").
