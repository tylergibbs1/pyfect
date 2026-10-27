"""Ports of ``@effect/opentelemetry``'s ``Resource.test.ts``.

Each test's docstring is the Effect test title. ``Resource.Resource`` is
``otel.resource.OtelResource`` (``fx.Resource`` is pyfect's cached value).
The SDK's language is ``python``.

Adapted, with the reason:

- "preserves embedded equals signs and ignores empty attribute keys": the
  environment is ``os.environ`` (pytest's ``monkeypatch``), as pyfect has
  no ``ConfigProvider`` yet.
"""

import pytest

pytest.importorskip("opentelemetry.sdk")

import pyfect as fx
from pyfect import otel, testing
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
def test_preserves_embedded_equals_signs_and_ignores_empty_attribute_keys(
    monkeypatch: pytest.MonkeyPatch,
):
    """preserves embedded equals signs and ignores empty attribute keys"""
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "key=value,encoded=abc=def==, =ignored")
    resource = yield from OtelResource().pipe(fx.provide(otel.resource.layer_from_env()))
    assert resource.attributes["key"] == "value"
    assert resource.attributes["encoded"] == "abc=def=="
    assert "" not in resource.attributes
