# 📜 Constitution of the Voice Call Agent

Non-negotiable rules for all code in this repository, a real-time Python voice service. Any AI agent that generates or refactors code here MUST follow them.

## 0. Law zero: Pipecat structures the conversation, the model talks, the code owns facts and writes

*   **Pipecat's documented patterns come first.** The conversation is a Pipecat Flows graph: each node focuses the model on one task with only the functions it needs ("monolithic prompts with many tools lead to hallucinations and lower accuracy", Pipecat). Pipecat's built-ins (Flows, Evals, observers, turn and mute strategies, tracing) are used before any code of our own; own code exists only for a gap Pipecat leaves, and says at the code which gap it fills (ADR 0019).
*   **The model understands and phrases.** Within a node it converses, asks for what is missing and calls the node's functions with what the caller said. No rule in code classifies the caller's words.
*   **The code owns the facts, the transitions and the writes.** It states the facts the model gets wrong when it works them out (dates, weekdays, the summary of what will be written); a node's transition follows its function's result; and before anything is written it validates, and only that: the business is the call's (`CallSession`), the service and the time slot are real (returned by the scheduling backend), and the caller confirmed this exact proposal after hearing it read back.
*   Every write goes through that validation and through the scheduling backend's HTTP contract; the agent has no database credentials. If the backend does not confirm a write, the agent says so and confirms nothing.

## 1. Structural quality

*   **SOLID and layer separation:** call transports, speech pipeline, the agent's tools, write guards, the scheduling backend adapter and observability are independent modules, testable on their own. Orchestration coordinates; it does not absorb the logic of each layer.
*   **Hard limits:** file ≤ ~300 lines, function ≤ ~50 lines. When a limit is near, split by concept.
*   **No patches that grow.** If a fix would have to grow case by case, stop and question the approach before building anything (§17): the model may be the one that should handle it, or the design may be wrong.
*   **Strict typing:** `mypy --strict` in CI. Data models with Pydantic; no untyped `dict` crossing layers.

## 2. Separation of responsibilities between services

*   **This repository** contains only the voice engine and the state of the call. Appointment business logic lives in Cronix and is consumed over HTTP.
*   **Cronix** exposes a minimal, explicit surface for the phone channel (Edge Function `phone-agent-api`). The agent does not reuse the WhatsApp Edge Function nor the dashboard assistant's: their authentication and assumptions differ.
*   The call in progress does **not** run on Supabase Edge Functions (duration limit and no persistent connection). It runs on its own server with a persistent WebSocket.

## 3. Multi-tenant

