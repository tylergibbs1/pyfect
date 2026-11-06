"""Ports of the ``Config.schema`` titles of Effect's ``Config.test.ts``.

Each test's docstring is the Effect test title, prefixed by its ``describe``
block where titles repeat. ``Schema.Struct({...})`` is ``S.Struct`` of a
TypedDict; ``Schema.optionalKey(X)`` and ``Schema.optional(X)`` are both a
``NotRequired`` key (Python has no ``undefined``); ``Schema.Array`` decodes to
a tuple; ``Config.Array`` / ``Config.Record`` of a schema are
``config.list_of`` / ``config.dict_of`` of it.

Adapted, with the reason:

- "fromEnv provider: loads root, flat, and nested paths" leaves out the
  ``Schema.UndefinedOr`` cases: Python has no ``undefined`` to decode.
- "supports declarations with concrete StringTree encodings" checks the
  ``urllib`` split result (``S.URL``), which keeps the text as given (no
  trailing ``/`` added, as ``new URL`` does).
- "loads matching numeric record keys" gives ``int`` / ``float`` keys:
  Python mappings keep a key's type.

Omitted, with the reason:

- "preserves values successfully decoded from undefined", "wraps
  successfully decoded undefined in Some", "preserves missing array
  positions as undefined values", "recovers an absent sibling of a
  successfully decoded union" and "fromUnknown provider: decodes Undefined":
  each decodes ``undefined`` (``Schema.UndefinedOr`` / ``Schema.Undefined``),
  which Python does not have.
- "rejects Schema.ObjectKeyword" and "rejects Schema.MutableJson": neither
  schema exists in pyfect (every Python value is an object; ``S.Json`` holds
  any JSON value).
"""

from collections.abc import Mapping
from typing import Literal, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import config, testing
from pyfect import config_provider as cp
from pyfect import schema as S
from pyfect.config import Config, ConfigError
from pyfect.config_provider import Record, SourceError, Value
from pyfect.redacted import Redacted
from pyfect.schema import transformation as T


def _parse[A](cfg: Config[A], provider: cp.ConfigProvider) -> fx.Ok[A] | fx.Err[str]:
    return fx.run_blocking(cfg.parse(provider).map_error(lambda e: e.cause.message).result())


def assert_success[A](cfg: Config[A], provider: cp.ConfigProvider, expected: object) -> None:
    assert _parse(cfg, provider) == fx.Ok(expected)


def assert_failure(cfg: Config[object], provider: cp.ConfigProvider, message: str) -> None:
    assert _parse(cfg, provider) == fx.Err(message)


def unknown(value: object, *, preserve_empty_strings: bool = False) -> cp.ConfigProvider:
    return cp.from_unknown(value, preserve_empty_strings=preserve_empty_strings)


def env(values: dict[str, str], *, preserve_empty_strings: bool = False) -> cp.ConfigProvider:
    return cp.from_env(env=values, preserve_empty_strings=preserve_empty_strings)


class _Value(TypedDict):
    value: str


class _OptionalValue(TypedDict):
    value: NotRequired[str]


class _Empty(TypedDict):
    pass


class _Child(TypedDict):
    child: str


class _A(TypedDict):
    a: str


class _ANumber(TypedDict):
    a: float


class _AOptionalNumber(TypedDict):
    a: NotRequired[float]


class _BNumber(TypedDict):
    b: float


class _ALiteral(TypedDict):
    a: Literal["b", "c"]


class _AArray(TypedDict):
    a: tuple[float, ...]


class _ANested(TypedDict):
    a: _BNumber


class _AEmptyTuple(TypedDict):
    a: tuple[()]


class _ANumberTuple(TypedDict):
    a: tuple[float]


class _APair(TypedDict):
    a: tuple[str, float]


# --- withDefault, option and absence -----------------------------------------------------


def test_uses_the_default_unless_a_plain_array_schema_receives_an_array_representation():
    """uses the default unless a plain Array schema receives an array representation"""
    cfg = config.schema(S.Array(S.String), "a").with_default(("default",))

    assert_success(cfg, env({"a": "value"}), ("default",))
    assert_success(cfg, env({"a": ""}), ("default",))
    assert_success(cfg, env({"a": ""}, preserve_empty_strings=True), ("default",))
    assert_success(cfg, env({"a_0": "value"}), ("value",))
    assert_success(cfg, env({}), ("default",))


