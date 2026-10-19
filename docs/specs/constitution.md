# 📜 Constitution of the Voice Call Agent

Non-negotiable rules for all code in this repository. It inherits the principles of the Cronix constitution (`cronix/docs/specs/constitution.md`) and adapts them to a real-time Python voice service. Any AI agent that generates or refactors code here MUST follow them.

## 0. Law zero: the model proposes, the code decides

*   The LLM **never** decides what is written to the scheduling backend (Cronix). It interprets what the caller said and proposes an action; the code validates it, confirms it with the caller and executes it.
*   Every write (book, reschedule, cancel) goes through the **two-turn confirmation** (§4) and through the Cronix HTTP contract (`cronix-phone-api-contract.md`). The agent has no database credentials.
*   No written value may come from the model alone: date, time, service and target appointment must trace back to something the caller said **and** to something the backend returned (catalog, availability, appointments).

## 1. Structural quality

*   **SOLID and layer separation**, as in Cronix: call transports, speech pipeline, dialog state, intent understanding, the scheduling backend adapter and observability are independent modules, testable on their own. Orchestration coordinates; it does not absorb the logic of each layer.
*   **Hard limits:** file ≤ ~300 lines, function ≤ ~50 lines. When a limit is near, split by concept.
*   **No patches that can grow.** If a fix can expand to more cases, it is built as its own component, with its contract and tests.
*   **Strict typing:** `mypy --strict` in CI. Data models with Pydantic; no untyped `dict` crossing layers.

## 2. Separation of responsibilities between services

*   **This repository** contains only the voice engine and the state of the call. Appointment business logic lives in Cronix and is consumed over HTTP.
*   **Cronix** exposes a minimal, explicit surface for the phone channel (Edge Function `phone-agent-api`). The agent does not reuse the WhatsApp Edge Function nor the dashboard assistant's: their authentication and assumptions differ.
*   The call in progress does **not** run on Supabase Edge Functions (duration limit and no persistent connection). It runs on its own server with a persistent WebSocket.

## 3. Multi-tenant