*   The business is resolved by **the scheduling backend**, never by the LLM: on the phone line by the dialed number; on WhatsApp by the existing routing (session or the client's phone) and, when that is not enough, by the name the caller says, matched and confirmed by the backend.
*   If it cannot be resolved safely, **the tenant is not guessed**: on the phone line the call ends with a fixed message; on WhatsApp the agent asks.
*   The call's channel (WhatsApp or Twilio) exists only in `call_transports/` and `call_session/`. The rest of the code works with a neutral `CallSession`.
*   Every request to the backend carries the `business_id` resolved at the start of the call; the backend validates it again on its side (defense in depth).

## 4. Phone-specific security

*   **On WhatsApp calls**, Meta verifies the caller's number: it is treated like a WhatsApp message.
*   **On the phone line, the caller ID can be spoofed.** Therefore:
    - **Booking** with the caller ID is acceptable (the worst case is an unwanted, reversible appointment).
    - **Rescheduling or cancelling** an existing appointment requires a second factor: the caller confirms the name the appointment was booked under and its date, **or** a code sent by SMS to the registered number. Without it, a message is taken for the business instead of executing.
    - **Reading** the caller's appointments requires the same second factor, and the agent greets the caller by name only when the identity is verified: a spoofed caller ID must not reveal whose number it is nor their appointments.
*   Personal data (name, phone) is redacted in logs and traces. Recordings, if enabled, are encrypted and have an explicit retention policy. What callers say is kept only by the development transcripts (ADR 0017), refused in production and never exported.
*   Recording notice at the start of the call when recording is enabled.

## 5. Latency is a requirement, not a wish

*   A phase is accepted only if it meets its latency budget measured with real calls over the phone network (not locally): see `call-module/manifest.md` §6.
*   Each segment (end of speech → final transcript → first token → first audio) is measured and published per call.

## 6. Resilience

*   If the backend does not answer within the timeout, the agent **does not invent** a result: it says it could not complete the action, confirms nothing and suggests calling back or writing over WhatsApp. A message for the business is taken only while the backend answers, since the backend is where it is stored.
*   **From phase 4**, configurable provider fallback (STT, LLM, TTS): a provider failure degrades the call; it does not cut it silently. Until then, a provider failure is reported with its error code (§16).
*   Every write request to the backend carries an idempotency key (see contract). Retrying never duplicates an appointment.

## 7. Testing and quality

*   **Pyramid:** unit tests (pytest) for the agent's tools, the write guards and the backend adapter; integration against a local Cronix; end-to-end **simulated calls** in CI with recorded audio and conversation scripts.
*   **Evals:** one golden dataset of multi-turn conversations (`docs/evals/golden-dataset.md`, ADR 0010) at two levels: reference conversations through the real conversation runner with scripted providers, on every change; and model evals with the real language model, task metrics and a judge model against a baseline. A measure that drops beyond its margin (0 for security; for quality, 0.05 or the spread measured between runs of the unchanged agent when wider, ADR 0016) fails the evals check, and a pull request is not merged with a failing check.
*   A test is worth something only if it fails when what it claims to cover breaks: guard tests are verified by injecting the defect. A test that hangs instead of failing when its guard breaks does not count: bound every wait.
*   Tests mirror `src/`: `tests/unit/`, `tests/integration/`, and `tests/architecture/` for rules checked on the source itself (channel isolation, naming, dependency direction, error handling, file contents); `tests/evals/` for the golden dataset and `tests/snapshots/` for the prompt, phrases, model configuration and port schemas.

## 8. Documentation (SDD)

Documentation is updated as part of the change, not afterwards. **Before every commit and every push**, without being asked:

*   **`README.md`** is updated if anything it describes changed: installation, usage, architecture, status or environment variables.
*   **Public documentation in `docs/`** reflects every addition, removal or behaviour change: the specs (`docs/specs/`) and the architecture decisions (`docs/adr/`). No task is done until the manifest of the module it touched is updated. The manifest describes the current state, not its history: what changed, when and why lives in the pull request and in git.
*   If a change does not affect documentation, the change summary says so explicitly ("no documentation changes because …"); it is never omitted silently.
*   Removing code or a feature removes its documentation: documentation never describes something that no longer exists.
*   Every trade-off records its context, the alternatives considered and its consequences: as an ADR in `docs/adr/NNNN-title-in-english.md` (numbered, see `docs/adr/README.md`) if it is cross-cutting, in the module's manifest if it is local.
*   **ADRs keep their history.** Before it is published (it reaches the default branch of the public repository), an ADR is edited freely. Once published, a change to part of its decision is made in the ADR itself, which gains a dated entry in its `Changes` section saying what changed, why, and where the new decision is recorded; editorial corrections go to its `Revisions` section. A different decision takes a new ADR that says `Supersedes NNNN`, and the earlier one becomes `Superseded by NNNN`. ADRs that already say `Amends NNNN` keep that history.
*   **Where documentation lives:** additional public documentation inside `docs/`; architecture decisions in `docs/adr/`; at the repository root only `README.md` and `CLAUDE.md` as documentation (tool configuration files such as `pyproject.toml` stay where their tools expect them).

## 9. Language policy

*   **Everything in the repository is in English:** identifiers, comments, docstrings, log and error messages, `README.md`, `CLAUDE.md`, the specs in `docs/specs/`, commit messages and pull request descriptions.
*   **What the agent says to the caller is product content, in the caller's language** (Spanish in v1): LLM prompts and spoken phrases. It lives in resource files under `src/voice_call_agent/conversation_content/<locale>/` (`system_prompt.md`, `phrases.toml`) and is loaded once at startup; it is never written inline in logic.

## 10. Naming convention

*   Every package, module, class and function is named after **what it does**, not after whom it talks to or which project it belongs to.
*   **Banned names** for packages and modules: `utils`, `helpers`, `common`, `misc`, `core`, `manager`, `handler`, `data`, and a bare `service.py` or `client.py`. The words `util`, `helper`, `manager`, `handler` and `misc` are banned inside class and function names too.
*   Inside `adapters/`, a package is named after the external system it adapts (`cronix_scheduling_api`, `deepgram_speech`). Call transports are named after the protocol they implement (`twilio_media_streams`, `whatsapp_calling`). Everywhere else, names say what the code does.
*   **"Cronix" appears only in `adapters/cronix_scheduling_api/`** and in the composition root that wires it. The domain, the speech pipeline and the agent's tools never import anything with "cronix" in its name: they depend on protocols (`SchedulingBackend`, `BusinessResolver`). Only adapters and the composition root import adapters.
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
*   **Quality gate.** Before every commit and every push, `uv run pre-commit run --all-files --hook-stage manual` passes, together with the secrets review of §12 and the documentation review of §8. `.pre-commit-config.yaml` is the only list of checks (ADR 0008): this constitution, `CLAUDE.md` and `README.md` point to it instead of copying it.
*   **Pull requests.** Changes reach `main` only through a pull request. CI's jobs are required checks, and the branch protection applies to administrators too (ADR 0012). A maintainer approves each merge.

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
*   **Nothing from test or practice calls enters the repository:** no words a caller said, names, dates they asked for, nor quotes of the agent, in code, tests, cases, documents or commit messages. A failure is described by the behaviour it shows, and its case uses invented data.

## 15. Security and tenancy are built per feature

*   No feature is done without, in the same change: its **security tests, positive and negative** (missing, invalid or altered signatures, repeated events, oversized input, floods), its **impact on the threat model** (`docs/security/threat-model.md`), and, if it touches data, its **tenant isolation tested** (a call of business A never reaches business B).
*   **The business comes only from the `CallSession`** resolved at the start of the call: never from what the caller says nor from what the LLM proposes. Requests to the scheduling backend carry `call_sid`, never `business_id` (contract §4).
*   If this service ever stores data of its own, every table is born with a tenant column, its index and isolation tests in the same change. On the scheduling backend's side, its own repository's rules apply (contract §8).
*   **HTTP surface:** security headers on every response (ADR 0007); no `Server` header; **CORS closed** by default, opened only by configuration to explicit origins, never `*`; trusted hosts by configuration; `X-Forwarded-*` trusted only from configured proxies; request body size limited; no interactive API documentation in production; error responses never reveal traces, internal paths, input values or settings.
*   **Webhooks:** signatures validated in constant time before parsing; replays rejected by event id and, when the provider allows it, by age; rate limits per client address and route. Every failure path fails closed.
*   **Checks:** the security checks run with lint, types and tests, the same hooks locally and in CI (§11, ADR 0008); every CI job is a required check of `main` (ADR 0012).

## 16. Observability first

*   **A failure is looked for in the observability first**: the logs by error code, the call trace, error tracking. If they cannot show it, the first change instruments it (an error code, an attribute or a span, with its test), and only then is it fixed.
*   **Every error has a code and a kind** in `observability/error_taxonomy.py`, real failure or expected outcome, and is reported with `report_error`: structured log, `voice.error` metric, an issue only for real failures, and the trace of the call. No handler silences an error (`tests/architecture/test_error_handling.py`).
*   **Every feature ships with** what it adds to the call trace, its error codes, and its case in the golden dataset; a reference conversation when it changes how the call flows.
*   **No change to the prompt, the phrases, the model, its generation settings or the tools lands without model evals against the baseline** (ADR 0010, amended by ADR 0013; enforced by the behaviour fingerprint). The first baseline is measured with the booking prompt of phase 2; until then the fingerprint records the inputs unmeasured. No behaviour change without a golden case that shows it; every production failure that is fixed adds its case. A change that adds or changes cases may store its baseline although a quality measure drops, when the drop comes from those cases: the reason is stored with the baseline and shown in the pull request (`--accept-drop`). A security measure never drops.
*   **Personal data never leaves in errors or traces**: error tracking is configured without personal data and scrubs what it sends (ADR 0009); attributes are identifiers and categories, and per-call identifiers tag issues and traces, never metrics.

## 17. Proportion and course correction

**Mistakes this project avoids:**
*   Building code and robustness before the problem is solved end to end.
*   Validations so strict that the agent cannot do its work.
*   A new rule for every case that fails, until the rules grow without limit.
*   Large files and modules nobody can reason about.
*   Patching the same path when results do not improve.
*   Fixing without first reading the traces (§16).
*   Building our own version of something Pipecat ships, or designing before reading Pipecat's documentation (§0).

**Growth.** What exists stays. Observability, evals, golden cases and security controls are added with each feature, to the extent that feature needs them: first working and safe, then more robust as real usage shows. The safety of writes and data is never postponed.

**Working rule.** Whoever implements and sees that the implementation fails, that the design is wrong or that a better path exists stops and says so at once, with evidence: where the error is and the alternative path with its trade-off, even if it contradicts an earlier decision. They do not keep insisting on the same path nor harden it. The maintainers decide.

**The working code decides, and governance is questioned too.** A rule of this repository (this constitution, `CLAUDE.md`, the ADR policy, documentation processes, CI) that blocks a better technical path, slows work without protecting anything real, creates a technical, security or reputational risk, or contradicts another rule or the code, is changed, not worked around: whoever meets it proposes the concrete change at once, with evidence. It is not applied in silence.
