"""Structs, records and tuples at their edges: slotted objects as inputs,
flipped and type sides, missing keys and positions, effectful keys and
values, and the input an issue keeps under ``report_input``."""

from collections.abc import Iterator, Mapping
from typing import Any, NotRequired, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.cause import Cause, Die, Fail
from pyfect.exit import Exit, Failure
from pyfect.option import Some
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import Composite, InvalidValue
from pyfect.testing import SchemaAsserts


class _X(TypedDict):
    x: float


class _Text(TypedDict):
    x: str


class _MaybeX(TypedDict):
    x: NotRequired[float]


def _error(exit: Exit[Any, S.SchemaError]) -> S.SchemaError:
    assert isinstance(exit, Failure)
    return next(r.error for r in exit.cause.reasons if isinstance(r, Fail))


def _issue_input(exit: Exit[Any, S.SchemaError]) -> object:
    """The input the failure's top issue keeps."""
    issue = _error(exit).issue
    assert isinstance(issue, Composite)
    return issue.input


def _decoding[V](getter: G.Getter[V, V]) -> T.Transformation[V, V]:
    return T.Transformation(getter, G.passthrough())


def _later(value: str, _: S.ParseOptions) -> fx.Effect[str]:
    return fx.yield_now().as_(value)


def _bad_later(_value: float, _: S.ParseOptions) -> fx.Effect[float, InvalidValue]:
    return fx.yield_now().and_then(fx.fail(InvalidValue({"message": "bad"})))


def _bad_key(_value: str, _: S.ParseOptions) -> fx.Effect[str, InvalidValue]:
    return fx.fail(InvalidValue({"message": "bad key"}))


_MIXED = Cause((Fail(InvalidValue({"message": "bad"})), Die(RuntimeError("defect"))))


def _mixed(_value: str, _: S.ParseOptions) -> fx.Effect[str, InvalidValue]:
    return fx.fail_cause(_MIXED)


_FAILS_WITH_A_DEFECT = S.String.pipe(S.decode(_decoding(G.transform_effect(_mixed))))


# ------------------------------------------------------- slotted objects


class _Slotted:
    __slots__ = ("__weakref__", "a", "b")

    def __init__(self, a: object, b: object | None = None) -> None:
        self.a = a
        if b is not None:
            self.b = b


class _OneSlot:
    __slots__ = "value"  # noqa: PLC0205 - a string names one slot

    def __init__(self, value: object) -> None:
        self.value = value


class _Redeclared(_OneSlot):
    __slots__ = ("value",)


def test_a_slotted_object_is_read_by_its_set_slots():
    # ``b`` unset and ``__weakref__`` are no keys of the object.
    record = S.Record(S.String, S.Number)
    asserts = SchemaAsserts(record).decoding()
    asserts.succeed(_Slotted(1.0), {"a": 1.0})
    asserts.succeed(_Slotted(1.0, 2.0), {"a": 1.0, "b": 2.0})
    asserts.succeed(_OneSlot(1.0), {"value": 1.0})


def test_a_slot_declared_twice_is_one_key():
    SchemaAsserts(S.Record(S.String, S.Number)).decoding(errors="all").fail(
        _Redeclared("x"), 'Expected number\n  at ["value"]'
    )


# ------------------------------------------------------- flip and type side


def test_a_struct_record_and_tuple_that_flip_to_themselves_are_their_own_flip():
    # A TypedDict of its own: a struct's node (and its flip) is made once per TypedDict.
    class Own(TypedDict):
        x: float

    for schema in (S.Struct(Own), S.Record(S.String, S.Number), S.Tuple(S.String)):
        assert schema.ast.flip() is schema.ast


def test_flipped_composites_check_the_values_they_encode_from():
    # Encoding a flipped schema decodes: its checks see the decoded value.
    def x_not_three(value: _X) -> bool:
        return value["x"] != 3

    not_three = S.make_filter(x_not_three, expected="not 3")
    struct = S.Struct(_X, x=S.NumberFromString).check(not_three)
    SchemaAsserts(S.flip(struct)).encoding().fail({"x": "3"}, "Expected not 3")

    def first_not_three(value: tuple[float]) -> bool:
        return value[0] != 3

    tuple_ = S.Tuple(S.NumberFromString).check(S.make_filter(first_not_three, expected="not 3"))
    SchemaAsserts(S.flip(tuple_)).encoding().fail(["3"], "Expected not 3")


def test_a_flipped_struct_keeps_an_optional_key_optional_on_its_encoded_side():
    defaulted = S.Number.pipe(S.with_decoding_default_key(fx.succeed(5.0)))
    flipped = S.flip(S.Struct(_MaybeX, x=defaulted))
    assert "required" not in S.to_json_schema_document(flipped).schema


def test_the_type_side_of_a_record_decodes_keys_and_values_as_types():
    values = S.to_type(S.Record(S.String, S.NumberFromString))
    assert S.decode_unknown_sync(values)({"a": 1.0}) == {"a": 1.0}
    keys = S.to_type(S.Record(S.NumberFromString, S.String))
    assert S.decode_unknown_sync(keys)({1.0: "a"}) == {1.0: "a"}
    rest = S.to_type(
        S.StructWithRest(S.Struct(_X, x=S.NumberFromString), S.Record(S.String, S.NumberFromString))
    )
    assert S.decode_unknown_sync(rest)({"x": 1.0, "y": 2.0}) == {"x": 1.0, "y": 2.0}


# ------------------------------------------------------------ struct keys


