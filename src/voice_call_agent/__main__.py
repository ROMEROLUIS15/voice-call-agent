"""Entrypoint: `uv run voice-call-agent` or `python -m voice_call_agent`."""

import uvicorn

from voice_call_agent.asgi_app import build_asgi_app
from voice_call_agent.graceful_http_server import GracefulHttpServer
from voice_call_agent.observability.log_configuration import configure_logging
from voice_call_agent.service_composition import compose_service
from voice_call_agent.settings.service_settings import ServiceSettings


def main() -> None:
    settings = ServiceSettings()
    configure_logging(settings.logging_output())
    components = compose_service(settings)
    server = settings.server()
    config = uvicorn.Config(
        build_asgi_app(settings, components),
        host=server.host,
        port=server.port,
        log_config=None,  # uvicorn's records go through the single structured sink.
    )
    GracefulHttpServer(config, components.supervisor, components.shutdown_grace_seconds).run()


if __name__ == "__main__":
    main()
