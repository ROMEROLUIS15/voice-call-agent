"""Entrypoint: `uv run voice-call-agent` or `python -m voice_call_agent`."""

from voice_call_agent.asgi_app import build_asgi_app
from voice_call_agent.graceful_http_server import GracefulHttpServer, server_config
from voice_call_agent.observability.log_configuration import configure_logging
from voice_call_agent.service_composition import compose_service
from voice_call_agent.settings.service_settings import ServiceSettings


def main() -> None:
    settings = ServiceSettings()
    configure_logging(settings.logging_output())
    components = compose_service(settings)
    app = build_asgi_app(settings, components)
    config = server_config(app, settings.server(), settings.http_hardening())
    GracefulHttpServer(config, components.supervisor, components.shutdown_grace_seconds).run()


if __name__ == "__main__":
    main()
