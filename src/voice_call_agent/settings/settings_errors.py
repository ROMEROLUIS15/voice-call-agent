"""Configuration errors."""


class IncompleteSettingsError(ValueError):
    """A required variable or part of a variable group is missing.

    Subclasses `ValueError` so pydantic reports it as a validation error at startup.
    """


class UnsafeSettingsError(ValueError):
    """A setting would weaken the service's security (for example, CORS open to `*`)."""
