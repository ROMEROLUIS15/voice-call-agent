# Voice Call Agent — context for the coding agent

## Non-negotiable rules

Summary only; the full, binding text is `docs/specs/constitution.md`.

*   **Language.** Everything in the repository is in English: identifiers, comments, docstrings, logs, errors, docs, commits. What the agent says to the caller (LLM prompts, spoken phrases) stays in Spanish, in resource files under `src/voice_call_agent/conversation_content/<locale>/`, never inline in logic.
*   **Balance between the agent and the code.** The model does the conversational work and proposes the action; the code validates only what will be written (the call's business, a real service and slot, the caller's confirmation of that exact proposal). It never scripts the conversation nor redoes what the model understands well (constitution §0).
*   **Proportion and course correction.** End to end first; observability, evals and controls grow with each feature as it needs them; the safety of writes and data never waits. If the implementation fails, the design is wrong or a better path exists: stop, say so with evidence and propose the alternative with its trade-off, even against an earlier decision; do not harden the same path. A rule that blocks without protecting anything, creates a risk or contradicts the code is reported, not applied in silence (constitution §17).
*   **Names.** Name things after what they do, not whom they talk to. Banned: `utils`, `helpers`, `common`, `misc`, `core`, `manager`, `handler`, `data`, bare `service.py` / `client.py`. "Cronix" appears only in `adapters/cronix_scheduling_api/` and the composition root; the domain depends on the `SchedulingBackend` and `BusinessResolver` protocols. The package is `voice_call_agent`.
*   **Typing and structure.** `mypy --strict` with zero errors; no `Any` without a justifying comment; Pydantic models across layers; files ≤ ~300 lines, functions ≤ ~50; dependencies injected from `service_composition.py`; no global singletons, no import-time side effects, nothing blocking the event loop.
*   **Secrets.** Only environment variables loaded as `SecretStr`; never in code, logs or errors. `.env` is git-ignored; `.env.example` documents every variable.
*   **Repository scope.** The repository describes only the product and its technical decisions. It never references third-party organizations, clients, employers, job opportunities or the personal motivations of its maintainers. External context, if any, stays outside the repository.
*   **Documentation.** Updated as part of every change, before every commit and every push: `README.md` and `docs/` (specs and ADRs in `docs/adr/NNNN-title-in-english.md`). A change without documentation impact says so explicitly in its summary ("no documentation changes because …"). Removed code takes its documentation with it. At the root, only `README.md` and `CLAUDE.md` are documentation.
*   **Security and tenancy per feature.** Negative security tests, the threat model and tenant isolation tests ship with the feature, not later. CORS stays closed; security headers on every response; the business comes only from the `CallSession` (constitution §15).
*   **Observability first.** Find a failure in the observability first (logs by error code, the call trace, Sentry); if it cannot show it, instrument it first (an error code, an attribute or a span, with its test), then fix it. Every feature ships with its trace data, its error codes in `observability/error_taxonomy.py` reported through `report_error`, and its golden case (`docs/evals/golden-dataset.md`). No change to the prompt, phrases, model, generation settings or tools without model evals against the baseline (constitution §16, ADR 0010 amended by 0013).
*   **Verification.** A task is not done until the checks below pass and the module's manifest is updated (SDD).

**Before any commit and any push**, the quality gate passes (constitution §11; `.pre-commit-config.yaml` is the only list of checks, ADR 0008):

```bash
uv run pre-commit run --all-files --hook-stage manual   # the same hooks CI runs
git status             # secrets review: no .env, token, key or credential file staged
```

Changes reach `main` only through a pull request whose required checks are green (ADR 0012); a maintainer approves the merge.

Once per clone: `uv run pre-commit install` (ruff and gitleaks then run on every commit).

And: **README and `docs/` (specs and ADRs) updated, or the summary says why not.**
And: **negative security tests and the threat model updated if the change touches an attack surface.**
And: **a changed snapshot is reviewed and regenerated (`uv run pytest tests/snapshots --snapshot-update`); a changed behaviour fingerprint needs the model evals and a new baseline (`uv run --env-file .env --group evals python -m evals.model_evals --write-baseline`) or, until the first baseline is measured with the booking prompt of phase 2, `--record-fingerprint` (ADR 0013).**

If a secret was ever tracked: `git rm --cached <file>` and rotate the secret.

## What this repository is

The **Cronix call agent**: a Python service (Pipecat + FastAPI) that answers calls over **WhatsApp** and over a **phone line (Twilio)** and books appointments in Cronix by talking, in real time (v1); checking, rescheduling and cancelling follow in v1.1. The Python package is agnostic (`voice_call_agent`); Cronix is one scheduling backend behind a port.

## Before writing code

Read, in this order, and follow them:
1. `docs/specs/constitution.md` — non-negotiable rules (law zero: the agent does the work, the code validates the write).
2. `docs/specs/call-module/manifest.md` — scope, architecture, invariants, latency, acceptance criteria and phases.
3. `docs/specs/cronix-phone-api-contract.md` — HTTP contract with Cronix.
4. `docs/adr/` — architecture decisions already taken.

No task is finished without updating the manifest if a contract, invariant or flow changed (SDD).

## Decisions taken (2026-10-18)

| Decision | Choice |
|---|---|
| Voice engine language | Python + Pipecat (self-hosted) |
| Repository | New, separate from Cronix. Cronix is a destination over HTTP. |
| First case | Booking in Cronix by phone, reusing its booking logic through a minimal HTTP contract |
| Entries | **Two**: WhatsApp call (Cronix's number, Cloud API Calling, WebRTC) and phone line (Twilio Media Streams). Same engine; the channel lives only in `call_transports/` and `call_session/`. |
| Voice architecture | Cascaded (STT → LLM → TTS), not speech-to-speech: better for auditable writes and tool calling. |
| Repository language and naming | English repository, Spanish caller-facing content in resource files; names by function, agnostic package, "Cronix" only in its adapter. |

## Verified facts that shape the design

*   **WhatsApp Cloud API Calling:** user-initiated calls are available in every country with the Cloud API and are free for the caller. Pipecat supports them with a WebRTC transport (subscribe the webhook to the `calls` field). **Risk:** Meta requires a messaging limit of ≥ 2,000 daily recipients (test accounts and numbers are exempt); the real number's limit is 250 (2026-10-20), so the WhatsApp entry is paused and the phone line (Twilio, Venezuelan numbers) is the main path (manifest §10).
*   **Cronix's WhatsApp number is shared by every business** (routing by `#slug`, session or the client's phone). A call has no slug: if the business cannot be resolved, the agent asks for it.
*   **Identity:** Meta verifies the number on WhatsApp; the phone line's caller ID can be spoofed → reading appointments, rescheduling or cancelling over Twilio requires a second factor, and the caller is greeted by name only on WhatsApp.
*   **Cronix's booking logic** creates the client if missing and checks conflicts atomically, but reports a conflict as free text; the contract's endpoint translates it to `SLOT_CONFLICT`.
*   **Supabase Edge Functions** do not work for the call in progress (duration limit, no persistent connection). They do work for the contract's short endpoints.
*   **Typical cascaded latency:** 600–1,200 ms to first audio; the project's target is ≤ 1.0 s p50.

## Status and next step

Current phase, status and next step: `docs/specs/call-module/manifest.md` §12.

Check current versions and APIs of Pipecat, Deepgram and Twilio in their documentation before writing code: this ecosystem changes every few weeks. The versions in use are pinned in `pyproject.toml` and recorded in manifest §7.
