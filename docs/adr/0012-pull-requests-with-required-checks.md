# ADR 0012: Changes reach main through pull requests with required checks

*   **Status:** Accepted
*   **Date:** 2026-10-19

## Context
The constitution said that CI blocks a change, but `main` had no branch protection and changes were pushed to it directly: CI reported a failure only after the change was already published. A rule that describes a protection that does not exist misleads whoever relies on it.

## Decision
*   `main` is protected: changes reach it only through a pull request; CI's `quality`, `tests` and `security` jobs are required checks, and the branch must be up to date with `main` before merging; the protection applies to administrators too; force pushes and deletion are not allowed.
*   No approving review is required, because one maintainer cannot approve their own pull request. A maintainer approves each merge.
*   The model evals check is not required: it runs only when what shapes the agent's replies changes, and a required check that never runs would block every other pull request. A pull request is not merged with it failing.

## Alternatives considered
*   **Keep pushing to `main` and reword the rule as "`main` stays green".** Not chosen: honest, but it blocks nothing.
*   **Require an approving review.** Not chosen while there is one maintainer.
*   **Run the evals workflow on every pull request so that it can be required.** Not chosen: it would spend provider credits, or need its own change detection, for changes that cannot alter the replies.

## Consequences
*   Easier: the checks block before publication, as the constitution says; the merge is the point where a change is approved.
*   Harder: one branch and one pull request per change; a fix to a red `main` also goes through a pull request.
