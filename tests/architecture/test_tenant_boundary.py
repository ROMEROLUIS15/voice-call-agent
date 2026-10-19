"""Tenant boundary: the agent never names a business in what it sends to the backend.

The backend derives the business from `call_sid` (contract §4). Requests and port methods
therefore carry the call, never a tenant: neither the caller nor the LLM can choose one.
"""

import inspect

from pydantic import BaseModel

from voice_call_agent.call_session.business_resolution import BusinessResolver
from voice_call_agent.scheduling_backend import scheduling_models
from voice_call_agent.scheduling_backend.scheduling_port import SchedulingBackend

TENANT_WORDS = ("business", "tenant")


def tenant_fields(model: type[BaseModel]) -> list[str]:
    return [name for name in model.model_fields if any(w in name for w in TENANT_WORDS)]


def tenant_parameters(protocol: type) -> list[str]:
    found = []
    for name, method in inspect.getmembers(protocol, inspect.isfunction):
        for parameter in inspect.signature(method).parameters:
            if any(word in parameter for word in TENANT_WORDS):
                found.append(f"{name}({parameter})")
    return found


def _models_sent_with_a_call() -> list[type[BaseModel]]:
    return [
        model
        for model in vars(scheduling_models).values()
        if isinstance(model, type)
        and issubclass(model, BaseModel)
        and "call_id" in model.model_fields
    ]


def test_requests_carry_the_call_and_never_a_tenant() -> None:
    requests = _models_sent_with_a_call()
    assert {model.__name__ for model in requests} >= {
        "BookingRequest",
        "RescheduleRequest",
        "CancellationRequest",
        "CallerMessage",
    }
    assert {
        model.__name__: tenant_fields(model) for model in requests if tenant_fields(model)
    } == {}


def test_port_methods_take_no_tenant_argument() -> None:
    assert tenant_parameters(SchedulingBackend) == []
    assert tenant_parameters(BusinessResolver) == []


def test_checkers_catch_a_tenant_leak() -> None:
    class LeakyRequest(BaseModel):
        call_id: str
        business_id: str

    class LeakyPort:
        def book(self, call_id: str, tenant_id: str) -> None: ...

    assert tenant_fields(LeakyRequest) == ["business_id"]
    assert tenant_parameters(LeakyPort) == ["book(tenant_id)"]
