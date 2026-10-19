"""Configuration errors."""


class IncompleteSettingsError(ValueError):
    """A required variable or part of a variable group is missing.

    Subclasses `ValueError` so pydantic reports it as a validation error at startup.
    """
