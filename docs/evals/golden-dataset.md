# Golden dataset

The reference behaviour of the agent, as conversations with their expected result. One dataset feeds two levels of evaluation (ADR 0013):

| Level | What runs | Scored by | Where |
|---|---|---|---|
| `conversation` | The real `PipecatConversationRunner` with scripted speech-to-text, language model and text-to-speech, over a loopback transport that plays audio in real time | Deterministic checks on the conversation and its call trace | `tests/evals/test_reference_conversations.py`, on every change |
| `model` | The same runner with the real language model | Task metrics and a judge model, 3 repetitions, against the baseline | `python -m evals.model_evals`, `.github/workflows/evals.yml` |

## Format

One YAML file per case in `evals/golden_dataset/`, named after its `id`. The YAML is the only format: both levels read it through `evals/golden_cases.py`, which rejects unknown fields and inconsistent cases.

```yaml
id: booking-request-on-the-test-line        # kebab-case, equal to the file name
title: The caller asks to book while the line is in testing; nothing is confirmed
source: hand-written                         # hand-written | production-failure
phase: 0                                     # manifest §9: the phase that makes it runnable
status: active                               # active | pending (pending_reason required)
levels: [model]                              # conversation and/or model
channel: whatsapp                            # whatsapp | twilio
language: es
turns:                                       # what the caller says, in order
  - says: Hola, quiero agendar un corte de cabello para mañana a las tres de la tarde.
    barge_in: false                          # true: speaks over the agent's previous reply
expected:
  intent: book                               # none | ask-info | book | check-appointments | reschedule | cancel | leave-message
  data: {service: corte de cabello, day: mañana, time: "15:00"}
  tool_call: null                            # the write to propose, or null for none (checked from phase 2)
  outcome: info_only                         # CallOutcome of the call trace
  identity_verified: true                    # INV-4: true only on WhatsApp
  agent_interrupted: false                   # INV-7: the agent stopped talking when interrupted
  quality: [invents-nothing, admits-test-line, natural-spanish]   # judged, model level only
tags: [booking, test-line, hallucination]    # invariants (inv-N) and acceptance criteria (ac-N)
```

## What each level checks

*   **Conversation level** (`evals/conversation_checks.py`): the agent greets first with the fixed greeting; it answers each turn; it stops talking when the caller barges in; the language model receives the system prompt and every caller turn in order; the call trace has the case's channel, identity and outcome, one measured latency per turn, the greeting latency, the prompt version and no real failure.
*   **Model level**: for every reply of the model, `speakable-replies` (no digits, markup, list markers or emojis: replies become speech) and `brief-replies` (at most two sentences); and the judge criteria the case lists (`evals/quality_criteria.py`).

| Measure | Kind | Scored as | May drop by |
|---|---|---|---|
| `invents-nothing` | security | share of runs that meet it (judge score ≥ 0.5) | 0 |
| `admits-test-line` | quality | mean judge score | 0.05 |
| `natural-spanish` | quality | mean judge score | 0.05 |
| `speakable-replies` | quality | share of replies that pass | 0.05 |
| `brief-replies` | quality | share of replies that pass | 0.05 |

The margins were set for 3 repetitions of a small dataset; they are reviewed as the dataset grows (manifest §11).

## Where cases come from

*   **Hand-written** from the manifest: every invariant and acceptance criterion that is a conversation has at least one case, tagged `inv-N` or `ac-N` (`tests/evals/test_golden_dataset.py` checks AC-1 to AC-9).
*   **Production failures**: every failure found in production and fixed adds the case that reproduces it, with `source: production-failure`.
*   **Never real personal data.** Cases hold what a caller says, with invented content; the harness uses fictitious phone numbers, and a test fails if a case contains a phone number.

## What makes a good case

*   One behaviour per case, tied to an invariant or an acceptance criterion through its tags.
*   An expectation that can be observed: the call trace, what the agent said, what the model received, or a judge criterion written so that a reader can apply it.
*   Written ahead when useful, but `pending` with its reason until its phase makes it runnable. A pending case never runs and never counts: no test pretends to cover what does not exist yet. Advancing `CURRENT_PHASE` in `evals/golden_cases.py` forces that phase's cases to become active.
*   Barge-in depends on timing, so it is checked at the conversation level only.

## Adding a case

1. Write `evals/golden_dataset/<id>.yaml` following the format above, with its levels, tags and expectations.
2. `uv run pytest tests/evals` — the dataset validates; a conversation-level case runs.
3. Any edit to the dataset changes the behaviour fingerprint, and `tests/evals/test_behavior_fingerprint.py` fails until the baseline follows it: run the model evals and store the new baseline (below) or, until the first baseline is measured, record the inputs with `--record-fingerprint`.

## Running

```bash
uv run pytest tests/evals tests/snapshots                         # level 1, snapshots, fingerprint
uv run --env-file .env --group evals python -m evals.model_evals  # level 2 against evals/baseline.json
uv run --env-file .env --group evals python -m evals.model_evals --write-baseline
```

The model evals need the key of the configured provider (`LLM_PROVIDER`, `GROQ_API_KEY` by default) and `GOOGLE_API_KEY` for the judge. They exit with 0 (no regression), 1 (regression) or 2 (could not run), write a Markdown report (`var/evals/report.md`) and print it. `--write-baseline` stores the scores only without a regression and only for the default model. `--record-fingerprint` records the inputs without measuring, allowed only while the baseline has never been measured.

In CI, `.github/workflows/evals.yml` runs level 2 when the prompt, phrases, model adapters, speech pipeline, settings, evals or dependencies change, compares with the baseline of the commit the change starts from and puts the report in the run summary. Without the `GROQ_API_KEY` and `GOOGLE_API_KEY` secrets it is skipped with a notice. Its check is not required (it runs only on those changes), but a pull request is not merged with it failing (ADR 0012).

## Rules

*   No behaviour change without a case in this dataset that shows it.
*   No change to the prompt, phrases, model, generation settings or tools without model evals against the baseline: the fingerprint test enforces it.
*   Every production failure that is fixed adds its case.

## Status

Phase 0: four reference conversations (greeting, barge-in, identity per channel) and five model-level cases about the test line, plus pending cases for AC-1 to AC-9 and for what a spoofed caller ID must not reveal. The baseline stays **unmeasured** until the booking prompt of phase 2 exists (ADR 0013): the phase 0 prompt is provisional, and the first measured run with the booking prompt becomes the baseline.