def test_defaults_absent_named_containers_and_preserves_explicit_empty_containers():
    """defaults absent named containers and preserves explicit empty containers"""
    absent = unknown({})
    default = {"value": "default"}

    assert_success(config.schema(S.Struct(_Value), "a").with_default(default), absent, default)
    assert_success(
        config.schema(S.Struct(_OptionalValue), "a").with_default(default), absent, default
    )
    assert_success(config.schema(S.Struct(_Empty), "a").with_default(default), absent, default)
    assert_success(
        config.schema(S.Record(S.String, S.String), "a").with_default(default), absent, default
    )
    assert_success(config.schema(S.Tuple(), "a").with_default(("default",)), absent, ("default",))
    assert_success(
        config.schema(S.Tuple(S.String), "a").with_default(("default",)), absent, ("default",)
    )
    assert_success(
        config.schema(S.FrozenSet(S.String), "a").with_default(frozenset({"default"})),
        absent,
        frozenset({"default"}),
    )
    assert_success(
        config.schema(S.Map(S.String, S.String), "a").with_default({"default": "value"}),
        absent,
        {"default": "value"},
    )

    assert_success(config.schema(S.Struct(_OptionalValue), "a"), unknown({"a": {}}), {})
    assert_success(config.schema(S.Record(S.String, S.String), "a"), unknown({"a": {}}), {})
    assert_success(config.schema(S.Tuple(), "a"), unknown({"a": []}), ())


@testing.effect
def test_rejects_present_containers_with_incompatible_shapes():
    """rejects present containers with incompatible shapes"""
    wrong_struct = yield from (
        config.schema(S.Struct(_OptionalValue), "value").parse(unknown({"value": []})).flip()
    )
    assert isinstance(wrong_struct, ConfigError)

    wrong_array = yield from (
        config.schema(S.Array(S.String), "value").parse(unknown({"value": {}})).flip()
    )
    assert isinstance(wrong_array, ConfigError)


# --- schema --------------------------------------------------------------------------------


def test_reports_missing_redacted_input():
    """reports missing redacted input"""
    assert_failure(
        config.schema(S.Redacted(S.Literal("secret")), "a"),
        unknown({}),
        'Expected "secret"\n  at ["a"]',
    )


def test_loads_matching_numeric_record_keys():
    """loads matching numeric record keys"""
    provider = unknown({"a": {"80": "http", "1.5": "fractional", "abc": "skipped"}})

    assert_success(config.schema(S.Record(S.Int, S.String), "a"), provider, {80: "http"})
    assert_success(
        config.schema(S.Record(S.Number, S.String), "a"),
        provider,
        {80: "http", 1.5: "fractional"},
    )


# --- materialization: Encoded shapes -------------------------------------------------------


def _value_of(text: str) -> _Value:
    return {"value": text}


def _text_of(value: _Value) -> str:
    return value["value"]


def _encoded_value_of(text: str) -> Mapping[str, object]:
    # A struct's Encoded is a ``Mapping``: the transformation into it gives one.
    return {"value": text}


def _text_of_encoded(value: Mapping[str, object]) -> str:
    return str(value["value"])


scalar_to_struct = S.String.pipe(
    S.decode_to(S.Struct(_Value), T.transform(decode=_encoded_value_of, encode=_text_of_encoded))
)
struct_to_scalar = S.Struct(_Value).pipe(
    S.decode_to(S.String, T.transform(decode=_text_of, encode=_value_of))
)


@testing.effect
def test_loads_the_encoded_shape_when_it_differs_from_the_decoded_shape():
    """loads the encoded shape when it differs from the decoded shape"""
    assert (
        yield from config.schema(scalar_to_struct, "config").parse(unknown({"config": "value"}))
    ) == {"value": "value"}
    assert (
        yield from config.schema(struct_to_scalar, "config").parse(
            unknown({"config": {"value": "value"}})
        )
    ) == "value"


class _Shapes(TypedDict):
    fromScalar: _Value
    fromStruct: str
    items: tuple[_Value, ...]


@testing.effect
def test_loads_encoded_shapes_recursively_inside_objects_and_arrays():
    """loads encoded shapes recursively inside objects and arrays"""
    cfg = config.schema(
        S.Struct(
            _Shapes,
            fromScalar=scalar_to_struct,
            fromStruct=struct_to_scalar,
            items=S.Array(scalar_to_struct),
        )
    )

    assert (
        yield from cfg.parse(
            unknown({"fromScalar": "one", "fromStruct": {"value": "two"}, "items": ["three"]})
        )
    ) == {"fromScalar": {"value": "one"}, "fromStruct": "two", "items": ({"value": "three"},)}


