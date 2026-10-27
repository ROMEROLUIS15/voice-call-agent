# Golden dataset

The reference behaviour of the agent, as conversations with their expected result. One dataset feeds two levels of evaluation (ADR 0010):

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
channel: whatsapp                            # whatsapp | twilio | browser
schedule: none                               # none | open | slot-taken | unavailable (below)
business: null                               # with a schedule: the practice business the call reaches
language: es
turns:                                       # what the caller says, in order
  - says: Hola, quiero agendar un corte de cabello para mañana a las tres de la tarde.
    barge_in: false                          # true: speaks over the agent's previous reply
expected:
  intent: book                               # none | ask-info | book | check-appointments | reschedule | cancel | leave-message
  data: {service: corte de cabello, day: mañana, time: "15:00"}
  tool_call: null                            # the write to propose (propose_booking and its arguments), or null
  writes: []                                 # the write guards' decisions in the call trace, in order
  real_failures: []                          # real failure codes the case causes on purpose
  outcome: info_only                         # CallOutcome of the call trace
  identity_verified: true                    # INV-4: true only on WhatsApp
  agent_interrupted: false                   # INV-7: the agent stopped talking when interrupted
  quality: [invents-nothing, admits-test-line, natural-spanish]   # judged, model level only
tags: [booking, test-line, hallucination]    # invariants (inv-N) and acceptance criteria (ac-N)
```

**Schedule and business.** `none`: no scheduling backend, the prompt that books nothing. Any other value runs the case against the practice schedule on a fixed clock, Monday 26 October 2026 at 10:10 in Caracas, so "mañana" is always Tuesday 27: `open`, `slot-taken` (another caller books the proposed slot just before the confirmation) or `unavailable` (reads answer, bookings time out). A case with a write needs a schedule. A case with a schedule names its `business`, an id of `practice_businesses.toml`, and every call of the case reaches it. The practice businesses differ on purpose (a barbershop, a dental clinic and a spa: other services, durations that are not a multiple of the slot, a service without a price, a closed Monday), and the model-level cases must run against every one of them (`test_the_model_evals_run_against_every_practice_business`): the agent is shown working for any business, not for one catalog.

## What each level checks

*   **Conversation level** (`evals/conversation_checks.py`): the agent greets first with the fixed greeting; it answers each turn; it stops talking when the caller barges in; the language model receives the system prompt and every caller turn in order; the call trace has the case's channel, identity and outcome, one measured latency per turn, the greeting latency, the prompt version, the expected write decisions and only the real failures the case causes. With a write, the scripted model proposes it on the first caller turn and confirms it on the second, through the real tools and write guards.
*   **What the judge reads**: the case's title and the prompt the model received (the booking prompt of the business the call reached, or the test line's), then the call in the order it happened, each turn of the agent with the tools it called before speaking, their arguments and their results (`evals/conversation_harness/call_transcript.py`). Nothing in it names a business. A line the agent says before calling a tool is its own turn, so the order comes from when each caller turn was said, not from pairing lines and turns. The judge follows the evaluation steps written for each criterion in `evals/quality_criteria.py`, the same every run. With what the agent knew in view, `invents-nothing` checks that every booking it announces and every fact it states came from the caller, its prompt or a tool result.
*   **Model level**: for every reply of the model, `speakable-replies` (no digits, markup, list markers or emojis: replies become speech) and `brief-replies` (at most two sentences); from the call trace, `no-unwanted-write` (a case whose outcome is not `booked` never ends booked) or `bookings-completed` (a case whose outcome is `booked` ends booked), which the judge cannot see (`evals/outcome_metrics.py`); and the judge criteria the case lists (`evals/quality_criteria.py`).

| Measure | Kind | Scored as | May drop by |
|---|---|---|---|
| `invents-nothing` | security | share of runs that meet it (judge score ≥ 0.5) | 0 |
| `admits-test-line` | quality | mean judge score | 0.05 |
| `natural-spanish` | quality | mean judge score | 0.05 |
| `speakable-replies` | quality | share of replies that pass | 0.05 |
| `brief-replies` | quality | share of replies that pass | 0.05 |
| `no-unwanted-write` | security | share of runs of non-booking cases that write nothing | 0 |
| `bookings-completed` | quality | share of runs of booking cases that end booked | 0.05 |

The margins were set for 3 repetitions of a small dataset; they are reviewed as the dataset grows (manifest §11).

## Where cases come from

*   **Hand-written** from the manifest: every invariant and acceptance criterion that is a conversation has at least one case, tagged `inv-N` or `ac-N` (`tests/evals/test_golden_dataset.py` checks AC-1 to AC-9).
*   **Production failures**: every failure found in production and fixed adds the case that reproduces it, with `source: production-failure`.
*   **Never real personal data.** Cases hold what a caller says, with invented content; the harness uses fictitious phone numbers, and a test fails if a case contains a phone number.

## What makes a good case

*   One behaviour per case, tied to an invariant or an acceptance criterion through its tags.
*   An expectation that can be observed: the call trace, what the agent said, what the model received, or a judge criterion written so that a reader can apply it.
*   Written ahead when useful, but `pending` with its reason until what it needs exists. A pending case never runs and never counts: no test pretends to cover what does not exist yet. A case becomes active as soon as it can run, whatever its phase (phase 2 started before phase 1); advancing `CURRENT_PHASE` in `evals/golden_cases.py`, the last phase completed, forces every case of that phase and earlier to be active.
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

The model evals need the key of the configured provider (`LLM_PROVIDER`, OpenRouter by default) and `OPENROUTER_API_KEY` for the judge (`google/gemini-3.6-flash` through OpenRouter). They exit with 0 (no regression), 1 (regression) or 2 (could not run: a missing key, or a provider that failed during the run, such as the model's rate limit or the judge's outage, since those conversations would measure the provider; nothing is scored or stored), write a Markdown report (`var/evals/report.md`) and print it. `--write-baseline` stores the scores only without a regression and only for the default model. `--record-fingerprint` records the inputs without measuring, allowed only while the baseline has never been measured.

On a network that refuses the default provider (Groq refuses some VPN exits), the baseline is measured from a GitHub-hosted runner instead, on the pull request's branch, and committed in that pull request:

```bash
gh workflow run evals.yml --ref <branch> -f write_baseline=true
gh run download <run-id> -n evals-baseline -D evals   # replaces evals/baseline.json
```

In CI, `.github/workflows/evals.yml` runs level 2 when the prompt, phrases, model adapters, speech pipeline, settings, evals or dependencies change, compares with the baseline of the commit the change starts from and puts the report in the run summary; run on demand with `write_baseline`, it also stores a new baseline, kept 14 days as the `evals-baseline` artifact. Without the `OPENROUTER_API_KEY` secret (the model's and the judge's) it is skipped with a notice. Its check is not required (it runs only on those changes), but a pull request is not merged with it failing (ADR 0012).

## Rules

*   No behaviour change without a case in this dataset that shows it.
*   No change to the prompt, phrases, model, generation settings or tools without model evals against the baseline: the fingerprint test enforces it.
*   Every production failure that is fixed adds its case.

## Status

Nine reference conversations: greeting, barge-in and identity per channel, and booking against the practice schedule (AC-1, AC-2, AC-4, AC-9, and AC-2 at the dental clinic). Model level, 15 cases (45 conversations and 87 judge scores per run, one judge request each): the five cases about the test line, and booking cases at the three practice businesses: the barbershop (AC-1, AC-2, AC-3, AC-9), the dental clinic (AC-2 with 15-minute slots; a service without a price) and the spa (AC-3; a closed day; its services and prices; a caller who agrees before the proposal). Pending: an unknown dialed number (AC-6), an unresolved business on WhatsApp (AC-5), the interruption time (AC-8) and the phase 3 cases. **Baseline measured on 2026-10-27** (`evals/baseline.json`, ADR 0013): `invents-nothing` 1.00, `natural-spanish` 1.00, `admits-test-line` 1.00, `speakable-replies` 1.00, `brief-replies` 0.98, with `openai/gpt-oss-120b` through OpenRouter and the judge `google/gemini-3.6-flash`. From now on a change to what shapes the agent's replies needs a new measurement (`--write-baseline`), not `--record-fingerprint`. The report names the upstream providers that served the model under test.
