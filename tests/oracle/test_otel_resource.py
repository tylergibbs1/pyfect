"""Ports of ``@effect/opentelemetry``'s ``opentelemetry/test/Resource.test.ts``.

Each test's docstring is the Effect test title. ``Resource.Resource`` is
``otel.resource.OtelResource`` (``fx.Resource`` is pyfect's cached value).
The SDK's language is ``python``.
"""

from typing import Any

import pytest

pytest.importorskip("opentelemetry.sdk")

import pyfect as fx
from pyfect import config_provider, otel, testing
from pyfect.otel.resource import OtelResource


def test_lets_custom_attributes_override_sdk_defaults_but_not_the_service_options():
    """lets custom attributes override SDK defaults but not the service options"""
    attributes = otel.resource.config_to_attributes(
        service_name="test",
        service_version="service-version",
        attributes={
            "service.name": "attribute-service",
            "telemetry.sdk.name": "custom",
            "telemetry.sdk.language": "webjs",
            "telemetry.sdk.version": "custom-version",
        },
    )
    assert attributes == {
        "service.name": "test",
        "service.version": "service-version",
        "telemetry.sdk.name": "custom",
        "telemetry.sdk.language": "webjs",
        "telemetry.sdk.version": "custom-version",
    }


@testing.effect
def test_preserves_embedded_equals_signs_and_ignores_empty_attribute_keys():
    """preserves embedded equals signs and ignores empty attribute keys"""
    env = {"OTEL_RESOURCE_ATTRIBUTES": "key=value,encoded=abc=def==, =ignored"}
    resource = yield from (
        OtelResource()
        .pipe(fx.provide(otel.resource.layer_from_env()))
        .pipe(fx.provide(config_provider.layer(config_provider.from_env(env))))
    )
    assert resource.attributes["key"] == "value"
    assert resource.attributes["encoded"] == "abc=def=="
    assert "" not in resource.attributes


def _resource(provider: config_provider.ConfigProvider, **attributes: str) -> fx.Effect[Any]:
    return (
        OtelResource()
        .pipe(fx.provide(otel.resource.layer_from_env(attributes or None)))
        .pipe(fx.provide(config_provider.layer(provider)))
    )


@testing.effect
def test_percent_decodes_attribute_keys_and_values_once():
    """percent-decodes attribute keys and values once"""
    text = (
        "message = hello%20world ,list=one%2Ctwo%3Dthree,"
        "%E5%9C%B0%E5%9F%9F=%E6%9D%B1%E4%BA%AC,percent=%2520"
    )
    resource = yield from _resource(config_provider.from_env({"OTEL_RESOURCE_ATTRIBUTES": text}))
    assert resource.attributes["message"] == "hello world"
    assert resource.attributes["list"] == "one,two=three"
    assert resource.attributes["地域"] == "東京"
    assert resource.attributes["percent"] == "%20"


@testing.effect
def test_keeps_empty_attribute_values_and_skips_entries_without_a_separator():
    """keeps empty attribute values and skips entries without a separator"""
    resource = yield from _resource(
        config_provider.from_env({"OTEL_RESOURCE_ATTRIBUTES": "empty=,novalue,a=1"})
    )
    assert resource.attributes["empty"] == ""
    assert resource.attributes["a"] == "1"
    assert "novalue" not in resource.attributes


@testing.effect
def test_accepts_structured_otel_resource_attributes():
    """accepts structured OTEL_RESOURCE_ATTRIBUTES"""
    resource = yield from _resource(
        config_provider.from_unknown(
            {"OTEL_RESOURCE_ATTRIBUTES": {"team": "platform", "service.version": "1.0.0"}}
        )
    )
    assert resource.attributes["team"] == "platform"
    assert resource.attributes["service.version"] == "1.0.0"


@testing.effect
def test_discards_otel_resource_attributes_with_malformed_percent_encoding():
    """discards OTEL_RESOURCE_ATTRIBUTES with malformed percent-encoding"""
    messages: list[object] = []
    env = {"OTEL_SERVICE_NAME": "env-service", "OTEL_RESOURCE_ATTRIBUTES": "valid=yes,cpu=50%"}
    resource = yield from _resource(config_provider.from_env(env), team="explicit").with_logger(
        fx.Logger.make(lambda options: messages.append(options.message))
    )
    assert resource.attributes.get("valid") is None
    assert resource.attributes.get("cpu") is None
    assert resource.attributes["service.name"] == "env-service"
    assert resource.attributes["team"] == "explicit"
    assert messages and "Discarding OTEL_RESOURCE_ATTRIBUTES" in str(messages[0])
