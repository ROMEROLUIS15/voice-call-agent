## What

<!-- What changed and why, in a few lines. -->

## How it works now

<!-- Where (file and function), the flow in a few steps, and one example with invented data. -->

## Documentation

<!-- Constitution §8: the README describes the current state. -->

- README sections changed: <!-- e.g. Status, Measured results; or "none, because …" -->
- `docs/` changed: <!-- manifest, specs, ADRs, golden dataset; or "none, because …" -->

## Checks

- [ ] `uv run pre-commit run --all-files --hook-stage manual`
- [ ] Model evals against the baseline, if the behaviour fingerprint changed
- [ ] Threat model and negative security tests, if an attack surface changed
