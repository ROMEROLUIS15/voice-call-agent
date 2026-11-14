# ADR 0008: Security checks shared by developers and CI

*   **Status:** Accepted
*   **Date:** 2026-10-18

## Context
Security has to be checked on every change, not at the end: vulnerable dependencies, insecure code patterns and committed secrets, together with lint, types, tests and the coverage threshold. Checks that run differently on a laptop and in CI drift apart, and errors seen only in CI arrive late.

## Decision
`.pre-commit-config.yaml` is the single list of checks. Developers run it on every commit (ruff and gitleaks on the staged changes) and before a push (`uv run pre-commit run --all-files --hook-stage manual`); every CI job runs the same hooks.

| Concern | Tool |
|---|---|
| Lint, format, types | ruff, `mypy --strict` with Pydantic's plugin (a model built in code is checked for its fields' types and unknown fields) |
| Tests and coverage (≥ 85 %) | pytest with pytest-cov |
| Static security analysis | bandit 1.9.4 |
| Known vulnerable dependencies | pip-audit 2.10.1 |
| Secrets in the code and the whole history | gitleaks v8.30.1, its default rules extended by `.gitleaks.toml` |

Every tool is pinned (`uv.lock` for the Python ones, `rev:` for gitleaks), so a check gives the same verdict everywhere.

## Alternatives considered
*   **semgrep instead of bandit.** Not chosen: its rules are fetched from a registry at run time, so the same commit can get different verdicts on different days, and runs need network access. ruff already applies part of bandit's rules (`S`); bandit adds the rest offline.
*   **Separate CI-only commands.** Not chosen: they drift from what developers run.
*   **gitleaks' GitHub Action.** Not chosen: it would be a second way to run the same tool; the pre-commit hook pins one version for both.

## Consequences
*   Easier: a failing check reproduces locally with one command; security checks block merges from the first commit.
*   Harder: gitleaks is built from source by pre-commit (Go is needed locally; CI runners have it), and the first run is slower until cached. The coverage threshold rises with the dialog (phase 2) and is never lowered to make a change pass.

## Changes
2026-11-14 · gitleaks reads `.gitleaks.toml`: its default rules plus a connection string that carries its password and any environment file but `.env.example`. Against fake secrets of the kinds the project handles, the default rules caught a JWT and three API keys and missed a database URL with its password; with the file, all five and the file itself. The whole history still scans clean. The Supabase CLI's working folder (`supabase/`, with a local stack's keys) is ignored.

2026-11-14 · Pydantic's mypy plugin checks the models built in code (`init_typed`, `init_forbid_extra` in `[tool.pydantic-mypy]`). Before, a model's constructor took any type, so `CheckAvailabilityArguments(day_number="27")` passed mypy and failed only at run time; now mypy reports it. Data from outside (the model's tool calls, settings, files) is still validated by Pydantic at run time, in its lax mode. No existing code needed a change.
