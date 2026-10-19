"""Cronix adapter: implements `SchedulingBackend` and `BusinessResolver` over HTTP.

Speaks the `phone-agent-api` contract (`docs/specs/cronix-phone-api-contract.md`): HMAC-signed
requests, idempotency keys and the timeouts of contract §7. Implemented in phase 1.
"""
