# ADR 0013: Golden dataset and evals at two levels, with a fingerprint of what the evals measure

*   **Status:** Accepted
*   **Date:** 2026-10-19
*   **Supersedes:** 0010

## Context
ADR 0010 set up one golden dataset, evals at two levels and a baseline guarded by a fingerprint of the inputs it was measured with. Two of those inputs, the speech-to-text model and the voice, never reach the model evals: they run with scripted speech-to-text and a recording text-to-speech, so changing either would demand a paid run that cannot detect any effect. And the phase 0 prompt is provisional (a test line that books nothing): a baseline measured with it would gate prompt changes that phase 2 replaces anyway. Everything else in ADR 0010 holds and is restated here.

## Decision
*   **One golden dataset**, one YAML file per case in `evals/golden_dataset/` (`docs/evals/golden-dataset.md`): channel, language, caller turns, expected intent, data, tool call, outcome and identity, quality criteria, tags, phase and status. A case written ahead of its phase is `pending`, says why, and never runs; cases of the current phase must be active.
*   **Level 1, reference conversations** (`tests/evals/test_reference_conversations.py`): the real `PipecatConversationRunner` with scripted speech-to-text, language model and text-to-speech and a loopback transport that plays audio in real time. Turn detection, interruptions, the call trace and its observers are the production ones. Deterministic; runs with pytest on every change.
*   **Level 2, model evals** (`python -m evals.model_evals`): the same runner with the real language model. Deterministic task metrics (speakable, brief replies) and DeepEval's conversational G-Eval with a judge model from another provider than the model under test (`gemini-3.6-flash`, pinned). Every case runs 3 times. A security criterion counts as met or not met and may not drop at all; a quality measure is averaged and may drop by 0.05. Both margins are reviewed as the dataset grows.
*   **Baseline and fingerprint.** `evals/baseline.json` records the scores and the inputs they were measured with, only those the model evals exercise: conversation content version, model and generation settings, dataset version, scoring code, judge model. `tests/evals/test_behavior_fingerprint.py` fails when those inputs change and the baseline does not. The speech-to-text model and the voice stay in every call trace; their effect is measured with real calls. Syrupy snapshots (`tests/snapshots/`) show the prompt, phrases, model configuration and port schemas in review.
*   **First baseline with the booking prompt.** The baseline is first measured with the booking prompt of phase 2. Until then `--record-fingerprint` records the inputs unmeasured; once measured, the fingerprint changes only with new measurements.
*   **CI.** `.github/workflows/evals.yml` runs on GitHub-hosted runners when what shapes the replies changes, compares with the baseline of the commit the change starts from and publishes the report in the run summary. Its check is not required, but a pull request is not merged with it failing (ADR 0012). Secrets reach only the steps that use them; without them the job is skipped with a notice. `.github/workflows/provider-reachability.yml` checks, on demand, that the runners reach every provider.
*   **DeepEval** lives in the `evals` dependency group (`deepeval==4.2.8`), is imported only by `evals/judge_scoring.py`, and runs with telemetry off, forced in code and in the workflow.

## Alternatives considered
*   **Keep ADR 0010 unchanged.** Not chosen: a voice change would demand a paid run that measures nothing, and a baseline of the provisional prompt would gate changes that phase 2 replaces.
*   **Assertions on model output in unit tests.** Not chosen: brittle against a non-deterministic model, and they do not measure quality.
*   **Pipecat's audio-level evals.** Not chosen for now: they need live providers and are not deterministic; they fit end-to-end runs with recorded audio (phase 5).
*   **A self-hosted runner** to reach providers. Rejected: on a public repository a pull request could run arbitrary code on a maintainer's machine.
*   **A judge from the same provider as the model under test.** Not chosen: it shares the model's blind spots.
*   **Continuous judge scores for security with no margin.** Not chosen: judge noise alone would fail runs; a criterion met or not met is stable.
*   **A second dataset format for evals.** Not chosen: two formats drift; one YAML feeds both levels.

## Consequences
*   Easier: a behaviour change shows up as a failing reference conversation, a snapshot diff or a fingerprint mismatch; model regressions are measured against a baseline with explicit margins; the provisional prompt can change during phase 0 without paid runs.
*   Harder: from phase 2, a prompt, model or scoring change needs a run with real keys to store a new baseline; editing a scoring file changes the fingerprint even for a comment. The judge has its own bias, calibrated against human labels in phase 5. Until the booking prompt exists nothing is compared: a phase 0 prompt change is reviewed through its snapshot only.
