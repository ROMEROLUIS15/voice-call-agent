# ADR 0015: Browser practice entry for development

*   **Status:** Accepted
*   **Date:** 2026-10-26
*   **Amends:** 0004

## Context
Both entries of ADR 0004 need something outside the repository before a single call can be held: the phone line a Venezuelan number (manifest §10), the WhatsApp entry Meta's messaging limit or a test number with a public webhook. Meanwhile the prompt, the agent's tools and the pipeline's behaviour (turns, interruptions, latency per segment) need real conversations to be tuned, and the text evals (ADR 0010) cannot show how the agent sounds, how it handles being interrupted or what the speech-to-text makes of a real voice.

## Decision
A third entry, for development only: a call from a browser tab on the developer's own machine, over WebRTC (`call_transports/browser_webrtc/`). It runs the same conversation runner, pipeline, providers and call trace as the other entries; only the transport differs.

*   **Off unless enabled:** `BROWSER_PRACTICE_ENABLED=true`, refused at startup unless `ENVIRONMENT=development`, because the entry has no authentication.
*   **Local clients only:** an offer from any address other than a loopback one is refused (`403`).
*   **Its own page:** `/practice` serves a minimal page and script of this repository; Pipecat's prebuilt client is not used. The page gets a content security policy that allows only its own script and its request to the service; every other response keeps `default-src 'none'`.
*   **One offer and one answer:** the browser sends its offer once ICE gathering completes, so there is no candidate exchange afterwards. The service answers only offers with an audio section, ends the call if the browser does not connect within 20 s, and closes the peer once.
*   **A channel of its own** (`browser`): no caller or dialed number, identity never verified, like the phone line (INV-4); no telephony cost in the price table.

## Alternatives considered
*   **A US phone number on the phone-line entry.** Not chosen: a Twilio trial cannot point a number at the service's own webhook (only Twilio's templates), so it needs a paid account; the number has a monthly cost and every call from Venezuela is international for the caller; and it does not validate the Venezuelan route the product needs.
*   **The WhatsApp entry with a Meta test number.** Kept as the next step, not as the practice entry: it needs a separate Meta app and a public URL (a tunnel), and its media depends on the developer's network. It exercises the real WhatsApp entry, which the practice entry does not replace.
*   **Pipecat's development runner and prebuilt client.** Not chosen: the runner is a separate server, with its own routes, sessions and file endpoints, outside the service's hardening, settings and composition root; the prebuilt client speaks the runner's session protocol and is one more dependency.
*   **Daily or LiveKit rooms.** Not chosen: a hosted media service, an account and a dependency for a call that runs on one machine.

## Consequences
*   Easier: the whole engine can be heard and tuned today, at no telephony cost, with the same traces, error codes and cost estimates as a real call.
*   Harder: one more entry to keep, with its own negative security tests (`tests/integration/call_transports/browser_webrtc/`) and threat model entries (S13). Its latency is not the phone network's: the browser's audio is wideband, with echo cancellation, and reaches the service on the same machine, so acceptance measurements (constitution §5) still come from real calls.
*   A local tunnel that strips `X-Forwarded-For` would make remote clients look local (threat model R-09): the entry stays off whenever the development service is exposed.
