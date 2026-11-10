"""The OTLP resource attached to every exported log, metric and span
(Effect's ``OtlpResource``), and the conversion of values into OTLP
attribute values.

The payload types are the OTLP/JSON shapes, as plain dicts with the wire's
camelCase keys, so ``OtlpSerialization`` writes them as they are.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import NotRequired, TypedDict, cast

from pyfect import config
from pyfect._digits import in_object_order
from pyfect._version import VERSION
from pyfect.effect import Effect, gen
from pyfect.logger._text import format_unknown
from pyfect.observability._resource_attributes import resource_attributes
from pyfect.option import Option, Some

__all__ = [
    "AnyValue",
    "ArrayValue",
    "KeyValue",
    "KeyValueList",
    "Resource",
    "ResourceOptions",
    "entries_to_attributes",
    "from_config",
    "from_options",
    "instrumentation_scope",
    "make",
    "service_name_unsafe",
    "unknown_to_attribute_value",
]


class AnyValue(TypedDict, total=False):
    """An OTLP ``AnyValue``: one of its fields is set. ``intValue`` is a
    number while it is a safe JavaScript integer and decimal text past
    that, as OTLP/JSON writes an int64."""

    stringValue: str | None
    boolValue: bool | None
    intValue: int | str | None
    doubleValue: float | None
    arrayValue: ArrayValue
    kvlistValue: KeyValueList
    bytesValue: bytes


class ArrayValue(TypedDict):
    values: list[AnyValue]


class KeyValue(TypedDict):
    key: str
    value: AnyValue


class KeyValueList(TypedDict):
    values: list[KeyValue]


class Resource(TypedDict):
    """What the telemetry describes: the service and its attributes."""

    attributes: list[KeyValue]
    droppedAttributesCount: int


class ResourceOptions(TypedDict, total=False):
    """The resource options every OTLP exporter takes."""

    service_name: str | None
    service_version: str | None
    attributes: Mapping[str, object] | None


class _Scope(TypedDict):
    name: str
    version: NotRequired[str]


def instrumentation_scope() -> _Scope:
    """The instrumentation scope of the exported spans and logs: pyfect
    and its version (Effect's ``effect``)."""
    return {"name": "pyfect", "version": VERSION}


def make(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    attributes: Mapping[str, object] | None = None,
) -> Resource:
    """A resource with the ``telemetry.sdk.*`` defaults, then
    ``attributes``, then the service name and version (an empty one adds
    nothing), later ones winning."""
    merged: dict[str, object] = {
        "telemetry.sdk.name": "pyfect",
        "telemetry.sdk.language": "python",
        "telemetry.sdk.version": VERSION,
        **(attributes or {}),
    }
    if service_name:
        merged["service.name"] = service_name
    if service_version:
        merged["service.version"] = service_version
    return {
        "attributes": entries_to_attributes(in_object_order(merged).items()),
        "droppedAttributesCount": 0,
    }


def _first[A](*options: Option[A]) -> A | None:
    for option in options:
        if isinstance(option, Some):
            return option.value
    return None


def from_config(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    attributes: Mapping[str, object] | None = None,
) -> Effect[Resource]:
    """A resource from the options and the OpenTelemetry configuration.

    The service name is the first of ``service_name``, the
    ``service.name`` attribute, ``OTEL_SERVICE_NAME`` and ``service.name``
    in ``OTEL_RESOURCE_ATTRIBUTES``; the version likewise, with
    ``OTEL_SERVICE_VERSION``. ``attributes`` win over
    ``OTEL_RESOURCE_ATTRIBUTES``. Missing or invalid configuration (no
    service name at all) is a defect."""

    @gen
    def build():
        env: dict[str, str] | None = yield from resource_attributes().with_default(None)
        explicit = attributes or {}

        name: object = service_name
        if name is None:
            name = explicit.get("service.name")
        if name is None:
            name = _first((yield from config.string("OTEL_SERVICE_NAME").option()))
        if name is None and env is not None:
            name = env.get("service.name")
        if name is None:
            name = yield from config.string("OTEL_SERVICE_NAME")

        version: object = service_version
        if version is None:
            version = explicit.get("service.version")
        if version is None:
            version = _first((yield from config.string("OTEL_SERVICE_VERSION").option()))
        if version is None and env is not None:
            version = env.get("service.version")

        merged: dict[str, object] = {**(env or {}), **explicit}
        merged.pop("service.name", None)
        merged.pop("service.version", None)
        return make(
            service_name=name,  # pyright: ignore[reportArgumentType]
            service_version=version,  # pyright: ignore[reportArgumentType]
            attributes=merged,
        )

    return build.or_die()


def from_options(options: ResourceOptions | None) -> Effect[Resource]:
    """``from_config`` with the options an exporter was given."""
    given = options or {}
    return from_config(
        service_name=given.get("service_name"),
        service_version=given.get("service_version"),
        attributes=given.get("attributes"),
    )


def service_name_unsafe(resource: Resource) -> str:
    """The resource's ``service.name``; raises ``ValueError`` when it has no
    non-empty string one."""
    for attribute in resource["attributes"]:
        if attribute["key"] == "service.name":
            name = attribute["value"].get("stringValue")
            if name:
                return name
            break
    raise ValueError("Resource does not contain a service name")


def entries_to_attributes(entries: Iterable[tuple[str, object]]) -> list[KeyValue]:
    """Each ``(key, value)`` as an OTLP attribute."""
    return [{"key": key, "value": unknown_to_attribute_value(value)} for key, value in entries]


_INT64_BOUND = 2**63
_MAX_SAFE_INTEGER = 2**53 - 1


def _int_value(value: int) -> int | str:
    """An int64 as OTLP/JSON writes it: a number while JavaScript holds it
    exactly, decimal text past that."""
    return value if -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER else str(value)


def unknown_to_attribute_value(value: object) -> AnyValue:  # noqa: PLR0911
    """``value`` as an OTLP ``AnyValue``: lists and tuples item by item,
    strings and booleans as they are, an ``int`` in the int64 range as
    ``intValue`` (past it as ``stringValue``, as Effect writes a
    ``bigint``), a whole ``float`` in that range as ``intValue`` (a
    JavaScript number is an integer when whole), other floats as
    ``doubleValue``, and anything else as text (Effect's ``format``)."""
    match value:
        case list() | tuple():
            items = cast("Iterable[object]", value)
            return {"arrayValue": {"values": [unknown_to_attribute_value(v) for v in items]}}
        case str():
            return {"stringValue": value}
        case bool():
            return {"boolValue": value}
        case int():
            if -_INT64_BOUND <= value < _INT64_BOUND:
                return {"intValue": _int_value(value)}
            return {"stringValue": str(value)}
        case float():
            if value.is_integer() and -_INT64_BOUND <= value < _INT64_BOUND:
                return {"intValue": _int_value(int(value))}
            return {"doubleValue": value}
        case _:
            return {"stringValue": format_unknown(value)}
