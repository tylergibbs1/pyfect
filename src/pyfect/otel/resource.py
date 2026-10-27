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
from pyfect.context import Tag
from pyfect.layer import Layer
from pyfect.option import Option, Some
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


def _env_attributes(text: str) -> dict[str, AttributeValue]:
    """``OTEL_RESOURCE_ATTRIBUTES``: comma-separated ``key=value`` pairs,
    split at the first ``=``; pairs without one or with an empty key are
    skipped."""
    attributes: dict[str, AttributeValue] = {}
    for pair in text.split(","):
        key, eq, value = pair.partition("=")
        if eq and key.strip():
            attributes[key.strip()] = value.strip()
    return attributes


def layer_from_env(
    additional_attributes: Mapping[str, AttributeValue] | None = None,
) -> Layer[OtelResource]:
    """A resource from the SDK defaults, then ``OTEL_RESOURCE_ATTRIBUTES``
    and ``OTEL_SERVICE_NAME`` (read through the ``CurrentConfigProvider``
    when the layer builds; a config error is a defect), then
    ``additional_attributes``, later ones winning."""

    def make(service_name: Option[str], text: str) -> Resource:
        attributes = _env_attributes(text)
        if isinstance(service_name, Some):
            attributes["service.name"] = service_name.value
        return Resource({**_sdk_attributes(), **attributes, **(additional_attributes or {})})

    read = config.all(
        config.option(config.string("OTEL_SERVICE_NAME")),
        config.string("OTEL_RESOURCE_ATTRIBUTES").with_default(""),
    )
    return _layer.effect(OtelResource, read.map(lambda pair: make(*pair)).or_die())


layer_empty: Final[Layer[OtelResource]] = _layer.succeed(OtelResource, Resource.get_empty())
"""A resource with no attributes."""
