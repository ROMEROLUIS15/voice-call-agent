"""A Sentry transport that keeps envelopes in memory instead of sending them."""

from typing import Any

import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

# Sentry payloads are free-form JSON; tests read them as such.
type SentryPayload = dict[str, Any]


class CapturingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.envelopes.append(envelope)

    def items(self, item_type: str) -> list[SentryPayload]:
        sentry_sdk.flush()
        return [
            item.payload.json
            for envelope in self.envelopes
            for item in envelope.items
            if item.type == item_type and item.payload.json is not None
        ]
