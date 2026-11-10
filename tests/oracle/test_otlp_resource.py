"""Ports of Effect's ``OtlpResource.test.ts``.

Each test's docstring is the Effect test title. The SDK attributes name
pyfect and Python (``telemetry.sdk.name`` ``pyfect``,
``telemetry.sdk.language`` ``python``) where Effect's name Effect and
Node. A JavaScript number is a ``float`` and a ``bigint`` an ``int``.
"""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import config_provider, layer
from pyfect._version import VERSION
from pyfect.observability import otlp_resource
from pyfect.observability.otlp_resource import Resource

SDK = {
    "telemetry.sdk.name": "pyfect",
    "telemetry.sdk.language": "python",
    "telemetry.sdk.version": VERSION,
}


def _attributes(resource: Resource) -> dict[str, Any]:
    return {
        attribute["key"]: attribute["value"].get("stringValue")
        for attribute in resource["attributes"]
    }


def _from_config(env: dict[str, str], **options: Any) -> fx.Effect[Resource]:
    provider = config_provider.layer(config_provider.from_env(env))
    return otlp_resource.from_config(**options).pipe(layer.provide(provider))


def test_decodes_percent_encoded_otel_resource_attributes() -> None:
    """fromConfig decodes percent-encoded OTEL_RESOURCE_ATTRIBUTES"""
    resource = fx.run_sync(
        _from_config(
            {
                "OTEL_SERVICE_NAME": "repro",
                "OTEL_RESOURCE_ATTRIBUTES": "message=hello%20world,comma=comma%2Cvalue",
            }
        )
    )
    attributes = _attributes(resource)
    assert attributes["message"] == "hello world"
    assert attributes["comma"] == "comma,value"


def test_trims_otel_resource_attributes_entries_and_keeps_empty_values() -> None:
    """fromConfig trims OTEL_RESOURCE_ATTRIBUTES entries and keeps empty values"""
    resource = fx.run_sync(
        _from_config(
            {
                "OTEL_SERVICE_NAME": "env-service",
                "OTEL_RESOURCE_ATTRIBUTES": "message = hello%20world ,empty=,novalue, =ignored,a=1",
            }
        )
    )
    assert _attributes(resource) == {
        **SDK,
        "service.name": "env-service",
        "message": "hello world",
        "empty": "",
        "a": "1",
    }


def test_uses_explicit_service_options_before_attributes_and_environment_variables() -> None:
    """fromConfig uses explicit service options before attributes and environment variables"""
    resource = fx.run_sync(
        _from_config(
            {
                "OTEL_SERVICE_NAME": "env-service",
                "OTEL_SERVICE_VERSION": "env-version",
                "OTEL_RESOURCE_ATTRIBUTES": (
                    "service.name=env-attribute-service,service.version=env-attribute-version"
                ),
            },
            service_name="explicit-service",
            service_version="explicit-version",
            attributes={
                "custom.attribute": "explicit",
                "service.name": "explicit-attribute-service",
                "service.version": "explicit-attribute-version",
            },
        )
    )
    assert _attributes(resource) == {
        **SDK,
        "custom.attribute": "explicit",
        "service.name": "explicit-service",
        "service.version": "explicit-version",
    }


def test_uses_explicit_attributes_before_environment_variables() -> None:
    """fromConfig uses explicit attributes before environment variables"""
    resource = fx.run_sync(
        _from_config(
            {
                "OTEL_SERVICE_NAME": "env-service",
                "OTEL_SERVICE_VERSION": "env-version",
                "OTEL_RESOURCE_ATTRIBUTES": (
                    "service.name=env-attribute-service,"
                    "service.version=env-attribute-version,custom.attribute=env"
                ),
            },
            attributes={
                "custom.attribute": "explicit",
                "service.name": "explicit-attribute-service",
                "service.version": "explicit-attribute-version",
            },
        )
    )
    assert _attributes(resource) == {
        **SDK,
        "custom.attribute": "explicit",
        "service.name": "explicit-attribute-service",
        "service.version": "explicit-attribute-version",
    }


def test_uses_dedicated_service_variables_before_otel_resource_attributes() -> None:
    """fromConfig uses dedicated service variables before OTEL resource attributes"""
    resource = fx.run_sync(
        _from_config(
            {
                "OTEL_SERVICE_NAME": "env-service",
                "OTEL_SERVICE_VERSION": "env-version",
                "OTEL_RESOURCE_ATTRIBUTES": (
                    "service.name=env-attribute-service,service.version=env-attribute-version"
                ),
            }
        )
    )
    assert _attributes(resource) == {
        **SDK,
        "service.name": "env-service",
        "service.version": "env-version",
    }


def test_omits_service_version_when_it_is_not_configured() -> None:
    """fromConfig omits service.version when it is not configured"""
    resource = fx.run_sync(_from_config({}, service_name="explicit-service"))
    assert _attributes(resource) == {**SDK, "service.name": "explicit-service"}


def test_dies_when_no_service_name_is_configured() -> None:
    """fromConfig dies when no service name is configured"""
    exit = fx.run_sync(_from_config({}).exit())
    assert isinstance(exit, fx.Failure)
    assert exit.cause.has_dies
    assert "OTEL_SERVICE_NAME" in exit.cause.pretty()


def test_lets_custom_attributes_override_sdk_defaults_and_service_options_override_attributes() -> (
    None
):
    """lets custom attributes override SDK defaults and service options override attributes"""
    resource = otlp_resource.make(
        service_name="test",
        service_version="1.0.0",
        attributes={
            "telemetry.sdk.name": "custom",
            "telemetry.sdk.language": "webjs",
            "telemetry.sdk.version": "custom-version",
            "service.name": "attribute-service",
            "service.version": "attribute-version",
        },
    )
    assert resource["attributes"] == [
        {"key": "telemetry.sdk.name", "value": {"stringValue": "custom"}},
        {"key": "telemetry.sdk.language", "value": {"stringValue": "webjs"}},
        {"key": "telemetry.sdk.version", "value": {"stringValue": "custom-version"}},
        {"key": "service.name", "value": {"stringValue": "test"}},
        {"key": "service.version", "value": {"stringValue": "1.0.0"}},
    ]


def test_preserves_bigint_attribute_precision() -> None:
    """unknownToAttributeValue preserves bigint attribute precision"""
    value = 9_007_199_254_740_993
    assert str(otlp_resource.unknown_to_attribute_value(value).get("intValue")) == str(value)


def test_keeps_integers_outside_the_int64_range_out_of_int_value() -> None:
    """unknownToAttributeValue keeps integers outside the int64 range out of intValue"""
    convert = otlp_resource.unknown_to_attribute_value
    assert convert(float(2**63)) == {"doubleValue": float(2**63)}
    assert convert(-9_223_372_036_854_778_000.0) == {"doubleValue": -9_223_372_036_854_778_000.0}
    assert convert(9_223_372_036_854_775_808) == {"stringValue": "9223372036854775808"}
    assert convert(-9_223_372_036_854_775_809) == {"stringValue": "-9223372036854775809"}