def test_strict_parsing_lists_a_records_keys_before_reading_any_property():
    order: list[str] = []

    class Logged(Mapping[str, object]):
        def __init__(self, items: dict[str, object]) -> None:
            self._data = items

        def __getitem__(self, key: str) -> object:
            return self._data[key]

        def __iter__(self) -> Iterator[str]:
            order.append("keys")
            return iter(self._data)

        def __len__(self) -> int:
            return len(self._data)

    def logged(value: str, _: object) -> fx.Effect[str]:
        order.append("x")
        return fx.succeed(value)

    x = S.String.pipe(S.decode(_decoding(G.transform_effect(logged))))
    schema = S.StructWithRest(S.Struct(_Text, x=x), S.Record(S.String, S.String))
    decode = S.decode_unknown_sync(schema)
    decode(Logged({"x": "1", "y": "2"}), on_excess_property="error")
    assert order.index("keys") < order.index("x")
    order.clear()
    decode(Logged({"x": "1", "y": "2"}))
    assert order == ["x", "keys"]


def test_a_missing_suspended_key_takes_its_decoding_default():
    defaulted = S.Number.pipe(S.with_decoding_default_key(fx.succeed(5.0)))
    schema = S.Struct(_X, x=S.suspend(lambda: defaulted))
    SchemaAsserts(schema).decoding().succeed({}, {"x": 5.0})


def test_a_missing_key_whose_transformation_yields_nothing_takes_its_message():
    schema = S.Struct(_X, x=S.NumberFromString.annotate_key(message_missing_key="need x"))
    SchemaAsserts(schema).decoding().fail({}, 'need x\n  at ["x"]')


def test_a_struct_reports_a_non_object_input():
    SchemaAsserts(S.Struct(_X)).decoding(report_input=True).fail(1, "Expected object, got 1")


# ----------------------------------------------------------- record entries


def test_effectful_record_keys_and_values_keep_their_keys():
    later_key = S.String.pipe(S.decode(_decoding(G.transform_effect(_later))))
    bad_value = S.Number.pipe(S.decode(_decoding(G.transform_effect(_bad_later))))
    decoded = fx.run_sync(
        S.decode_unknown_effect(S.Record(later_key, S.Number))({"a": 1.0}).or_die()
    )
    assert decoded == {"a": 1.0}
    failed = fx.run_sync_exit(S.decode_unknown_effect(S.Record(S.String, bad_value))({"a": 1.0}))
    assert _error(failed).message == 'bad\n  at ["a"]'


def test_a_record_key_that_fails_to_decode_is_reported_at_that_key():
    key = S.String.pipe(S.decode(_decoding(G.transform_effect(_bad_key))))
    SchemaAsserts(S.Record(key, S.Number)).decoding().fail({"a": 1.0}, 'bad key\n  at ["a"]')


def test_disabled_checks_let_a_record_take_a_key_its_checks_refuse():
    record = S.Record(S.String.check(S.is_min_length(2)), S.Number)
    SchemaAsserts(record).decoding(disable_checks=True).succeed({"a": 1.0})


def test_a_record_drops_a_value_that_encodes_to_nothing():
    record = S.Record(S.String, S.OptionFromOptionalKey(S.Number))
    SchemaAsserts(record).encoding().succeed({"a": None, "b": Some(1.0)}, {"b": 1.0})


# ------------------------------------------------------------ tuple positions


def test_an_optional_element_may_come_before_the_rest():
    schema = S.TupleWithRest(S.Tuple(S.optional_key(S.String)), S.Number)
    SchemaAsserts(schema).decoding().succeed(["a", 1.0, 2.0], ("a", 1.0, 2.0))


def test_a_missing_optional_element_whose_transformation_yields_nothing_is_left_out():
    SchemaAsserts(S.Tuple(S.optional_key(S.NumberFromString))).decoding().succeed([], ())


def test_a_missing_element_whose_transformation_yields_nothing_takes_its_message():
    element = S.NumberFromString.annotate_key(message_missing_key="need 0")
    SchemaAsserts(S.Tuple(element)).decoding().fail([], "need 0\n  at [0]")


def test_a_tuple_drops_an_element_that_encodes_to_nothing():
    SchemaAsserts(S.Tuple(S.OptionFromOptionalKey(S.Number))).encoding().succeed((None,), ())


def test_missing_elements_take_their_decoding_defaults():
    defaulted = S.Number.pipe(S.with_decoding_default(fx.succeed(5.0)))
    decoding = SchemaAsserts(S.Tuple(defaulted)).decoding()
    decoding.succeed([], (5.0,))
    SchemaAsserts(S.Tuple(S.suspend(lambda: defaulted))).decoding().succeed([], (5.0,))
    after_optional = S.Tuple(S.optional_key(S.String), S.optional_key(defaulted))
    SchemaAsserts(after_optional).decoding().succeed(["a"], ("a", 5.0))


# ------------------------------------------------------------ reported input


def test_a_composite_issue_keeps_the_input_under_report_input():
    tuple_exit = S.decode_unknown_exit(S.Tuple(S.String))([1], report_input=True)
    assert _issue_input(tuple_exit) == Some([1])
    struct_exit = S.decode_unknown_exit(S.Struct(_X))({"x": "1"}, report_input=True)
    assert _issue_input(struct_exit) == Some({"x": "1"})


def test_an_issue_beside_a_defect_keeps_the_input_under_report_input():
    struct = S.Struct(_Text, x=_FAILS_WITH_A_DEFECT)
    assert _issue_input(S.decode_unknown_exit(struct)({"x": "a"}, report_input=True)) == Some(
        {"x": "a"}
    )
    tuple_ = S.Tuple(_FAILS_WITH_A_DEFECT)
    assert _issue_input(S.decode_unknown_exit(tuple_)(["a"], report_input=True)) == Some(["a"])
