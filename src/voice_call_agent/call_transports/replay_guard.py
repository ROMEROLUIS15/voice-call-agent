"""Rejection of repeated webhook events and media streams (replay protection)."""

import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Protocol


class ReplayGuard(Protocol):
    """Remembers event ids for a window of time."""

    async def first_seen(self, key: str) -> bool:
        """True the first time `key` is presented within the window; False for a repeat."""
        ...


class InMemoryReplayGuard:
    """Per-instance memory of seen keys.

    Several instances need a shared store: a repeat that reaches another instance is not seen
    here (manifest §10). `max_keys` bounds memory under a flood; the oldest keys go first.
    """

    def __init__(
        self,
        window_seconds: float,
        *,
        max_keys: int = 100_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._expiry_by_key: OrderedDict[str, float] = OrderedDict()

    async def first_seen(self, key: str) -> bool:
        now = self._clock()
        self._forget_expired(now)
        if key in self._expiry_by_key:
            return False
        if len(self._expiry_by_key) >= self._max_keys:
            self._expiry_by_key.popitem(last=False)
        self._expiry_by_key[key] = now + self._window_seconds
        return True

    def _forget_expired(self, now: float) -> None:
        # Keys are inserted with the same window, so insertion order is expiry order.
        while self._expiry_by_key:
            oldest_key, expires_at = next(iter(self._expiry_by_key.items()))
            if expires_at > now:
                return
            del self._expiry_by_key[oldest_key]