@testing.effect
def test_loads_every_union_member_from_its_encoded_shape():
    """loads every union member from its encoded shape"""
    cfg = config.schema(S.Union(scalar_to_struct, struct_to_scalar), "config")

    assert (yield from cfg.parse(unknown({"config": "scalar"}))) == {"value": "scalar"}
    assert (yield from cfg.parse(unknown({"config": {"value": "struct"}}))) == "struct"


# --- materialization: Objects ----------------------------------------------------------------


class _Host(TypedDict):
    host: str


class _Wanted(TypedDict):
    wanted: str


@testing.effect
def test_loads_explicit_properties_even_when_only_a_fallback_provider_contains_the_child():
    """loads explicit properties even when only a fallback provider contains the child"""
    primary = cp.make(lambda path: fx.succeed(Record(frozenset()) if not path else None))
    fallback = cp.make(lambda path: fx.succeed(Value("localhost") if path == ("host",) else None))
    provider = primary.or_else(fallback)

    assert (yield from config.schema(S.Struct(_Host)).parse(provider)) == {"host": "localhost"}


def _advertising(source_error: SourceError) -> cp.ConfigProvider:
    def load(path: cp.Path) -> fx.Effect[cp.Node | None, SourceError]:
        if not path:
            return fx.succeed(Record(frozenset({"wanted", "unrelated"})))
        if path[0] == "wanted":
            return fx.succeed(Value("value"))
        return fx.fail(source_error)

    return cp.make(load)


@testing.effect
def test_does_not_load_advertised_keys_that_are_unrelated_to_the_schema():
    """does not load advertised keys that are unrelated to the schema"""
    provider = _advertising(SourceError("unrelated key was loaded"))

    assert (yield from config.schema(S.Struct(_Wanted)).parse(provider)) == {"wanted": "value"}


@testing.effect
def test_loads_advertised_keys_only_when_they_match_an_index_signature():
    """loads advertised keys only when they match an index signature"""
    provider = _advertising(SourceError("non-matching key was loaded"))

    assert (yield from config.schema(S.Record(S.Literal("wanted"), S.String)).parse(provider)) == {
        "wanted": "value"
    }


# --- materialization: Opaque schemas ---------------------------------------------------------

_OPAQUE = "Config.schema does not support opaque StringTree encodings"


def test_rejects_schema_any():
    """Opaque schemas: rejects Schema.Any"""
    with pytest.raises(ValueError, match=_OPAQUE):
        config.schema(S.Any)


def test_rejects_schema_unknown():
    """Opaque schemas: rejects Schema.Unknown"""
    with pytest.raises(ValueError, match=_OPAQUE):
        config.schema(S.Unknown)


def test_rejects_schema_json():
    """Opaque schemas: rejects Schema.Json"""
    with pytest.raises(ValueError, match=_OPAQUE):
        config.schema(S.Json)


class _UnknownValue(TypedDict):
    value: object


def test_rejects_opaque_shapes_nested_in_objects():
    """rejects opaque shapes nested in objects"""
    with pytest.raises(ValueError, match=_OPAQUE):
        config.schema(S.Struct(_UnknownValue, value=S.Unknown))


def test_rejects_opaque_union_members():
    """rejects opaque union members"""
    with pytest.raises(ValueError, match=_OPAQUE):
        config.schema(S.Union(S.String, S.Unknown))


def test_rejects_opaque_shapes_behind_suspensions():
    """rejects opaque shapes behind suspensions"""
    with pytest.raises(ValueError, match=_OPAQUE):
        config.schema(S.suspend(lambda: S.Unknown))


@testing.effect
def test_supports_declarations_with_concrete_string_tree_encodings():
    """supports declarations with concrete StringTree encodings"""
    provider = unknown({"value": "https://example.com"})
    value = yield from config.schema(S.URL, "value").parse(provider)

    assert (value.scheme, value.netloc) == ("https", "example.com")


@testing.effect
def test_supports_arbitrary_json_encoded_in_a_scalar_string():
    """supports arbitrary JSON encoded in a scalar string"""
    provider = unknown({"value": '{"nested":[1,true]}'})
    value = yield from config.schema(S.from_json_string(S.Json), "value").parse(provider)

    assert value == {"nested": [1, True]}


# --- materialization: Union -------------------------------------------------------------------


