"""The OpenTelemetry resource: what process or service emits the spans,
logs and metrics (Effect's ``Resource``).

``layer(service_name=...)`` builds one from service metadata;
``layer_from_env()`` reads ``OTEL_SERVICE_NAME`` and
``OTEL_RESOURCE_ATTRIBUTES`` through ``Config``; ``layer_empty`` has no
attributes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from opentelemetry.sdk.resources import Resource
from opentelemetry.util.types import AttributeValue

from pyfect import config
from pyfect import layer as _layer
from pyfect.config import ConfigError
from pyfect.context import Tag
from pyfect.effect import Effect, gen
from pyfect.layer import Layer
from pyfect.logger import log_warning
from pyfect.observability._resource_attributes import resource_attributes
from pyfect.option import Some
from pyfect.otel._attributes import PYFECT_VERSION

__all__ = ["OtelResource", "config_to_attributes", "layer", "layer_empty", "layer_from_env"]


class OtelResource(Tag[Resource]):
    """The resource attached to everything the bridge exports."""


def _sdk_attributes() -> dict[str, AttributeValue]:
    return {
        "telemetry.sdk.name": "pyfect",
        "telemetry.sdk.language": "python",
        "telemetry.sdk.version": PYFECT_VERSION,
    }


def config_to_attributes(
    *,
    service_name: str,
    service_version: str | None = None,
    attributes: Mapping[str, AttributeValue] | None = None,
) -> dict[str, AttributeValue]:
    """The SDK defaults, then ``attributes``, then the service name and
    version (an empty version counts as none), later ones winning."""
    merged: dict[str, AttributeValue] = {
        **_sdk_attributes(),
        **(attributes or {}),
        "service.name": service_name,
    }
    if service_version:
        merged["service.version"] = service_version
    return merged


def layer(
    *,
    service_name: str,
    service_version: str | None = None,
    attributes: Mapping[str, AttributeValue] | None = None,
) -> Layer[OtelResource]:
    """A resource made from ``config_to_attributes``."""
    return _layer.succeed(
        OtelResource,
        Resource(
            config_to_attributes(
                service_name=service_name,
                service_version=service_version,
                attributes=attributes,
            )
        ),
    )


def _discard(error: ConfigError) -> Effect[dict[str, str]]:
    empty: dict[str, str] = {}
    return log_warning("Discarding OTEL_RESOURCE_ATTRIBUTES", error).as_(empty)


def layer_from_env(
    additional_attributes: Mapping[str, AttributeValue] | None = None,
) -> Layer[OtelResource]:
    """A resource from the SDK defaults, then ``OTEL_RESOURCE_ATTRIBUTES``,
    then ``OTEL_SERVICE_NAME``, then ``additional_attributes``, later ones
    winning (read through the ``CurrentConfigProvider`` when the layer
    builds; a config error is a defect).

    ``OTEL_RESOURCE_ATTRIBUTES`` may be a record node or a ``key=value``
    list: keys and values trimmed, then percent-decoded once; an empty value
    is kept as ``""``; a pair without ``=`` or with an empty key is skipped.
    Invalid percent-encoding discards the whole variable with a warning."""

    @gen
    def build():
        service_name = yield from config.option(config.string("OTEL_SERVICE_NAME"))
        empty: dict[str, str] = {}
        attributes = yield from resource_attributes().with_default(empty).catch_all(_discard)
        named: dict[str, AttributeValue] = (
            {"service.name": service_name.value} if isinstance(service_name, Some) else {}
        )
        return Resource(
            {**_sdk_attributes(), **attributes, **named, **(additional_attributes or {})}
        )

    return _layer.effect(OtelResource, build.or_die())


layer_empty: Final[Layer[OtelResource]] = _layer.succeed(OtelResource, Resource.get_empty())
"""A resource with no attributes."""
