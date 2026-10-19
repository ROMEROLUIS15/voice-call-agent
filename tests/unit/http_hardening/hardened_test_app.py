"""A minimal FastAPI app wrapped by `harden_app`, to test the protections in isolation."""

from fastapi import FastAPI, Query, Response
from starlette.types import ASGIApp

from voice_call_agent.http_hardening.app_hardening import harden_app
from voice_call_agent.http_hardening.request_rate_limit import build_rate_limiter
from voice_call_agent.settings.sections import (
    DeploymentEnvironment,
    HttpHardeningSettings,
    WebhookProtectionSettings,
)

LIMITED_PATH = "/limited"
LEAKY_ERROR = "database password is hunter2 at /srv/app/secrets.py"


def hardened_test_app(
    *,
    environment: DeploymentEnvironment = DeploymentEnvironment.PRODUCTION,
    cors_allowed_origins: tuple[str, ...] = (),
    rate_limit: str = "100/minute",
    max_request_body_bytes: int = 1024,
) -> ASGIApp:
    app = FastAPI()

    @app.get("/ok")
    async def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/sets-server-header")
    async def sets_server_header() -> Response:
        return Response("hi", headers={"Server": "internal-stack/1.2", "X-Frame-Options": "ALLOW"})

    @app.get("/fails")
    async def fails() -> None:
        raise RuntimeError(LEAKY_ERROR)

    @app.get("/needs-param")
    async def needs_param(count: int = Query()) -> dict[str, int]:
        return {"count": count}

    @app.post("/echo")
    async def echo(body: dict[str, str]) -> dict[str, str]:
        return body

    @app.api_route(LIMITED_PATH, methods=["GET", "POST"])
    async def limited() -> dict[str, str]:
        return {"status": "ok"}

    return harden_app(
        app,
        http=HttpHardeningSettings(
            environment=environment,
            allowed_hosts=("testserver",),
            trusted_proxy_addresses="127.0.0.1",
            cors_allowed_origins=cors_allowed_origins,
            max_request_body_bytes=max_request_body_bytes,
            max_websocket_message_bytes=1024,
        ),
        webhooks=WebhookProtectionSettings(
            rate_limit=rate_limit,
            rate_limit_storage_uri="async+memory://",
            replay_window_seconds=300,
            connect_event_max_age_seconds=60,
        ),
        rate_limiter=build_rate_limiter("async+memory://"),
        rate_limited_paths=frozenset({LIMITED_PATH}),
    )
