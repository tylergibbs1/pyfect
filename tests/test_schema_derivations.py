"""``S.to_equivalence`` and ``S.to_formatter`` beyond Effect's titles:
behaviours the oracle ports leave unpinned."""

from typing import Any

from pyfect import schema as S
from pyfect.option import Some
from pyfect.schema import ast


def test_a_union_value_matches_a_member_only_when_both_values_do():
    always = S.String.override_to_equivalence(lambda: lambda a, b: True)
    equivalence = S.to_equivalence(S.Union(always, S.Number))
    assert equivalence("a", "b")
    assert not equivalence("a", 1)


def test_equals_keeps_booleans_apart_from_numbers_and_nan_equal():
    equivalence = S.to_equivalence(S.Unknown)
    assert not equivalence(True, 1)
    assert equivalence(float("nan"), float("nan"))
    assert equivalence(1, 1.0)


def _struct_with_rest() -> S.Bottom[Any, Any]:
    # A property also covered by an index signature (Effect's StructWithRest).
    return S.Bottom(
        ast.Objects(
            properties=(ast.PropertySignature("a", S.Number.ast),),
            index_signatures=(ast.IndexSignature(S.String.ast, S.Number.ast),),
        )
    )


def test_a_property_covered_by_an_index_signature_is_written_once():
    """Effect's ``StructWithRest`` title, on the node it builds."""
    assert S.to_formatter(_struct_with_rest())({"a": 1, "b": 2}) == '{ "a": 1, "b": 2 }'


def test_a_checked_declaration_keeps_its_formatter_and_equivalence():
    schema = S.Option(S.Number).check(S.make_filter(lambda _: True))
    assert S.to_formatter(schema)(Some(1)) == "some(1)"
    assert not S.to_equivalence(schema)(Some(1), None)
