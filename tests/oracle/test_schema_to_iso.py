"""Ports of Effect's ``test/schema/toIso.test.ts`` and the ``toCodecIso`` section of
``toCodec.test.ts``. ``Schema.Date`` is a plain ``datetime`` declaration here, with no codec, as
Effect's ``Date`` has none for this family; ``ReadonlySet`` is ``S.FrozenSet``, ``ReadonlyMap``
``S.Map``.

Omitted: "Opaque", "Date": pyfect has no ``Schema.Opaque`` or ``Schema.Date`` to give them."""
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownLambdaType=false
# pyright: reportUnknownParameterType=false, reportMissingParameterType=false
# pyright: reportPrivateUsage=false

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import cause as C
from pyfect import schema as S
from pyfect.hash_map import HashMap
from pyfect.option import Some
from pyfect.schema import ast
from pyfect.schema import transformation as T

_Date = S.instance_of(datetime)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class Value(S.Class):
    a: datetime = S.field(_Date)


def _at(millis: int) -> Value:
    return Value(a=_date(millis))


def _date(millis: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=millis)


def _add_one(date: datetime) -> datetime:
    return date + timedelta(milliseconds=1)


def _add_two(date: datetime) -> datetime:
    return date + timedelta(milliseconds=2)


_ITEM: Any = S.to_iso_focus(Value).key("a")


def test_override_to_codec_iso() -> None:
    """Optic generation / overrideToCodecIso"""
    schema = S.URL.pipe(S.override_to_codec_iso(S.String, T.url_from_string))
    modify = S.to_iso(schema).modify(lambda s: s + "test")
    url = S.decode_unknown_sync(S.URLFromString)
    assert modify(url("https://example.com/")) == url("https://example.com/test")


class A(S.Class):
    value: Value


class B(S.Class):
    a: A


def test_class() -> None:
    """Optic generation / toIso / Class / Class"""
    modify = S.to_iso(B).key("a").key("value").key("a").modify(_add_one)
    assert modify(B(a=A(value=_at(0)))) == B(a=A(value=_at(1)))


def test_to_type_class() -> None:
    """Optic generation / toIso / toType(Class)"""
    modify = S.to_iso(S.to_type(Value)).key("a").modify(_add_one)
    assert modify(_at(0)) == _at(1)


def test_to_encoded_class() -> None:
    """Optic generation / toIso / toEncoded(Class)"""
    modify = S.to_iso(S.to_encoded(Value)).key("a").modify(_add_one)
    assert modify({"a": _date(0)}) == {"a": _date(1)}


def test_number_and_is_positive() -> None:
    """Optic generation / toIso / brand / Number & isPositive"""
    schema = S.Number.check(S.is_greater_than(0))
    modify = S.to_iso(schema).modify(lambda n: n - 1)
    assert modify(2) == 1
    with pytest.raises(S.SchemaError, match="Expected a value greater than 0"):
        modify(1)


def test_tuple() -> None:
    """Optic generation / toIso / Tuple"""
    schema = S.Tuple(Value, S.optional_key(Value))
    modify = S.to_iso(schema).key(0).key("a").modify(_add_one)
    assert modify((_at(0),)) == (_at(1),)


def test_array() -> None:
    """Optic generation / toIso / Array"""
    update = _ITEM.modify(_add_one)
    modify = S.to_iso(S.Array(Value)).modify(lambda items: [update(i) for i in items])
    assert list(modify((_at(0),))) == [_at(1)]


def _first_and_rest(items: Any) -> list[Any]:
    first, *rest = items
    return [_ITEM.modify(_add_one)(first), *map(_ITEM.modify(_add_two), rest)]


def test_non_empty_array() -> None:
    """Optic generation / toIso / NonEmptyArray"""
    modify = S.to_iso(S.NonEmptyArray(Value)).modify(_first_and_rest)
    assert list(modify((_at(0), _at(1), _at(2)))) == [_at(1), _at(3), _at(4)]


def test_tuple_with_rest() -> None:
    """Optic generation / toIso / TupleWithRest"""
    modify = S.to_iso(S.TupleWithRest(S.Tuple(Value), Value)).modify(_first_and_rest)
    assert list(modify((_at(0), _at(1), _at(2)))) == [_at(1), _at(3), _at(4)]


class _Fields(TypedDict):
    value: Value
    optionalValue: NotRequired[Value]


def test_struct() -> None:
    """Optic generation / toIso / Struct"""
    modify = S.to_iso(S.Struct(_Fields)).key("value").key("a").modify(_add_one)
    assert modify({"value": _at(0)}) == {"value": _at(1)}
    assert modify({"value": _at(0), "optionalValue": _at(2)}) == {
        "value": _at(1),
        "optionalValue": _at(2),
    }


def test_record() -> None:
    """Optic generation / toIso / Record"""
    update = _ITEM.modify(_add_one)
    modify = S.to_iso(S.Record(S.String, Value)).modify(
        lambda rec: {k: update(v) for k, v in rec.items()}
    )
    assert modify({"a": _at(0), "b": _at(1)}) == {"a": _at(1), "b": _at(2)}


class _A(TypedDict):
    a: Value


def test_struct_with_rest() -> None:
    """Optic generation / toIso / StructWithRest"""
    schema = S.StructWithRest(S.Struct(_A), S.Record(S.String, Value))

    def f(rec: Any) -> Any:
        return {
            k: (_ITEM.modify(_add_one) if k == "a" else _ITEM.modify(_add_two))(v)
            for k, v in rec.items()
        }

    modify: Any = S.to_iso(schema).modify(f)
    assert modify({"a": _at(0), "b": _at(1)}) == {"a": _at(1), "b": _at(3)}