def test_materializes_each_member_independently_before_applying_first_match_semantics():
    """materializes each member independently before applying first-match semantics"""
    cfg = config.schema(S.Union(S.Struct(_Child), S.String), "value")
    provider = env({"value": "scalar", "value_child": "object"})

    assert_success(cfg, provider, {"child": "object"})


def test_preserves_first_match_semantics_when_the_scalar_member_is_declared_first():
    """preserves first-match semantics when the scalar member is declared first"""
    cfg = config.schema(S.Union(S.String, S.Struct(_Child)), "value")
    provider = env({"value": "scalar", "value_child": "object"})

    assert_success(cfg, provider, "scalar")


def test_reports_one_of_ambiguity_without_exposing_the_internal_cursor():
    """reports oneOf ambiguity without exposing the internal cursor"""
    cfg = config.schema(S.Union(S.Struct(_Child), S.String, mode="one_of"), ("database", "value"))
    provider = env({"database_value": "scalar", "database_value_child": "object"})

    assert_failure(
        cfg, provider, 'Expected exactly one member to match\n  at ["database"]["value"]'
    )


@testing.effect
def test_applies_checks_attached_to_the_original_union():
    """applies checks attached to the original union"""

    def no_strings(value: object) -> S.FilterOutput:
        return "union check failed" if isinstance(value, str) else None

    schema = S.Union(S.Struct(_Child), S.String).check(S.make_filter(no_strings))
    error = yield from config.schema(schema, "value").parse(unknown({"value": "scalar"})).flip()

    assert error.cause.message == 'union check failed\n  at ["value"]'


@testing.effect
def test_propagates_source_error_defects_instead_of_trying_another_member():
    """propagates SourceError defects instead of trying another member"""
    source_error = SourceError("source unavailable")

    def load(path: cp.Path) -> fx.Effect[cp.Node | None, SourceError]:
        if path == ("value",):
            return fx.succeed(Record(frozenset({"child"}), "scalar"))
        return fx.fail(source_error)

    cfg = config.schema(S.Union(S.Struct(_Child), S.String), "value")

    error = yield from cfg.parse(cp.make(load)).flip()
    assert error.cause is source_error


# --- fromEnv provider --------------------------------------------------------------------------


def test_from_env_loads_root_flat_and_nested_paths():
    """fromEnv provider: loads root, flat, and nested paths"""
    assert_success(config.schema(S.String, "a"), env({"a": "value"}), "value")
    assert_success(config.schema(S.String, ("a", "b")), env({"a_b": "value"}), "value")


def test_uses_a_co_located_scalar_instead_of_object_children_for_a_leaf_schema():
    """node precedence: uses a co-located scalar instead of object children for a leaf schema"""
    assert_success(config.schema(S.Struct(_ANumber)), env({"a": "1", "a_b": "2"}), {"a": 1})


def test_uses_a_co_located_scalar_instead_of_array_children_for_a_leaf_schema():
    """node precedence: uses a co-located scalar instead of array children for a leaf schema"""
    assert_success(config.schema(S.Struct(_ANumber)), env({"a": "1", "a_0": "2"}), {"a": 1})


def test_prefers_object_children_when_a_node_can_be_both_object_and_array():
    """node precedence: prefers object children when a node can be both object and array"""
    assert_success(
        config.schema(S.Struct(_ANested)),
        env({"a": "1", "a_b": "2", "a_0": "3"}),
        {"a": {"b": 2}},
    )


def test_from_env_decodes_null():
    """fromEnv provider: decodes Null"""
    cfg = config.schema(S.Null, "a")

    assert_success(cfg, env({"a": "null"}), None)
    assert_failure(cfg, env({}), 'Expected "null"\n  at ["a"]')


def test_from_env_decodes_string_and_reports_absence():
    """fromEnv provider: decodes String and reports absence"""
    cfg = config.schema(S.String, "a")

    assert_success(cfg, env({"a": "a"}), "a")
    assert_failure(cfg, env({}), 'Expected string\n  at ["a"]')


def test_from_env_decodes_number_and_reports_absence():
    """fromEnv provider: decodes Number and reports absence"""
    cfg = config.schema(S.Number, "a")

    assert_success(cfg, env({"a": "1"}), 1)
    assert_failure(cfg, env({}), 'Expected string | "Infinity" | "-Infinity" | "NaN"\n  at ["a"]')


