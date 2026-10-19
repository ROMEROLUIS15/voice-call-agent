# ADR 0003: Cascaded speech architecture (STT → LLM → TTS)

*   **Status:** Accepted
*   **Date:** 2026-10-18

## Context
The agent writes to a system of record: it books, reschedules and cancels appointments. Every write must be traceable to what the caller said and to what the backend returned (constitution §0), guarded by a two-turn confirmation, and executed through tool calls.

## Decision
A cascaded pipeline: speech-to-text, then a text language model, then text-to-speech.

## Alternatives considered
*   **Speech-to-speech models.** Not chosen: they can lower latency and sound more natural, but text is no longer the source of truth of each turn, which makes per-turn guards, audits and evals harder, and tool calling less controllable.

## Consequences
*   Easier: every turn has a transcript and a text response to guard, log, evaluate and replay; each provider can be swapped on its own.
*   Harder: latency adds up across segments (typically 600–1,200 ms to first audio). Mitigated by streaming at every stage, Flux's built-in turn detection, and a per-segment budget measured on real calls (manifest §6).
