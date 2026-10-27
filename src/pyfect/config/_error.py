"""``ConfigError``: reading configuration failed."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.config._issue import SchemaError
from pyfect.config_provider import SourceError
from pyfect.errors import TaggedError


@dataclass(eq=False)
class ConfigError(TaggedError):
    """Configuration could not be read: the source failed (``SourceError``)
    or the data was missing or invalid (``SchemaError``). ``message`` is
    Effect's (``SchemaError(Expected string\\n  at ["PORT"])``); the bare
    text is ``error.cause.message``."""

    cause: SourceError | SchemaError

    @property
    def message(self) -> str:
        match self.cause:
            case SchemaError():
                return f"SchemaError({self.cause.message})"
            case SourceError(message=message):
                return f"SourceError: {message}"
