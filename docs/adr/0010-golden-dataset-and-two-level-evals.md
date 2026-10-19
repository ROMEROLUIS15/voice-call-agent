# ADR 0010: Golden dataset and evals at two levels, with a judge model

*   **Status:** Accepted, amended by 0013
*   **Date:** 2026-10-19

## Context
What the agent says depends on the prompt, the fixed phrases, the language model and its generation settings, and on how the pipeline handles turns and interruptions. Any of them can change behaviour without failing a single unit test, and the model's output is not deterministic. Changes must be checked against a known baseline before they land. The repository is public: provider keys can only live in CI secrets, and code from a pull request must never run on maintainers' machines.

## Decision
*   **One golden dataset**, one YAML file per case in `evals/golden_dataset/` (`docs/evals/golden-dataset.md`): channel, language, caller turns, expected intent, data, tool call, outcome and identity, quality criteria, tags, phase and status. A case written ahead of its phase is `pending`, says why, and never runs; cases of the current phase must be active.
*   **Level 1, reference conversations** (`tests/evals/test_reference_conversations.py`): the real `PipecatConversationRunner` with scripted speech-to-text, language model and text-to-speech and a loopback transport that plays audio in real time. Turn detection, interruptions, the call trace and its observers are the production ones. Deterministic; runs with pytest on every change.
*   **Level 2, model evals** (`python -m evals.model_evals`): the same runner with the real language model. Deterministic task metrics (speakable, brief replies) and DeepEval's conversational G-Eval with a judge model from another provider than the model under test (`gemini-3.6-flash`, pinned). Every case runs 3 times. A security criterion counts as met or not met and may not drop at all; a quality measure is averaged and may drop by 0.05. Both margins are reviewed as the dataset grows.
*   **Baseline and fingerprint.** `evals/baseline.json` records the scores and the inputs they were measured with: conversation content version, model and generation settings, STT model and voice, dataset version, scoring code, judge model. `tests/evals/test_behavior_fingerprint.py` fails when those inputs change and the baseline does not, so no such change lands without new evals. Syrupy snapshots (`tests/snapshots/`) show the prompt, phrases, model configuration and port schemas in review.
*   **CI.** `.github/workflows/evals.yml` runs on GitHub-hosted runners when any input of the fingerprint changes, compares with the baseline of the commit the change starts from and publishes the report in the run summary. Secrets reach only the steps that use them; without them the job is skipped with a notice. `.github/workflows/provider-reachability.yml` checks, on demand, that the runners reach every provider.
*   **DeepEval** lives in the `evals` dependency group (`deepeval==4.2.8`), is imported only by `evals/judge_scoring.py`, and runs with telemetry off, forced in code and in the workflow.

## Alternatives considered
*   **Assertions on model output in unit tests.** Not chosen: brittle against a non-deterministic model, and they do not measure quality.
*   **Pipecat's audio-level evals.** Not chosen for now: they need live providers and are not deterministic; they fit end-to-end runs with recorded audio (phase 5).
*   **A self-hosted runner** to reach providers. Rejected: on a public repository a pull request could run arbitrary code on a maintainer's machine.
*   **A judge from the same provider as the model under test.** Not chosen: it shares the model's blind spots.
*   **Continuous judge scores for security with no margin.** Not chosen: judge noise alone would fail runs; a criterion met or not met is stable.
*   **A second dataset format for evals.** Not chosen: two formats drift; one YAML feeds both levels.

## Consequences
*   Easier: a behaviour change shows up as a failing reference conversation, a snapshot diff or a fingerprint mismatch; model regressions are measured against a baseline with explicit margins.
*   Harder: a prompt, model or scoring change needs a run with real keys (15 conversations and 36 judge scores today) to store a new baseline; editing a scoring file changes the fingerprint even for a comment. The judge has its own bias, calibrated against human labels in phase 5. Until the CI secrets exist, the baseline is recorded unmeasured and nothing is compared.