def test_from_env_decodes_finite_and_reports_absence():
    """fromEnv provider: decodes Finite and reports absence"""
    cfg = config.schema(S.Finite, "a")

    assert_success(cfg, env({"a": "1"}), 1)
    assert_failure(cfg, env({}), 'Expected string\n  at ["a"]')


def test_from_env_decodes_int_and_reports_absence():
    """fromEnv provider: decodes Int and reports absence"""
    cfg = config.schema(S.Int, "a")

    assert_success(cfg, env({"a": "1"}), 1)
    assert_failure(cfg, env({}), 'Expected string\n  at ["a"]')


def test_from_env_decodes_boolean_and_reports_absence():
    """fromEnv provider: decodes Boolean and reports absence"""
    cfg = config.schema(S.Boolean, "a")

    assert_success(cfg, env({"a": "true"}), True)
    assert_success(cfg, env({"a": "false"}), False)
    assert_failure(cfg, env({}), 'Expected "true" | "false"\n  at ["a"]')


def test_from_env_struct_decodes_required_properties():
    """fromEnv provider: Struct: decodes required properties"""
    assert_success(config.schema(S.Struct(_ANumber)), env({"a": "1"}), {"a": 1})


def test_from_env_struct_omits_absent_optional_key_properties():
    """fromEnv provider: Struct: omits absent optionalKey properties"""
    cfg = config.schema(S.Struct(_AOptionalNumber))

    assert_success(cfg, env({"a": "1"}), {"a": 1})
    assert_success(cfg, env({"unrelated": "value"}), {})


def test_from_env_struct_omits_absent_optional_properties():
    """fromEnv provider: Struct: omits absent optional properties"""
    cfg = config.schema(S.Struct(_AOptionalNumber))

    assert_success(cfg, env({"a": "1"}), {"a": 1})
    assert_success(cfg, env({"unrelated": "value"}), {})


def test_from_env_struct_decodes_literal_properties():
    """fromEnv provider: Struct: decodes literal properties"""
    cfg = config.schema(S.Struct(_ALiteral))

    assert_success(cfg, env({"a": "b"}), {"a": "b"})
    assert_success(cfg, env({"a": "c"}), {"a": "c"})


def test_decodes_indexed_array_properties_without_treating_co_located_scalars_as_arrays():
    """fromEnv provider: Struct: decodes indexed array properties without treating
    co-located scalars as arrays"""
    cfg = config.schema(S.Struct(_AArray))

    assert_failure(cfg, env({"a": ""}, preserve_empty_strings=True), 'Expected array\n  at ["a"]')
    assert_failure(cfg, env({"a": "1"}), 'Expected array\n  at ["a"]')
    assert_success(cfg, env({"a_0": "1"}), {"a": (1,)})
    assert_success(cfg, env({"a_0": "1", "a_1": "2"}), {"a": (1, 2)})
    assert_success(cfg, env({"a": "1", "a_0": "2"}), {"a": (2,)})
    assert_failure(cfg, env({}), "Expected object")


def test_from_env_decodes_and_validates_record_values():
    """fromEnv provider: decodes and validates Record values"""
    cfg = config.schema(S.Record(S.String, S.Finite))

    assert_success(cfg, env({"a": "1"}), {"a": 1})
    assert_success(cfg, env({"a": "1", "b": "2"}), {"a": 1, "b": 2})
    assert_failure(
        cfg,
        env({"a": "1", "b": "value"}),
        'Expected a string representing a finite number\n  at ["b"]',
    )


def test_from_env_tuple_rejects_a_scalar_where_an_empty_tuple_is_expected():
    """fromEnv provider: Tuple: rejects a scalar where an empty tuple is expected"""
    assert_failure(
        config.schema(S.Struct(_AEmptyTuple)),
        env({"a": ""}, preserve_empty_strings=True),
        'Expected array\n  at ["a"]',
    )


def test_from_env_tuple_rejects_scalar_tuple_input():
    """fromEnv provider: Tuple: rejects scalar tuple input"""
    assert_failure(
        config.schema(S.Struct(_ANumberTuple)), env({"a": "1"}), 'Expected array\n  at ["a"]'
    )


def test_from_env_tuple_requires_and_validates_every_tuple_element():
    """fromEnv provider: Tuple: requires and validates every tuple element"""
    cfg = config.schema(S.Struct(_APair, a=S.Tuple(S.String, S.Finite)))

    assert_success(cfg, env({"a_0": "a", "a_1": "2"}), {"a": ("a", 2)})
    assert_failure(cfg, env({"a": "a"}), 'Expected array\n  at ["a"]')
    assert_failure(
        cfg,
        env({"a_0": "a", "a_1": "value"}),
        'Expected a string representing a finite number\n  at ["a"][1]',
    )


