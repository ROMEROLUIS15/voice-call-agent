# ADR 0005: English repository with localized caller content

*   **Status:** Accepted
*   **Date:** 2026-10-18

## Context
The callers speak Spanish, while the code, its libraries and its tooling are in English. Mixing languages inside the code makes it inconsistent, and writing caller-facing text inline in the logic makes it hard to review and to localize.

## Decision
Everything in the repository is in English: identifiers, comments, logs, errors, documentation and commits. What the agent says to the caller (the LLM prompt and spoken phrases) is product content in the caller's language, stored per locale in `src/voice_call_agent/conversation_content/<locale>/` and loaded at startup. Constitution §9.

## Alternatives considered
*   **A Spanish repository.** Not chosen: inconsistent with the libraries and tooling, and a narrower audience for the code.
*   **Caller text inline in the code.** Not chosen: it mixes product content with logic and blocks localization.

## Consequences
*   Easier: consistent code and documentation; supporting a new language means adding a locale folder (phase 6).
*   Harder: caller-facing content needs its own review in its own language.
