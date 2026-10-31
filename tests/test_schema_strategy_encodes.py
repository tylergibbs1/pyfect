"""``to_strategy`` draws only values its schema encodes (QA schema-data
F14): a float under ``from_json_string`` is never ``NaN`` or infinite,
which the JSON text has no form for."""

from __future__ import annotations

from typing import Any, TypedDict

import pytest
from hypothesis import HealthCheck, given, settings

from pyfect import schema as S


class _Point(TypedDict):
    a: float


def _check_draws_encode(schema: Any) -> None:
    encode = S.encode_sync(schema)

    @settings(
        max_examples=60,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
        database=None,
    )
    @given(S.to_strategy(schema))
    def check(value: object) -> None:
        encode(value)

    check()


def test_a_json_string_of_a_float_field_draws_only_finite_floats():
    _check_draws_encode(S.from_json_string(S.Struct(_Point)))


def test_unknown_from_json_string_draws_only_json_values():
    _check_draws_encode(S.UnknownFromJsonString)


def _catalog() -> list[tuple[str, Any]]:
    return [(name, value) for name in dir(S) if isinstance(value := getattr(S, name), S.Bottom)]


@pytest.mark.parametrize(("name", "schema"), _catalog())
def test_every_catalog_schema_draws_values_it_encodes(name: str, schema: Any):
    """The guard: whatever a schema's strategy draws, the schema encodes."""
    try:
        S.to_strategy(schema)
    except (TypeError, ValueError):
        pytest.skip(f"{name} has no strategy")
    _check_draws_encode(schema)