def test_from_env_decodes_indexed_array_input_and_rejects_scalar_input():
    """fromEnv provider: decodes indexed Array input and rejects scalar input"""
    cfg = config.schema(S.Struct(_AArray, a=S.Array(S.Finite)))

    assert_failure(cfg, env({"a": "1,2,3"}), 'Expected array\n  at ["a"]')
    assert_success(cfg, env({"a_0": "1", "a_1": "2"}), {"a": (1, 2)})
    assert_success(cfg, env({"a": "a", "a_0": "1"}), {"a": (1,)})
    assert_failure(cfg, env({"a_0": "1", "a_2": "2"}), 'Expected string\n  at ["a"][1]')
    assert_failure(
        cfg,
        env({"a_0": "1", "a_1": "value"}),
        'Expected a string representing a finite number\n  at ["a"][1]',
    )


def test_from_env_union_decodes_literal_unions():
    """fromEnv provider: Union: decodes literal unions"""
    cfg = config.schema(S.Struct(_A, a=S.Literals("a", "b")))

    assert_success(cfg, env({"a": "a"}), {"a": "a"})
    assert_success(cfg, env({"a": "b"}), {"a": "b"})


def test_from_env_union_uses_first_match_semantics_by_default():
    """fromEnv provider: Union: uses first-match semantics by default"""
    cfg = config.schema(S.Union(S.Struct(_A), S.Struct(_BNumber)))

    assert_success(cfg, env({"a": "a"}), {"a": "a"})
    assert_success(cfg, env({"b": "1"}), {"b": 1})
    assert_success(cfg, env({"a": "a", "b": "1"}), {"a": "a"})


def test_from_env_union_enforces_exactly_one_match_in_one_of_mode():
    """fromEnv provider: Union: enforces exactly one match in oneOf mode"""
    cfg = config.schema(S.Union(S.Struct(_A), S.Struct(_BNumber), mode="one_of"))

    assert_success(cfg, env({"a": "a"}), {"a": "a"})
    assert_success(cfg, env({"b": "1"}), {"b": 1})
    assert_failure(cfg, env({"a": "a", "b": "1"}), "Expected exactly one member to match")


def test_from_env_union_decodes_number_before_string():
    """fromEnv provider: Union: decodes Number before String"""
    cfg = config.schema(S.Union(S.Number, S.String), "a")

    assert_success(cfg, env({"a": "1"}), 1)
    assert_success(cfg, env({"a": "a"}), "a")


def test_from_env_union_still_decodes_numeric_input_when_string_is_listed_first():
    """fromEnv provider: Union: still decodes numeric input when String is listed first"""
    cfg = config.schema(S.Union(S.String, S.Number), "a")

    assert_success(cfg, env({"a": "1"}), 1)
    assert_success(cfg, env({"a": "a"}), "a")


def test_from_env_reports_int_validation_errors():
    """fromEnv provider: reports Int validation errors"""
    cfg = config.schema(S.Redacted(S.Int), "a")

    assert _parse(cfg, env({"a": "1"})) == fx.Ok(Redacted(1))
    assert_failure(cfg, env({}), 'Expected string\n  at ["a"]')
    assert_failure(cfg, env({"a": "1.1"}), 'Expected an integer\n  at ["a"]')


# --- fromUnknown provider ------------------------------------------------------------------------


def test_from_unknown_loads_root_flat_and_nested_paths():
    """fromUnknown provider: loads root, flat, and nested paths"""
    assert_success(config.schema(S.String, ()), unknown("value"), "value")
    assert_success(config.schema(S.String, "a"), unknown({"a": "value"}), "value")
    assert_success(config.schema(S.String, ("a", "b")), unknown({"a": {"b": "value"}}), "value")


def test_from_unknown_decodes_null():
    """fromUnknown provider: decodes Null"""
    cfg = config.schema(S.Null)

    assert_success(cfg, unknown("null"), None)
    assert_failure(cfg, unknown("a"), 'Expected "null"')


def test_from_unknown_decodes_string_and_rejects_object_input():
    """fromUnknown provider: decodes String and rejects object input"""
    cfg = config.schema(S.String)

    assert_success(cfg, unknown("value"), "value")
    assert_failure(cfg, unknown({}), "Expected string")


