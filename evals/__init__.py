"""Evaluation of the agent's behaviour against the golden dataset (`docs/evals/golden-dataset.md`).

Two levels share one dataset: reference conversations with scripted providers, run by pytest on
every change, and model evals with the real language model and a judge model, run by
`.github/workflows/evals.yml`. Not shipped with the service.
"""
