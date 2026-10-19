# ADR 0001: Separate service from the scheduling backend

*   **Status:** Accepted
*   **Date:** 2026-10-18

## Context
A call in progress needs a persistent connection for minutes (a WebSocket for the phone line, WebRTC for WhatsApp) and continuous real-time audio. Cronix runs its server logic on Supabase Edge Functions, which have a duration limit and no persistent connection. Cronix owns the appointment logic: booking, conflicts, notifications and reminders.

## Decision
The voice agent is its own repository and its own service (Python, self-hosted server). It consumes Cronix over a minimal, HMAC-signed HTTP contract (`phone-agent-api`, see `docs/specs/cronix-phone-api-contract.md`). The agent has no database credentials.

## Alternatives considered
*   **Inside Cronix, as Edge Functions.** Rejected: the duration limit and the lack of persistent connections rule out a live call.
*   **Inside the Cronix repository, as another service.** Rejected: a different language, runtime and deployment, and coupled release cycles.

## Consequences
*   Easier: independent deployment and scaling; a narrow, auditable write surface; Cronix keeps one implementation of the appointment rules.
*   Harder: the contract lives in two repositories (it changes first in Cronix's manifest), and every read is a network hop, budgeted in manifest §6 (≤ 300 ms p50).