def test_from_unknown_decodes_number_and_rejects_invalid_input():
    """fromUnknown provider: decodes Number and rejects invalid input"""
    cfg = config.schema(S.Number)

    assert_success(cfg, unknown("1"), 1)
    assert_failure(
        cfg,
        unknown("a"),
        'Expected a string representing a finite number\nExpected "Infinity" | "-Infinity" | "NaN"',
    )


def test_from_unknown_decodes_finite_and_rejects_invalid_input():
    """fromUnknown provider: decodes Finite and rejects invalid input"""
    cfg = config.schema(S.Finite)

    assert_success(cfg, unknown("1"), 1)
    assert_failure(cfg, unknown("a"), "Expected a string representing a finite number")


def test_from_unknown_decodes_int_and_rejects_invalid_input():
    """fromUnknown provider: decodes Int and rejects invalid input"""
    cfg = config.schema(S.Int)

    assert_success(cfg, unknown("1"), 1)
    assert_failure(cfg, unknown("a"), "Expected a string representing a finite number")


def test_from_unknown_decodes_boolean_and_rejects_invalid_input():
    """fromUnknown provider: decodes Boolean and rejects invalid input"""
    cfg = config.schema(S.Boolean)

    assert_success(cfg, unknown("true"), True)
    assert_success(cfg, unknown("false"), False)
    assert_failure(cfg, unknown("a"), 'Expected "true" | "false"')


def test_from_unknown_struct_requires_and_validates_required_properties():
    """fromUnknown provider: Struct: requires and validates required properties"""
    cfg = config.schema(S.Struct(_ANumber, a=S.Finite))

    assert_success(cfg, unknown({"a": "1"}), {"a": 1})
    assert_failure(cfg, unknown({}), 'Missing key\n  at ["a"]')
    assert_failure(
        cfg, unknown({"a": "value"}), 'Expected a string representing a finite number\n  at ["a"]'
    )


def test_from_unknown_struct_omits_absent_optional_key_properties():
    """fromUnknown provider: Struct: omits absent optionalKey properties"""
    cfg = config.schema(S.Struct(_AOptionalNumber))

    assert_success(cfg, unknown({"a": "1"}), {"a": 1})
    assert_success(cfg, unknown({}), {})


def test_from_unknown_struct_omits_absent_optional_properties():
    """fromUnknown provider: Struct: omits absent optional properties"""
    cfg = config.schema(S.Struct(_AOptionalNumber))

    assert_success(cfg, unknown({"a": "1"}), {"a": 1})
    assert_success(cfg, unknown({}), {})


def test_from_unknown_struct_decodes_literal_properties():
    """fromUnknown provider: Struct: decodes literal properties"""
    cfg = config.schema(S.Struct(_ALiteral))

    assert_success(cfg, unknown({"a": "b"}), {"a": "b"})
    assert_success(cfg, unknown({"a": "c"}), {"a": "c"})


def test_from_unknown_struct_rejects_scalar_values_for_array_properties():
    """fromUnknown provider: Struct: rejects scalar values for array properties"""
    cfg = config.schema(S.Struct(_AArray))

    assert_failure(cfg, unknown({"a": ""}), 'Missing key\n  at ["a"]')
    assert_failure(
        cfg, unknown({"a": ""}, preserve_empty_strings=True), 'Expected array\n  at ["a"]'
    )
    assert_failure(cfg, unknown({"a": "1"}), 'Expected array\n  at ["a"]')


def test_from_unknown_decodes_and_validates_record_values():
    """fromUnknown provider: decodes and validates Record values"""
    cfg = config.schema(S.Record(S.String, S.Finite))

    assert_success(cfg, unknown({"a": "1"}), {"a": 1})
    assert_success(cfg, unknown({"a": "1", "b": "2"}), {"a": 1, "b": 2})
    assert_failure(
        cfg,
        unknown({"a": "1", "b": "value"}),
        'Expected a string representing a finite number\n  at ["b"]',
    )


def test_from_unknown_tuple_accepts_array_tuple_input_and_rejects_scalar_input():
    """fromUnknown provider: Tuple: accepts array tuple input and rejects scalar input"""
    cfg = config.schema(S.Tuple(S.Number))

    assert_success(cfg, unknown(["1"]), (1,))
    assert_failure(cfg, unknown("1"), "Expected array")


