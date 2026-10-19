# ADR 0004: Two call entries over one engine

*   **Status:** Accepted
*   **Date:** 2026-10-18

## Context
WhatsApp Cloud API Calling lets clients call the Cronix number for free, but Meta requires a messaging limit of at least 2,000 daily recipients (test numbers are exempt), and Cronix does not reach it today. Traditional phone calls (PSTN) must be supported as well.

## Decision
Two entries over one speech engine: WhatsApp Calling (WebRTC) and a phone line through Twilio Media Streams. The channel exists only in `call_transports/` and `call_session/`; from the pipeline inwards there is only a channel-neutral `CallSession` (INV-8, enforced by an architecture test).

## Alternatives considered
*   **WhatsApp only.** Not chosen: the product would depend on Meta's requirement being met.
*   **Phone line only.** Not chosen: clients would lose free calls to the number they already use.

## Consequences
*   Easier: Meta's requirement stops being a blocker; traditional phone calls are supported.
*   Harder: two adapters, per-channel tests and per-channel latency; identity differs by channel (verified on WhatsApp, spoofable caller ID on the phone line, INV-4).
