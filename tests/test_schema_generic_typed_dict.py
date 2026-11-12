"""A parameterized generic TypedDict (``Body[Inner]``) is a struct of its keys with the type
arguments in place, whether ``S.Struct`` derives every key, is given some, or meets it as
another key's annotation. ``get_type_hints`` of such an alias is empty, so ``Body[int]``
used to be a struct with no keys (accepting anything) and naming a key raised
``TypeError: Body has no key 'body'`` (FINDINGS-lantern #1)."""

from __future__ import annotations

import ast
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from typing import NotRequired, TypedDict

import pytest

from pyfect import schema as S
from pyfect.testing import SchemaAsserts


class Prefix(TypedDict):
    network: IPv4Network | IPv6Network


class Body[T](TypedDict):
    body: T


class Page[T](TypedDict, total=False):
    items: list[T]
    next: NotRequired[T | None]


class Envelope(TypedDict):
    count: Body[int]


def test_derived_keys_take_the_type_arguments() -> None:
    decoding = SchemaAsserts(S.Struct(Body[int])).decoding()
    decoding.succeed({"body": 1})
    decoding.fail({"body": "x"}, 'Expected number\n  at ["body"]')
    decoding.fail({}, 'Missing key\n  at ["body"]')


def test_a_key_given_its_own_schema() -> None:
    schema = S.Struct(Body[Prefix], body=S.Struct(Prefix, network=S.IpNetworkFromString))
    decoded = S.decode_unknown_sync(schema)({"body": {"network": "10.0.0.0/8"}})
    assert decoded == {"body": {"network": IPv4Network("10.0.0.0/8")}}


def test_a_key_the_generic_lacks_is_still_refused() -> None:
    with pytest.raises(TypeError, match="has no key 'other'"):
        S.Struct(Body[int], other=S.String)


def test_optional_keys_and_nested_arguments() -> None:
    decoding = SchemaAsserts(S.Struct(Page[str])).decoding()
    decoding.succeed({})
    decoding.succeed({"items": ["a"], "next": None})
    decoding.fail({"items": [1]}, 'Expected string\n  at ["items"][0]')


def test_a_key_annotated_with_a_parameterized_generic() -> None:
    decoding = SchemaAsserts(S.Struct(Envelope)).decoding()
    decoding.succeed({"count": {"body": 1}})
    decoding.fail({"count": {"body": "x"}}, 'Expected number\n  at ["count"]["body"]')


SCHEMA = Path(S.__file__).parent
TYPED_DICT_HINTS = "_derive.py"


def test_only_typed_dict_hints_reads_a_typed_dicts_annotations() -> None:
    """Every TypedDict reader goes through ``typed_dict_hints``, which substitutes a generic's
    type arguments; ``get_type_hints`` of the alias is silently empty."""
    found = [
        f"{path.relative_to(SCHEMA)}:{node.lineno}"
        for path in sorted(SCHEMA.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "get_type_hints"
        and path.name != TYPED_DICT_HINTS
        and not _reads_a_class_field(path)
    ]
    assert not found, f"read TypedDict annotations with typed_dict_hints: {found}"


def _reads_a_class_field(path: Path) -> bool:
    # ``S.Class`` resolves one field's annotation on a holder class, never a TypedDict.
    return path.name == "_class.py" and path.parent == SCHEMA