def test_from_unknown_tuple_requires_and_validates_every_tuple_element():
    """fromUnknown provider: Tuple: requires and validates every tuple element"""
    cfg = config.schema(S.Tuple(S.String, S.Finite))

    assert_success(cfg, unknown(["a", "2"]), ("a", 2))
    assert_failure(cfg, unknown(["a"]), "Missing key\n  at [1]")
    assert_failure(
        cfg, unknown(["a", "value"]), "Expected a string representing a finite number\n  at [1]"
    )


def test_from_unknown_accepts_array_input_and_rejects_scalar_array_input():
    """fromUnknown provider: accepts array input and rejects scalar Array input"""
    cfg = config.schema(S.Array(S.Finite))

    assert_success(cfg, unknown(["1"]), (1,))
    assert_failure(cfg, unknown("1"), "Expected array")
    assert_success(cfg, unknown(["1", "2"]), (1, 2))
    assert_failure(
        cfg, unknown(["1", "value"]), "Expected a string representing a finite number\n  at [1]"
    )


def test_from_unknown_union_decodes_literal_unions():
    """fromUnknown provider: Union: decodes literal unions"""
    cfg = config.schema(S.Literals("a", "b"))

    assert_success(cfg, unknown("a"), "a")
    assert_success(cfg, unknown("b"), "b")


def test_from_unknown_union_uses_first_match_semantics_by_default():
    """fromUnknown provider: Union: uses first-match semantics by default"""
    cfg = config.schema(S.Union(S.Struct(_A), S.Struct(_BNumber)))

    assert_success(cfg, unknown({"a": "a"}), {"a": "a"})
    assert_success(cfg, unknown({"b": "1"}), {"b": 1})
    assert_success(cfg, unknown({"a": "a", "b": "1"}), {"a": "a"})


def test_from_unknown_union_enforces_exactly_one_match_in_one_of_mode():
    """fromUnknown provider: Union: enforces exactly one match in oneOf mode"""
    cfg = config.schema(S.Union(S.Struct(_A), S.Struct(_BNumber), mode="one_of"))

    assert_success(cfg, unknown({"a": "a"}), {"a": "a"})
    assert_success(cfg, unknown({"b": "1"}), {"b": 1})
    assert_failure(cfg, unknown({"a": "a", "b": "1"}), "Expected exactly one member to match")


def test_from_unknown_union_decodes_number_before_string():
    """fromUnknown provider: Union: decodes Number before String"""
    cfg = config.schema(S.Union(S.Number, S.String))

    assert_success(cfg, unknown("1"), 1)
    assert_success(cfg, unknown("a"), "a")


def test_from_unknown_union_still_decodes_numeric_input_when_string_is_listed_first():
    """fromUnknown provider: Union: still decodes numeric input when String is listed first"""
    cfg = config.schema(S.Union(S.String, S.Number))

    assert_success(cfg, unknown("1"), 1)
    assert_success(cfg, unknown("a"), "a")


class _Node(TypedDict):
    a: str
    children: "tuple[_Node, ...]"


def test_from_unknown_decodes_recursive_suspended_schemas():
    """fromUnknown provider: decodes recursive suspended schemas"""
    cfg = config.schema(S.Struct(_Node))
    leaf: dict[str, object] = {"a": "2", "children": []}

    assert_success(cfg, unknown({"a": "1", "children": []}), {"a": "1", "children": ()})
    assert_success(
        cfg,
        unknown({"a": "1", "children": [leaf]}),
        {"a": "1", "children": ({"a": "2", "children": ()},)},
    )


class _RedactedInt(TypedDict):
    a: Redacted[int]


def test_from_unknown_reports_nested_int_validation_errors():
    """fromUnknown provider: reports nested Int validation errors"""
    cfg = config.schema(S.Struct(_RedactedInt, a=S.Redacted(S.Int)))

    assert _parse(cfg, unknown({"a": "1"})) == fx.Ok({"a": Redacted(1)})
    assert_failure(cfg, unknown({}), 'Missing key\n  at ["a"]')
    assert_failure(cfg, unknown({"a": "1.1"}), 'Expected an integer\n  at ["a"]')


class _UrlValue(TypedDict):
    a: object


def test_from_unknown_decodes_nested_url_values():
    """fromUnknown provider: decodes nested URL values"""
    from urllib.parse import urlsplit

    cfg = config.schema(S.Struct(_UrlValue, a=S.URL))

    assert_success(
        cfg, unknown({"a": "https://example.com"}), {"a": urlsplit("https://example.com")}
    )
