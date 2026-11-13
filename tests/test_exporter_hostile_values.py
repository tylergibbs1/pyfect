"""(pyfect) One attribute value never stops a telemetry exporter from writing its batch.

The DevTools client had no JSON form for an exception without ``to_json``, so the whole batch
it was in was not sent. Effect writes such a value with ``JSON.stringify``: an object as its
own enumerable properties. Every exporter's encoding of an attribute value is run here over
values with no JSON form of their own, and must give JSON text.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any

import pytest

from pyfect import _json_text
from pyfect.devtools import client as devtools_client
from pyfect.observability import otlp_resource, otlp_serialization


class _Fields(Exception):
    def __init__(self) -> None:
        super().__init__("boom")
        self.code = 7


def _cycle() -> list[object]:
    items: list[object] = []
    items.append(items)
    return items


class _Slots:
    __slots__ = ("a",)


def _function() -> None:
    return None


_HOSTILE: list[Callable[[], object]] = [
    lambda: ValueError("no fields"),
    _Fields,
    object,
    _Slots,
    _cycle,
    lambda: {"nested": [_Fields(), {1, 2}]},
    lambda: math.nan,
    lambda: {1, 2},
    lambda: b"\x00\xff",
    lambda: (i for i in range(2)),
    lambda: _function,
    lambda: 10**400,
]


def _devtools(value: object) -> str:
    attributes = devtools_client._json_attributes({"v": value})  # pyright: ignore[reportPrivateUsage]
    return _json_text.js_stringify(attributes)


def _otlp(value: object) -> str:
    any_value = otlp_resource.unknown_to_attribute_value(value)
    body: Any = otlp_serialization._json_body({"value": any_value})  # pyright: ignore[reportPrivateUsage]
    return body.body.decode()


_EXPORTERS: dict[str, Callable[[object], str]] = {"devtools": _devtools, "otlp_json": _otlp}


@pytest.mark.parametrize("exporter", _EXPORTERS)
@pytest.mark.parametrize("make", _HOSTILE)
def test_every_exporter_writes_any_attribute_value(exporter: str, make: Callable[[], object]):
    """(pyfect) every exporter writes a value with no JSON form as JSON, never raising"""
    json.loads(_EXPORTERS[exporter](make()))


def test_an_object_is_written_as_its_fields_as_json_stringify_writes_it():
    """(pyfect) an exception or object with no ``to_json`` is its own fields, as
    ``JSON.stringify`` writes an object's enumerable properties"""
    assert _json_text.js_json_value(_Fields()) == {"code": 7}
    assert _json_text.js_json_value(ValueError("x")) == {}
    assert _json_text.js_json_value({"a": [object(), math.inf]}) == {"a": [{}, None]}