*   The business is resolved by **the scheduling backend**, never by the LLM: on the phone line by the dialed number (`voice_lines`); on WhatsApp by the existing routing (session or the client's phone) and, when that is not enough, by the name the caller says, matched and confirmed by the backend.
*   If it cannot be resolved safely, **the tenant is not guessed**: on the phone line the call ends with a fixed message; on WhatsApp the agent asks.
*   The call's channel (WhatsApp or Twilio) exists only in `call_transports/` and `call_session/`. The rest of the code works with a neutral `CallSession`.
*   Every request to the backend carries the `business_id` resolved at the start of the call; the backend validates it again on its side (defense in depth).

## 4. Phone-specific security

*   **On WhatsApp calls**, Meta verifies the caller's number: it is treated like a WhatsApp message.
*   **On the phone line, the caller ID can be spoofed.** Therefore:
    - **Booking** with the caller ID is acceptable (the worst case is an unwanted, reversible appointment).
    - **Rescheduling or cancelling** an existing appointment requires a second factor: the caller confirms the name the appointment was booked under and its date, **or** a code sent by SMS to the registered number. Without it, a message is taken for the business instead of executing.
*   Personal data (name, phone) is redacted in logs and traces. Recordings, if enabled, are encrypted and have an explicit retention policy.
*   Recording notice at the start of the call when recording is enabled.

## 5. Latency is a requirement, not a wish

*   A phase is accepted only if it meets its latency budget measured with real calls over the phone network (not locally): see `call-module/manifest.md` §6.
*   Each segment (end of speech → final transcript → first token → first audio) is measured and published per call.

## 6. Resilience

*   If the backend does not answer within the timeout, the agent **does not invent** a result: it says it could not complete the action and offers to take a message.
*   Configurable provider fallback (STT, LLM, TTS), as in Cronix. A provider failure degrades the call; it does not cut it silently.
*   Every write request to the backend carries an idempotency key (see contract). Retrying never duplicates an appointment.

## 7. Testing and quality

*   **Pyramid:** unit tests (pytest) for intent understanding, state and the backend client; integration against a local Cronix; end-to-end **simulated calls** in CI with recorded audio and conversation scripts.
*   **Evals:** multi-turn reference conversations (as in Cronix) that block the merge if the rate of correct appointments drops or p95 latency rises.
*   A test is worth something only if it fails when what it claims to cover breaks: guard tests are verified by injecting the defect. A test that hangs instead of failing when its guard breaks does not count: bound every wait.
*   Tests mirror `src/`: `tests/unit/`, `tests/integration/`, and `tests/architecture/` for rules checked on the source itself (channel isolation, naming, dependency direction).

## 8. Documentation (SDD)

Documentation is updated as part of the change, not afterwards. **Before every commit and every push**, without being asked:

*   **`README.md`** is updated if anything it describes changed: installation, usage, architecture, status or environment variables.
*   **Public documentation in `docs/`** reflects every addition, removal or behaviour change: the specs (`docs/specs/`) and the architecture decisions (`docs/adr/`). No task is done until the manifest of the module it touched is updated.
*   If a change does not affect documentation, the change summary says so explicitly ("no documentation changes because …"); it is never omitted silently.
*   Removing code or a feature removes its documentation: documentation never describes something that no longer exists.
*   Every trade-off records its context, the alternatives considered and its consequences: as an ADR in `docs/adr/NNNN-title-in-english.md` (numbered, see `docs/adr/README.md`) if it is cross-cutting, in the module's manifest if it is local.
*   **Where documentation lives:** additional public documentation inside `docs/`; architecture decisions in `docs/adr/`; at the repository root only `README.md` and `CLAUDE.md` as documentation (tool configuration files such as `pyproject.toml` stay where their tools expect them).

## 9. Language policy

*   **Everything in the repository is in English:** identifiers, comments, docstrings, log and error messages, `README.md`, `CLAUDE.md`, the specs in `docs/specs/`, commit messages and pull request descriptions.
*   **What the agent says to the caller is product content, in the caller's language** (Spanish in v1): LLM prompts and spoken phrases. It lives in resource files under `src/voice_call_agent/conversation_content/<locale>/` (`system_prompt.md`, `phrases.toml`) and is loaded once at startup; it is never written inline in logic.

## 10. Naming convention

*   Every package, module, class and function is named after **what it does**, not after whom it talks to or which project it belongs to.
*   **Banned names** for packages and modules: `utils`, `helpers`, `common`, `misc`, `core`, `manager`, `handler`, `data`, and a bare `service.py` or `client.py`. The words `util`, `helper`, `manager`, `handler` and `misc` are banned inside class and function names too.
*   Inside `adapters/`, a package is named after the external system it adapts (`cronix_scheduling_api`, `deepgram_speech`). Call transports are named after the protocol they implement (`twilio_media_streams`, `whatsapp_calling`). Everywhere else, names say what the code does.
*   **"Cronix" appears only in `adapters/cronix_scheduling_api/`** and in the composition root that wires it. The domain, the speech pipeline and the dialog never import anything with "cronix" in its name: they depend on protocols (`SchedulingBackend`, `BusinessResolver`). Only adapters and the composition root import adapters.
*   The Python package is agnostic: `voice_call_agent`.
*   Enforced by `tests/architecture/test_naming_rules.py`.

## 11. Python standards

*   **Layout and tooling:** `src` layout; `uv` with a committed `uv.lock`; Pipecat and the provider SDKs pinned to exact versions in `pyproject.toml`.
*   **Lint and types:** `ruff check`, `ruff format`, `mypy --strict` with zero errors. `Any` only when justified in a comment next to it; `# type: ignore` only with its error code and a reason.
*   **Models:** Pydantic for data crossing layers. Bundles of dependencies (factories) may be frozen dataclasses.
*   **Dependencies:** SOLID; components depend on protocols (DIP) and receive their dependencies explicitly from the composition root (`service_composition.py`). No global singletons. No import-time side effects: no I/O, network or logging configuration when a module is imported.
*   **Async:** nothing blocks the event loop, where other calls are streaming audio. CPU-heavy work or file I/O goes to `asyncio.to_thread`; heavy imports happen at startup.
*   **Errors:** each package defines its own domain exceptions. Expected business outcomes (slot taken, identity mismatch) are typed results, not exceptions.
*   **Logging:** structured logging with loguru, configured once by the entrypoint (JSON by default). No `print`; the only exception is the program output of a command-line tool.
*   **Before every commit** these must pass: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest`, the secrets review of §12 and the documentation review of §8. The same review applies before every push.

## 12. Secrets handling

*   Secrets come **only from environment variables**, loaded with pydantic-settings as `SecretStr`. Never in code, logs, error messages, URLs or committed files.
*   `.env` is git-ignored. `.env.example` lists **every** variable, documented, with empty or example values.
*   Settings validation errors never echo their input (`hide_input_in_errors=True`); loguru runs with `diagnose=False` so tracebacks never print variable values. Production logs run at `INFO` or higher: Pipecat logs conversation content at `DEBUG`.
*   **Before every commit:** check `git status` and the staged files for `.env` files, tokens, keys or credential files. If one was tracked, remove it from the index (`git rm --cached`) and rotate the secret.
*   Webhook signatures are validated in constant time before the body is parsed: Meta `X-Hub-Signature-256` over the raw body, Twilio `X-Twilio-Signature` over the exact public URL. A public WebSocket requires an admission token issued by a signed webhook.
*   Personal data (phones, names) is redacted in logs and traces (§4).

## 13. Scalability

*   **No global state:** the state of each call lives in its `CallSession` and its pipeline. Per-instance state is limited to call slots (`CallSupervisor`). Any instance can serve any webhook: tokens are stateless and nothing a later request needs is kept in memory. Several instances must be able to run in parallel.
*   **Concurrency limit** per instance, configurable (`MAX_CONCURRENT_CALLS`). Beyond it, calls are rejected cleanly (Twilio `<Reject reason="busy">`, WhatsApp `reject`) and readiness reports not-ready.
*   **Graceful shutdown:** on the first shutdown signal the instance stops accepting calls, waits for the calls in progress up to `SHUTDOWN_GRACE_SECONDS` and only then cuts them. The orchestrator's termination grace period must be longer.
*   **Explicit timeouts on every network call** the code makes or configures. When a library owns a network call and exposes no timeout, its default is recorded in the manifest as a known limitation.

## 14. Repository scope

*   The repository describes only the product and its technical decisions. It never references third-party organizations, clients, employers, job opportunities or the personal motivations of its maintainers. External context, if any, stays outside the repository.
*   This applies to every file, comment, test, commit message and pull request description.
*   Technology providers the product integrates with (Meta, Twilio, Deepgram, language model providers) are technical dependencies, not external context.
