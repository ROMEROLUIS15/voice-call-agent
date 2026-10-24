# ADR 0014: One phone number shared by every business

*   **Status:** Accepted
*   **Date:** 2026-10-24

## Context
The phone line resolved the business by the dialed number, so every business needed its own number. The phone line uses Venezuelan numbers, and neither Twilio nor Telnyx sells them (manifest §10): each one takes a support request or a number provider delivering it over SIP, with paperwork and a monthly fee. The cost and the effort would grow with every business. WhatsApp already serves every business from one number: when routing does not decide, the caller names the business and the backend matches it (contract §4.1b).

## Decision
The phone line uses **one Venezuelan number shared by every business**.

*   The dialed number only has to be a line of the service; otherwise the backend answers `UNKNOWN_LINE` and the call ends with a fixed message.
*   The agent always asks which business the caller wants. The backend matches the name against the active businesses (up to 3 candidates to ask about when it is ambiguous), the caller confirms, and the business stays fixed for the call (INV-1). The language model asks and passes the name; it never decides the business (constitution §3).
*   The caller ID never picks or suggests a business: it can be spoofed, and a suggestion would reveal which businesses that number is a client of.

## Alternatives considered
*   **A number per business** (the previous rule). No question at the start of the call, but the cost and the paperwork grow with every business, and no provider sells Venezuelan numbers directly.
*   **The shared number plus optional numbers per business.** Not needed now; it would be a new decision if a business asks for its own number.
*   **Picking the business from the caller ID** (the business that has the caller as a client). Shorter calls for returning clients, but the caller ID can be spoofed and the choice reveals client–business associations. On WhatsApp it is acceptable because Meta verifies the number.
*   **A short business code dialed or said by the caller.** Robust to misheard names, but every business must publish it and callers must know it. It stays an option if business names prove unreliable on 8 kHz audio (manifest §10).

## Consequences
*   Easier: one number to obtain and pay for; adding a business needs no telephony change; both entries resolve the business the same way.
*   Harder: every phone-line call starts with a question; business names must be recognized on 8 kHz audio (measured in phase 0, golden case `unresolved-business-on-the-phone-line`); similar names need the candidates and the confirmation; the greeting is generic until the business is resolved; contract §4.1b serves the phone line too, and the backend keeps the service's lines instead of a line per business.
