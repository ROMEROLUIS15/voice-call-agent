"""Infrastructure failures of the scheduling backend.

Business outcomes are not here: they are typed results in `scheduling_models`.
"""


class SchedulingBackendError(Exception):
    """Base class of every scheduling backend failure."""


class SchedulingBackendUnavailableError(SchedulingBackendError):
    """Timeout, rate limit or transient failure, after the allowed retry.

    The agent never invents a result (INV-5): it says it could not complete the action and
    offers to take a message. After a write timeout it checks the real state first (contract §7).
    """


class SchedulingBackendRejectedRequestError(SchedulingBackendError):
    """Non-recoverable rejection (bad signature, logic error). Never retried."""


class IdempotencyKeyReusedError(SchedulingBackendError):
    """The same idempotency key was sent with a different body (contract §5)."""
