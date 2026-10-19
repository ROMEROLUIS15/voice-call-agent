# Voice Call Agent — context for the coding agent

## Non-negotiable rules

Summary only; the full, binding text is `docs/specs/constitution.md`.

*   **Language.** Everything in the repository is in English: identifiers, comments, docstrings, logs, errors, docs, commits. What the agent says to the caller (LLM prompts, spoken phrases) stays in Spanish, in resource files under `src/voice_call_agent/conversation_content/<locale>/`, never inline in logic.
*   **Names.** Name things after what they do, not whom they talk to. Banned: `utils`, `helpers`, `common`, `misc`, `core`, `manager`, `handler`, `data`, bare `service.py` / `client.py`. "Cronix" appears only in `adapters/cronix_scheduling_api/` and the composition root; the domain depends on the `SchedulingBackend` and `BusinessResolver` protocols. The package is `voice_call_agent`.
*   **Typing and structure.** `mypy --strict` with zero errors; no `Any` without a justifying comment; Pydantic models across layers; files ≤ ~300 lines, functions ≤ ~50; dependencies injected from `service_composition.py`; no global singletons, no import-time side effects, nothing blocking the event loop.
*   **Secrets.** Only environment variables loaded as `SecretStr`; never in code, logs or errors. `.env` is git-ignored; `.env.example` documents every variable.
*   **Repository scope.** The repository describes only the product and its technical decisions. It never references third-party organizations, clients, employers, job opportunities or the personal motivations of its maintainers. External context, if any, stays outside the repository.
*   **Documentation.** Updated as part of every change, before every commit and every push: `README.md` and `docs/` (specs and ADRs in `docs/adr/NNNN-title-in-english.md`). A change without documentation impact says so explicitly in its summary ("no documentation changes because …"). Removed code takes its documentation with it. At the root, only `README.md` and `CLAUDE.md` are documentation.
*   **Security and tenancy per feature.** Negative security tests, the threat model and tenant isolation tests ship with the feature, not later. CORS stays closed; security headers on every response; the business comes only from the `CallSession` (constitution §15).
*   **Observability first.** Find a failure in the observability first (logs by error code, the call trace, Sentry); if it cannot show it, instrument it first (an error code, an attribute or a span, with its test), then fix it. Every feature ships with its trace data, its error codes in `observability/error_taxonomy.py` reported through `report_error`, and its golden case (`docs/evals/golden-dataset.md`). No change to the prompt, phrases, model, generation settings or tools without model evals against the baseline (constitution §16, ADR 0010).
*   **Verification.** A task is not done until the checks below pass and the module's manifest is updated (SDD).

**Before any commit and any push**, all of these must pass:

```bash
uv run pre-commit run --all-files --hook-stage manual   # the same hooks CI runs:
#   ruff check · ruff format --check · mypy --strict · pytest --cov (≥ 85 %)
#   bandit · pip-audit · gitleaks over the whole history
git status             # secrets review: no .env, token, key or credential file staged
```

Once per clone: `uv run pre-commit install` (ruff and gitleaks then run on every commit).

And: **README and `docs/` (specs and ADRs) updated, or the summary says why not.**
And: **negative security tests and the threat model updated if the change touches an attack surface.**
And: **a changed snapshot is reviewed and regenerated (`uv run pytest tests/snapshots --snapshot-update`); a changed behaviour fingerprint needs the model evals and a new baseline (`uv run --env-file .env --group evals python -m evals.model_evals --write-baseline`).**

If a secret was ever tracked: `git rm --cached <file>` and rotate the secret.

## What this repository is

The **Cronix call agent**: a Python service (Pipecat + FastAPI) that answers calls over **WhatsApp** and over a **phone line (Twilio)** and books, checks, reschedules and cancels appointments in Cronix by talking, in real time. The Python package is agnostic (`voice_call_agent`); Cronix is one scheduling backend behind a port.

## Before writing code

Read, in this order, and follow them:
1. `docs/specs/constitution.md` — non-negotiable rules (law zero: the model proposes, the code decides).
2. `docs/specs/call-module/manifest.md` — scope, architecture, invariants, latency, acceptance criteria and phases.
3. `docs/specs/cronix-phone-api-contract.md` — HTTP contract with Cronix.
4. `docs/adr/` — architecture decisions already taken.

No task is finished without updating the manifest if a contract, invariant or flow changed (SDD).

## Decisions taken (2026-10-18)

| Decision | Choice |
|---|---|
| Voice engine language | Python + Pipecat (self-hosted) |
| Repository | New, separate from Cronix. Cronix is a destination over HTTP. |
| First case | Booking in Cronix by phone, reusing its RPCs (`fn_book_appointment_wa`, etc.) |
| Entries | **Two**: WhatsApp call (Cronix's number, Cloud API Calling, WebRTC) and phone line (Twilio Media Streams). Same engine; the channel lives only in `call_transports/` and `call_session/`. |
| Voice architecture | Cascaded (STT → LLM → TTS), not speech-to-speech: better for auditable writes and tool calling. |
| Repository language and naming | English repository, Spanish caller-facing content in resource files; names by function, agnostic package, "Cronix" only in its adapter. |

## Verified facts that shape the design

*   **WhatsApp Cloud API Calling:** user-initiated calls are available in every country with the Cloud API and are free for the caller. Pipecat supports them with a WebRTC transport (subscribe the webhook to the `calls` field). **Risk:** Meta requires a messaging limit of ≥ 2,000 daily recipients (test accounts and numbers are exempt); Cronix does not reach it today. That is why the Twilio entry exists as a fallback.
*   **Cronix's WhatsApp number is shared by every business** (routing by `#slug`, session or the client's phone in `supabase/functions/process-whatsapp/tenant-routing.ts`). A call has no slug: if the business cannot be resolved, the agent asks for it.
*   **Identity:** Meta verifies the number on WhatsApp; the phone line's caller ID can be spoofed → rescheduling or cancelling over Twilio requires a second factor.
*   **`fn_book_appointment_wa`** creates the client if missing and checks conflicts atomically, but returns the conflict as free text ("Slot no disponible."); the new endpoint translates it to `SLOT_CONFLICT`.
*   **Supabase Edge Functions** do not work for the call in progress (duration limit, no persistent connection). They do work for the contract's short endpoints.
*   **Typical cascaded latency:** 600–1,200 ms to first audio; the project's target is ≤ 1.0 s p50.

## Next step: phase 0 (technical test, without Cronix)

Current status: `docs/specs/call-module/manifest.md` §12.

1. Repository skeleton: `pyproject.toml` (uv), FastAPI, Pipecat, pytest, strict mypy, ruff; module structure of manifest §3.
2. Twilio entry: test number, webhook → TwiML `<Connect><Stream>` → Pipecat pipeline with Deepgram (STT), an LLM and TTS, talking in Spanish.
3. WhatsApp entry: enable "Calls" on the number (or use a Meta test number), subscribe `calls`, same pipeline.
4. Measure latency per segment and per channel; record cost per minute.
5. Record in the manifest which LLM and TTS are chosen and why, and whether Cronix's real number qualifies for calls.

Check current versions and APIs of Pipecat, Deepgram and Twilio in their documentation before writing code: this ecosystem changes every few weeks. The versions in use are pinned in `pyproject.toml` and recorded in manifest §7.
