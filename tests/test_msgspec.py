"""``pyfect.msgspec``: msgspec structs as pyfect schemas."""

import pytest

msgspec = pytest.importorskip("msgspec")

from pyfect import msgspec as M  # noqa: E402
from pyfect import schema as S  # noqa: E402
from pyfect.result import Err  # noqa: E402


class Item(msgspec.Struct):
    sku: str
    qty: int


class Box(msgspec.Struct):
    items: list[Item]


def _error(schema: S.Bottom[object, object], input: object) -> str:
    result = S.decode_unknown_result(schema)(input)
    assert isinstance(result, Err)
    return str(result.error)


def test_decodes_with_msgspec_and_encodes_to_builtins():
    schema = M.from_struct(Box)

    assert S.decode_unknown_sync(schema)({"items": [{"sku": "a", "qty": 1}]}) == Box([Item("a", 1)])
    assert S.encode_sync(schema)(Box([Item("a", 1)])) == {"items": [{"sku": "a", "qty": 1}]}


def test_reports_the_error_at_the_path_msgspec_gives():
    schema = M.from_struct(Box)

    assert _error(schema, {"items": [{"sku": "a", "qty": "x"}]}) == (
        'Expected `int`, got `str`\n  at ["items"][0]["qty"]'
    )
    assert _error(schema, {"items": [{"qty": 1}]}) == 'Missing key\n  at ["items"][0]["sku"]'
    assert _error(schema, {}) == 'Missing key\n  at ["items"]'


def test_composes_with_other_schemas():
    schema = S.Array(M.from_struct(Item))

    assert S.decode_unknown_sync(schema)([{"sku": "a", "qty": 1}]) == (Item("a", 1),)
    assert _error(schema, [{"sku": "a", "qty": 1}, {"sku": 1, "qty": 1}]) == (
        'Expected `str`, got `int`\n  at [1]["sku"]'
    )


def test_lax_mode_reads_numbers_from_strings():
    schema = M.from_struct(Item, strict=False)

    assert S.decode_unknown_sync(schema)({"sku": "a", "qty": "2"}) == Item("a", 2)
