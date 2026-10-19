# ADR 0002: Python and Pipecat for the voice engine

*   **Status:** Accepted
*   **Date:** 2026-10-18

## Context
A real-time voice agent needs streaming orchestration of speech-to-text, a language model and text-to-speech, turn detection, interruption handling, latency metrics, and telephony transports for both a phone line and WhatsApp Calling. Cronix itself is written in TypeScript.

## Decision
Python with Pipecat, self-hosted. Pipecat and the provider SDKs are pinned to exact versions (`pipecat-ai==1.12.0`, see manifest §7) and `uv.lock` is committed.

## Alternatives considered
*   **TypeScript, the same language as Cronix.** Not chosen: Pipecat's transports for Twilio Media Streams and WhatsApp WebRTC, its Flux turn-detection integration and its latency observer are in Python.
*   **A hosted voice-agent platform.** Not chosen: less control over the pipeline, the write path and the per-segment measurement this project must own.
*   **An engine written from scratch.** Not chosen: a large amount of undifferentiated work (audio framing, resampling, interruptions) before any product value.

## Consequences
*   Easier: native transports for both entries, built-in turn detection and latency breakdowns.
*   Harder: Pipecat changes every few weeks (1.3 deprecated `PipelineTask`); mitigated by exact pins, a committed lock file, checking the documentation before upgrading, and tests over the integration points. Two languages across Cronix and the agent.
