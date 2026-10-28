# ADR 0017: Practice lines and conversation transcripts in development

*   **Status:** Accepted
*   **Date:** 2026-10-27
*   **Amends:** 0015

## Context
The first practice calls with a person's voice (2026-10-27) showed two gaps in the practice entry of ADR 0015:

*   **Every practice call reached the same business.** A practice call has no dialed number, so the practice schedule gives it its default business, the barbershop. The product serves any business, and the model evals already book at a barbershop, a dental clinic and a spa; by voice, only one could be heard.
*   **What was said could not be seen.** In one practice call the agent repeated itself and was imprecise when the caller changed service, but the call trace holds no conversation content (constitution §4 and §16): it showed the booking that was written and the latency of each turn, not what the caller asked nor what the agent answered. Without that, a fix would be a guess (constitution §16: instrument first).

## Decision
This ADR changes only what follows; the rest of ADR 0015 holds.

*   **A practice call dials a practice line.** Each practice business lists a fictitious number (`practice_businesses.toml`, in the 555-0100 to 555-0199 range reserved for fiction). The practice page lists them (`GET /practice/lines`) and its offer carries the one chosen; the backend resolves the business from it exactly as from a phone-line call's dialed number (constitution §3), and the practice call keeps no caller number. Only a listed line is accepted (`400`, `REQUEST_INVALID` otherwise). Without a practice schedule there are no lines and the call dials none, as before.
*   **Conversation transcripts, in development only.** With `CONVERSATION_TRANSCRIPTS_DIR`, refused at startup unless `ENVIRONMENT=development`, each call leaves a text file named after the call: the trace's call, business, start and outcome; the prompt its model received; and the conversation as the model saw it, with the caller's turns as the speech-to-text heard them, the agent's lines as far as they were spoken and each tool call with its result. It is written once the call ends, off the event loop, and a failure is reported (`TRANSCRIPT_WRITE_FAILED`) without touching the call. It is never exported: error tracking and the call trace stay without conversation content.

## Alternatives considered
*   **Choose the business by id on the practice page.** Not chosen: the business would come from the client instead of from the backend's resolution of the call (constitution §3, §15), a path no real entry has.
*   **The agent asks which business, as on WhatsApp's shared number.** Not chosen now: the phone line, the main path (manifest §10), identifies the business before the greeting, and resolving a spoken business name is the WhatsApp entry's, paused.
*   **Read the conversation from `DEBUG` logs.** Not chosen: Pipecat's debug output mixes every frame and provider detail, lives only in the terminal that ran the service, and `DEBUG` must never reach production (constitution §12). A transcript is one file per call, joinable with its trace by the call id.
*   **Put the conversation in the call trace.** Not chosen: the trace is exported to error tracking and kept in production; conversation content must not be (constitution §16).
*   **Record frames with timestamps instead of the model's context.** Not chosen now: the context is what the model reasoned from, which is what a wrong answer needs, and it already holds tool calls and results in order. Timestamps per turn are in the call trace.

## Consequences
*   Easier: every practice business can be called by voice, through the same resolution as the phone line; and a practice call can be read back line by line, so the next fix starts from evidence.
*   Harder: a transcript keeps what the caller said, including names, unredacted. Mitigated by being off by default, refused outside development, written under `var/` (ignored by git) and never exported; it is meant for calls by the developer or testers who know it is kept (threat model T-44). The practice page has one more route, which lists only fictitious numbers.
*   The behaviour fingerprint leaves the practice numbers out: a number decides which business a call reaches, never what its model is told.
