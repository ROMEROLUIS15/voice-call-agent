"""Complete Pipecat settings for the scripted services."""

from dataclasses import fields

from pipecat.services.settings import ServiceSettings

SCRIPTED_MODEL = "scripted"


def complete_settings[S: ServiceSettings](settings_type: type[S], **given: object) -> S:
    """Every field set (to `None` unless given): Pipecat logs an error for any field left unset."""
    settings = settings_type()
    values = {field.name: None for field in fields(settings) if field.name != "extra"}
    for name, value in (values | {"model": SCRIPTED_MODEL} | given).items():
        setattr(settings, name, value)
    return settings