def test_union() -> None:
    """Optic generation / toIso / Union"""
    update = _ITEM.modify(_add_one)
    modify: Any = S.to_iso(S.Union(S.String, Value)).modify(
        lambda x: x if isinstance(x, str) else update(x)
    )
    assert modify("a") == "a"
    assert modify(_at(0)) == _at(1)


class _Node(TypedDict):
    a: Value
    children: Any


_NODE: Any = S.Struct(_Node, children=S.Array(S.suspend(lambda: _NODE)))


def test_suspend() -> None:
    """Optic generation / toIso / suspend"""
    update = _ITEM.modify(_add_one)

    def f(node: Any) -> Any:
        return {"a": update(node["a"]), "children": [f(c) for c in node["children"]]}

    modify = S.to_iso(_NODE).modify(f)
    assert modify({"a": _at(0), "children": ({"a": _at(1), "children": ()},)}) == {
        "a": _at(1),
        "children": ({"a": _at(2), "children": ()},),
    }


def test_flip_schema() -> None:
    """Optic generation / toIso / flip(schema)"""
    modify: Any = S.to_iso(S.flip(Value)).key("a").modify(_add_one)
    assert modify(_at(0)) == {"a": _date(1)}


def test_flip_flip_schema() -> None:
    """Optic generation / toIso / flip(flip(schema))"""
    modify = S.to_iso(S.flip(S.flip(Value))).key("a").modify(_add_one)
    assert modify(_at(0)) == _at(1)


def test_option() -> None:
    """Optic generation / toIso / Option"""
    modify = S.to_iso(S.Option(Value)).tag("Some").key("value").key("a").modify(_add_one)
    assert modify(Some(_at(0))) == Some(_at(1))
    assert modify(None) is None


def test_result() -> None:
    """Optic generation / toIso / Result"""
    modify = (
        S.to_iso(S.Result(Value, Value)).tag("Success").key("success").key("a").modify(_add_one)
    )
    assert modify(fx.Ok(_at(0))) == fx.Ok(_at(1))


def test_cause_reason() -> None:
    """Optic generation / toIso / CauseReason"""
    schema = S.CauseReason(Value, S.Defect())
    modify = S.to_iso(schema).tag("Fail").key("error").key("a").modify(_add_one)
    assert modify(C.Fail(_at(0))) == C.Fail(_at(1))


def test_cause() -> None:
    """Optic generation / toIso / Cause"""
    failure: Any = S.to_iso_focus(S.CauseReason(Value, Value)).tag("Fail").key("error").key("a")
    update = failure.modify(_add_one)
    modify = S.to_iso(S.Cause(Value, Value)).modify(lambda rs: [update(r) for r in rs])
    assert modify(C.fail(_at(0))) == C.fail(_at(1))


def test_error() -> None:
    """Optic generation / toIso / Error"""
    modify = S.to_iso(S.ErrorInstance).modify(lambda e: RuntimeError(f"{e}!"))
    out = modify(RuntimeError("a"))
    assert str(out) == "a!"


def test_exit() -> None:
    """Optic generation / toIso / Exit"""
    schema = S.Exit(Value, S.ErrorInstance, S.Defect())
    modify = S.to_iso(schema).tag("Success").key("value").key("a").modify(_add_one)
    assert modify(fx.Success(_at(0))) == fx.Success(_at(1))


def test_readonly_set() -> None:
    """Optic generation / toIso / ReadonlySet"""
    update = _ITEM.modify(_add_one)
    modify = S.to_iso(S.FrozenSet(Value)).modify(lambda items: [update(i) for i in items])
    assert modify(frozenset({_at(0)})) == frozenset({_at(1)})


def test_readonly_map() -> None:
    """Optic generation / toIso / ReadonlyMap"""
    entry: Any = S.to_iso_focus(S.Tuple(S.String, Value)).key(1).key("a")
    update = entry.modify(_add_one)
    modify = S.to_iso(S.Map(S.String, Value)).modify(lambda es: [update(tuple(e)) for e in es])
    assert modify({"a": _at(0)}) == {"a": _at(1)}


def test_hash_map() -> None:
    """Optic generation / toIso / HashMap"""
    entry: Any = S.to_iso_focus(S.Tuple(S.String, Value)).key(1).key("a")
    update = entry.modify(_add_one)
    modify = S.to_iso(S.HashMap(S.String, Value)).modify(lambda es: [update(tuple(e)) for e in es])
    assert modify(HashMap.make(("a", _at(0)))).to_entries() == [("a", _at(1))]


class _UrlField(TypedDict):
    a: NotRequired[Any]


def test_does_not_propagate_constructor_defaults_to_the_canonical_encoding() -> None:
    """toCodecIso / does not propagate constructor defaults to the canonical encoding"""
    url = S.decode_unknown_sync(S.URLFromString)("https://example.com")
    field = (
        S.URL.pipe(S.override_to_codec_iso(S.String, T.url_from_string))
        .annotate_key(description="a")
        .pipe(S.with_constructor_default(fx.succeed(url)))
    )
    derived = S.to_codec_iso(S.Struct(_UrlField, a=field)).ast
    assert isinstance(derived, ast.Objects)
    node = derived.properties[0].type
    assert node.constructor_default is not None
    encoded = node
    while encoded.encoding is not None:
        encoded = encoded.encoding[-1].to
    assert encoded.constructor_default is None
    assert encoded.key_annotations == {"description": "a"}
