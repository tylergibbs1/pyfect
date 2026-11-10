"""``OTEL_RESOURCE_ATTRIBUTES`` as Effect's ``OtlpResource`` and
``@effect/opentelemetry``'s ``Resource`` read it: ``Config.Record(
StringFromUriComponent, StringFromUriComponent, name, { trim: true,
keepEmptyValues: true })``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from pyfect import config
from pyfect import schema as S
from pyfect._digits import in_object_order
from pyfect._js import decode_uri_component
from pyfect.config import ConfigError, Pointer
from pyfect.effect import Effect, fail, succeed
from pyfect.option import Some
from pyfect.schema import SchemaError
from pyfect.schema.issue import InvalidValue

NAME: Final = "OTEL_RESOURCE_ATTRIBUTES"


def _decode_keys(name: str) -> Callable[[dict[str, str]], Effect[dict[str, str], ConfigError]]:
    def decode(values: dict[str, str]) -> Effect[dict[str, str], ConfigError]:
        decoded: dict[str, str] = {}
        for key, value in values.items():
            try:
                decoded[decode_uri_component(key)] = value
            except ValueError:
                issue = InvalidValue(
                    {"message": "Expected a URI component encoded string"}, Some(key)
                )
                return fail(ConfigError(SchemaError(Pointer((name, key), issue))))
        return succeed(in_object_order(decoded))

    return decode


def resource_attributes() -> config.Config[dict[str, str]]:
    """A record node, or ``key=value`` pairs split at ``,`` and the first
    ``=``: keys and values trimmed, then percent-decoded once. An empty
    value is kept as ``""``; a pair without ``=`` or with an empty key is
    skipped; a repeated key keeps its last value. Invalid percent-encoding
    is a ``ConfigError``."""
    return config.dict_of(
        S.StringFromUriComponent, NAME, trim=True, keep_empty_values=True
    ).map_effect(_decode_keys(NAME))
