# ADR 0020: The default language model, chosen by measurement: DeepSeek V4.1 Flash on Together

*   **Status:** Accepted
*   **Date:** 2026-10-28

## Context

The booking flow (ADR 0019) left the model's own weaknesses to be settled by measurement. With `openai/gpt-oss-120b` on Groq, a security measure of the model evals moved between runs of the same code: in one run of three repetitions, a caller who changed the service while giving the name was booked the earlier service (`books-what-was-asked` 0.96), a failure also heard in a practice call. A security measure may never drop (constitution §16), so every later change to the prompt or the flow would depend on that luck. The model also matters for latency: the target is 1.0 s p50 to the first audio (manifest §6), and the model's time to the first token is most of the turn.

## Decision

The service's default model is **`deepseek/deepseek-v4.1-flash`, reached through OpenRouter, served by Together and, when Together fails, by Venice**, never by another provider, with reasoning effort `low` and every parameter required (`require_parameters`), and neither provider may collect the call's data (`data_collection: deny`). The route is fixed like the earlier one: different providers would change latency between calls.

Measured on 2026-10-28 with the model evals (27 cases, 3 repetitions, judge `google/gemini-3.6-flash`) and Pipecat's time-to-first-byte metric of each response:

| Model and route | Security measures | `brief-replies` | First token p50 / p90 |
|---|---|---|---|
| `openai/gpt-oss-120b`, Groq | 1.00 in two runs, 0.96 in one | 0.93 | 0.47 / 0.79 s |
| `anthropic/claude-haiku-5.5`, any provider | 1.00 | 0.67 | 0.78 / 2.60 s |
| `deepseek/deepseek-v4.1-flash`, any provider | 1.00 | 0.79 | 0.73 / 1.40 s |
| `deepseek/deepseek-v4.1-flash`, Together | 1.00 | 0.75 | 0.37 / 0.50 s |
| the same, with the prompt asking for no loose courtesy sentence first | 1.00 | 0.83 | 0.39 / 0.67 s |

Together and Venice were chosen by probing every provider of the model through OpenRouter with five short streamed requests carrying a function and the reasoning effort: Together answered first (0.45 s p50) and Venice was the fastest that answered every request (0.67 s).

## Alternatives considered

*   **Keep `gpt-oss-120b` on Groq.** Not chosen: its security measure depends on the run, and DeepSeek on Together is faster at p50 and p90.
*   **Claude Haiku 5.5.** Not chosen: as accurate in the evals, but a p90 of 2.6 s to the first token leaves the caller in silence.
*   **DeepSeek through any provider.** Not chosen: six providers served one run, with a p90 of 1.4 s.
*   **DeepSeek's own API.** Not used: phase 0 set it aside because its privacy policy stores personal data in China (manifest §7). The route never reaches it: only Together and Venice serve the calls, and neither may keep the data.

## Consequences

*   Easier: the security measures held in every run measured with this model, and the first token is earlier than before.
*   Harder: Together charges 0.30 / 1.20 USD per million tokens, twice `gpt-oss-120b` on Groq; about 0.006 USD of model per practice call, against about 0.04 USD of speech-to-text and voice. Its replies run longer: `brief-replies` is lower than with the earlier model, within its margin (ADR 0016).
*   The time to the first token measures the first streamed chunk; the time to the first audio on calls is read from each call trace's turns (manifest §6).
*   Revisited when a model is measured more accurate at a comparable first token, or when Together's latency or price changes.
