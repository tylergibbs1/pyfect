"""Ports of Effect's ``SchemaJITCompiler.test.ts``: every schema AST resolved
in this module is compiled (``import "effect/schema/SchemaJITCompiler/enable"``
is the ``jit_installed`` fixture).

Python mappings: a JavaScript getter property is a ``Getters`` entry (a
mapping counting reads); a symbol key is a non-string key; ``Schema.Symbol``
(a type of values that are symbols) is ``S.Unknown`` where a test only needs
a member accepting any value; ``undefined`` is ``None``.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, cast

import pytest

import pyfect.schema as S
from pyfect import effect as fx
from pyfect import testing
from pyfect.cause import die, fail
from pyfect.deferred import Deferred
from pyfect.result import Err
from pyfect.schema import ast
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.compiler import INVALID
from pyfect.schema.issue import InvalidValue

from ._schema_binary import Opt, struct
from ._schema_compiler import Getter, Getters, fresh_registry, jit_installed

pytestmark = pytest.mark.usefixtures("jit_installed")

__all__ = ["fresh_registry", "jit_installed"]


def _schema() -> Any:
    return struct(
        name=S.String,
        count=S.Number,
        active=S.Boolean,
        nested=struct(value=S.String),
    )


def _message(raised: pytest.ExceptionInfo[BaseException]) -> str:
    error = raised.value
    assert isinstance(error, S.SchemaError)
    return error.message


def _boom() -> object:
    raise RuntimeError("boom")


@testing.effect
def test_preserves_product_concurrency():
    """preserves product concurrency"""
    started: list[Any] = []
    releases: list[Any] = []
    for _ in range(3):
        started.append((yield from Deferred.make()))
        releases.append((yield from Deferred.make()))

    def run(value: str, _options: S.ParseOptions) -> Any:
        index = ord(value[0]) - 97
        return started[index].succeed(None).and_then(releases[index].wait()).as_(value)

    item = S.String.pipe(S.decode(T.Transformation(G.transform_effect(run), G.passthrough())))
    schema = struct(a=item, b=item, c=item)
    fiber = yield from S.decode_unknown_effect(schema)(
        {"a": "a", "b": "b", "c": "c"}, concurrency=2
    ).fork()

    yield from started[0].wait()
    yield from started[1].wait()
    assert (yield from started[2].is_done()) is False

    yield from releases[0].succeed(None)
    yield from started[2].wait()
    yield from releases[1].succeed(None)
    yield from releases[2].succeed(None)

    assert (yield from fiber.join()) == {"a": "a", "b": "b", "c": "c"}


def test_compiles_a_decoder_lazily_after_import():
    """compiles a decoder lazily after import"""
    input = {
        "name": "a",
        "count": 1,
        "active": True,
        "nested": {"value": "b", "extra": True},
        "extra": True,
    }
    output = S.decode_unknown_sync(_schema())(input)

    assert output == {"name": "a", "count": 1, "active": True, "nested": {"value": "b"}}
    assert output is not input
    assert output["nested"] is not input["nested"]


def test_compiles_type_guards():
    """compiles type guards"""
    is_ = S.is_(_schema())
    assert is_({"name": "a", "count": 1, "active": True, "nested": {"value": "b"}}) is True
    assert is_({"name": 1, "count": 1, "active": True, "nested": {"value": "b"}}) is False

    input = Getters({"name": Getter(_boom), "count": 1, "active": True, "nested": {"value": "b"}})
    with pytest.raises(RuntimeError) as raised:
        is_(input)
    assert str(raised.value) == "Type guard adapter can only return false for schema issues"
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert str(raised.value.__cause__) == "boom"
    assert input.reads["name"] == 1


def test_does_not_confuse_a_valid_value_with_the_invalid_sentinel():
    """does not confuse a valid value with the invalid sentinel"""
    schemas: list[Any] = [
        S.Union(S.Unknown, S.String),
        S.Union(S.Literal("valid"), S.Any),
    ]
    for schema in schemas:
        assert S.is_(schema)(INVALID) is True
        assert S.decode_unknown_sync(schema)(INVALID) is INVALID


def _filter(run: Callable[[Any, S.ParseOptions], bool]) -> S.Filter[Any]:
    def check(value: Any, node: ast.AST, options: S.ParseOptions) -> Any:
        return None if run(value, options) else InvalidValue()

    return S.Filter(check, None, False)


def test_uses_default_options_in_compiled_type_guards():
    """uses default options in compiled type guards"""
    structural = struct(value=S.String)
    is_ = S.is_(structural)
    assert is_({"value": "a"}) is True
    assert is_({"value": "a", "extra": True}) is True
    assert is_({"value": 1}) is False

    checked = struct(a=S.String, b=S.String).check(
        _filter(lambda value, options: options.get("report_input") is True and "extra" not in value)
    )
    input = {"b": "b", "a": "a", "extra": True}
    assert S.is_(checked)(input) is False
    assert S.decode_unknown_sync(checked)(input, report_input=True) == {"a": "a", "b": "b"}
    assert S.decode_unknown_sync(checked)(input, disable_checks=True) == {"a": "a", "b": "b"}
    assert S.is_(checked)(input) is False


def test_accepts_the_invalid_sentinel_inside_a_checked_composite():
    """accepts the invalid sentinel inside a checked composite"""
    schema = struct(value=S.Union(S.Unknown, S.String)).check(S.make_filter(lambda _: True))
    input = {"value": INVALID}
    assert S.is_(schema)(input) is True
    assert S.decode_unknown_sync(schema)(input) == input


def test_keeps_runtime_options_for_nested_checks_template_parts_and_record_keys():
    """keeps runtime options for nested checks, template parts and record keys"""
    checked = struct(
        nested=struct(value=S.String).check(
            _filter(lambda _, options: options.get("report_input") is True)
        )
    )
    value = {"nested": {"value": "valid"}}
    assert S.is_(checked)(value) is False
    assert S.decode_unknown_sync(checked)(value, report_input=True) == value

    template = struct(value=S.TemplateLiteral(["prefix-", S.String.check(S.is_min_length(2))]))
    assert S.is_(template)({"value": "prefix-a"}) is False
    assert S.decode_unknown_sync(template)({"value": "prefix-a"}, disable_checks=True) == {
        "value": "prefix-a"
    }
    assert S.is_(template)({"value": "prefix-a"}) is False

    record = S.Record(S.String.check(S.is_starting_with("x")), S.Number)
    decode = S.decode_unknown_sync(record)
    assert decode({"x": 1, "y": 2}) == {"x": 1}
    assert decode({"x": 1, "y": 2}, disable_checks=True) == {"x": 1, "y": 2}


def test_runs_the_diagnostic_phase_after_fast_validation_fails():
    """runs the diagnostic phase after fast validation fails"""
    input = Getters({"name": 1, "count": 1, "active": True, "nested": {"value": "b"}})
    with pytest.raises(S.SchemaError) as raised:
        S.decode_unknown_sync(_schema())(input)
    assert _message(raised) == 'Expected string\n  at ["name"]'
    assert input.reads["name"] == 2


def test_runs_one_diagnostic_pass_for_a_nested_failure():
    """runs one diagnostic pass for a nested failure"""
    checks = 0

    def fail(_: object) -> bool:
        nonlocal checks
        checks += 1
        return False

    decode = S.decode_unknown_sync(struct(nested=struct(value=S.String.check(S.make_filter(fail)))))
    with pytest.raises(S.SchemaError) as raised:
        decode({"nested": {"value": "invalid"}})
    assert _message(raised) == 'Expected <filter>\n  at ["nested"]["value"]'
    assert checks == 2


def test_preserves_diagnostics_with_shared_parser_helpers():
    """preserves diagnostics with shared parser helpers"""
    decode = S.decode_unknown_sync(struct(value=S.String))
    assert decode({"value": "a", "extra": True}) == {"value": "a"}
    with pytest.raises(S.SchemaError) as raised:
        decode({"value": 1})
    assert _message(raised) == 'Expected string\n  at ["value"]'
    with pytest.raises(S.SchemaError) as raised:
        decode({"value": "a", "extra": True}, on_excess_property="error")
    assert _message(raised) == 'Expected no excess property\n  at ["extra"]'


def test_executes_transformations_and_middleware_once():
    """executes transformations and middleware once"""
    transformations = 0

    def trim(value: str) -> str:
        nonlocal transformations
        transformations += 1
        return value.strip()

    transformed = S.String.pipe(
        S.decode_to(S.String.check(S.is_min_length(2)), T.transform(decode=trim, encode=str))
    )
    decode_transformed = S.decode_unknown_sync(transformed)
    assert decode_transformed("  valid  ") == "valid"
    assert transformations == 1
    with pytest.raises(S.SchemaError):
        decode_transformed(" x ")
    assert transformations == 2

    middleware_runs = 0

    def middleware(parse: Any, _options: S.ParseOptions) -> Any:
        nonlocal middleware_runs
        middleware_runs += 1
        return parse

    middleware_schema = struct(value=S.String).pipe(S.middleware_decoding(middleware))
    assert S.decode_unknown_sync(middleware_schema)({"value": "valid"}) == {"value": "valid"}
    assert middleware_runs == 1


def test_decodes_transformed_struct_properties_with_runtime_options():
    """decodes transformed Struct properties with runtime options"""
    decode = S.decode_unknown_sync(struct(first=S.FiniteFromString, second=S.FiniteFromString))
    options: list[S.ParseOptions] = [
        {},
        {"errors": "first"},
        {"on_excess_property": "ignore"},
        {"report_input": True},
        {"disable_checks": True},
    ]
    assert decode({"first": "1", "second": "2"}) == {"first": 1, "second": 2}
    for option in options:
        assert decode({"first": "1", "second": "2"}, **option) == {"first": 1, "second": 2}


def test_does_not_replay_inlined_struct_transformations():
    """does not replay inlined Struct transformations"""
    transformations = 0

    def to_number(value: str) -> float:
        nonlocal transformations
        transformations += 1
        return value if value == "invalid" else float(value)  # pyright: ignore[reportReturnType]

    transformed = S.String.pipe(S.decode_to(S.Number, T.transform(decode=to_number, encode=str)))
    decode = S.decode_unknown_sync(struct(value=transformed))
    assert decode({"value": "1"}) == {"value": 1}
    assert transformations == 1
    with pytest.raises(S.SchemaError):
        decode({"value": False})
    assert transformations == 1
    with pytest.raises(S.SchemaError):
        decode({"value": "invalid"})
    assert transformations == 2


def test_applies_struct_output_and_encoding_checks_after_compiled_fields_without_replay():
    """applies Struct output and encoding checks after compiled fields without replay"""
    transformations = 0
    checks = 0

    def to_number(value: str) -> float:
        nonlocal transformations
        transformations += 1
        return float(value)

    def positive(output: Any) -> bool:
        nonlocal checks
        checks += 1
        assert list(output) == ["value"]
        return output["value"] > 0

    inner = struct(
        value=S.String.pipe(S.decode_to(S.Number, T.transform(decode=to_number, encode=str)))
    ).check(S.make_filter(positive))
    schema = S.flip(S.flip(inner).check(S.make_filter(lambda input: input["value"] != "01")))
    decode = S.decode_unknown_sync(schema)
    assert decode({"value": "1", "extra": True}) == {"value": 1}
    with pytest.raises(S.SchemaError):
        decode({"value": "-1", "extra": True})
    assert transformations == 2
    assert checks == 2

    assert decode({"value": "-1"}, disable_checks=True) == {"value": -1}
    assert checks == 2
    with pytest.raises(S.SchemaError):
        decode({"value": "-1"}, errors="all")
    assert transformations == 4
    assert checks == 3
    with pytest.raises(S.SchemaError):
        decode({"value": "01"})
    assert transformations == 5
    assert checks == 3


def _counting_failure() -> tuple[Any, Callable[[], int]]:
    checks = 0

    def fail(_: object) -> bool:
        nonlocal checks
        checks += 1
        return False

    return S.String.check(S.make_filter(fail)), lambda: checks


def test_replaces_the_parser_used_by_the_other_decoding_adapters():
    """replaces the parser used by the other decoding adapters"""
    schema, checks = _counting_failure()
    assert isinstance(S.decode_unknown_result(schema)("value"), Err)
    assert checks() == 2


def test_replaces_the_parser_used_by_encoding_adapters():
    """replaces the parser used by encoding adapters"""
    schema, checks = _counting_failure()
    assert isinstance(S.encode_unknown_result(schema)("value"), Err)
    assert checks() == 2


def test_does_not_replay_defects():
    """does not replay defects"""
    input = Getters({"name": Getter(_boom), "count": 1, "active": True, "nested": {"value": "b"}})
    with pytest.raises(RuntimeError) as raised:
        S.decode_unknown_sync(_schema())(input)
    assert str(raised.value) == "Sync adapter can only throw schema errors"
    assert str(raised.value.__cause__) == "boom"
    assert input.reads["name"] == 1


def test_honors_explicit_parseoptions_in_the_compiled_diagnostic_phase():
    """honors explicit ParseOptions in the compiled diagnostic phase"""
    with pytest.raises(S.SchemaError) as raised:
        S.decode_unknown_sync(_schema())(
            {
                "name": "a",
                "count": 1,
                "active": True,
                "nested": {"value": "b", "nestedExtra": True},
                "extra": True,
            },
            on_excess_property="error",
            errors="all",
        )
    assert _message(raised) == (
        'Expected no excess property\n  at ["extra"]\n'
        'Expected no excess property\n  at ["nested"]["nestedExtra"]'
    )


def test_compiles_symbol_keyed_struct_properties():
    """compiles symbol-keyed Struct properties"""
    key = object()
    schema = S.Bottom[Any](
        ast.Objects(
            (
                ast.PropertySignature("text", S.String.ast),
                ast.PropertySignature(key, S.Number.ast),
            )
        )
    )
    output = S.decode_unknown_sync(schema)({"text": "value", key: 1, "extra": True})
    assert output["text"] == "value"
    assert output[key] == 1
    assert list(output) == ["text", key]


class _Date:
    pass


def test_uses_the_interpreter_for_unsupported_schemas():
    """uses the interpreter for unsupported schemas"""
    date = _Date()
    assert S.decode_unknown_sync(S.instance_of(_Date))(date) is date


def test_uses_the_interpreter_when_dynamic_function_generation_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    """uses the interpreter when dynamic function generation is unavailable"""

    def unavailable(*_: object) -> None:
        raise RuntimeError("dynamic function generation unavailable")

    monkeypatch.setattr(builtins, "exec", unavailable)
    schema = struct(value=S.String)
    interpreted = 0
    node = schema.ast
    original = type(node).interpret

    def counting(self: Any, input: object, options: S.ParseOptions) -> Any:
        nonlocal interpreted
        if self is node:
            interpreted += 1
        return original(self, input, options)

    monkeypatch.setattr(type(node), "interpret", counting)
    decode = S.decode_unknown_sync(schema)
    assert decode({"value": "a"}) == {"value": "a"}
    assert interpreted == 1
    with pytest.raises(S.SchemaError) as raised:
        decode({"value": 1})
    assert _message(raised) == 'Expected string\n  at ["value"]'


def test_compiles_primitive_leaves_without_confusing_undefined_with_a_missing_key():
    """compiles primitive leaves without confusing undefined with a missing key"""
    decode = S.decode_unknown_sync(
        struct(
            undefined=S.Null,
            unknown=S.Unknown,
            bigint=S.BigInt,
            literal=S.Literal("a"),
        )
    )
    assert decode(
        {"undefined": None, "unknown": None, "bigint": 1, "literal": "a", "extra": True}
    ) == {"undefined": None, "unknown": None, "bigint": 1, "literal": "a"}
    with pytest.raises(S.SchemaError) as raised:
        decode({"unknown": None, "bigint": 1, "literal": "a"})
    assert _message(raised) == 'Missing key\n  at ["undefined"]'


def test_compiles_arrays_and_tuples_with_rest_and_tail_elements():
    """compiles arrays and tuples with rest and tail elements"""
    assert S.decode_unknown_sync(S.Array(S.String))(["a", "b"]) == ("a", "b")

    decode_tuple = S.decode_unknown_sync(S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean))
    assert decode_tuple(["a", 1, 2, True]) == ("a", 1, 2, True)
    with pytest.raises(S.SchemaError) as raised:
        decode_tuple(["a", 1, 2])
    assert _message(raised) == "Expected boolean\n  at [2]"


def test_compiles_optional_tuple_elements():
    """compiles optional tuple elements"""
    schema = S.Tuple(S.optional_key(S.String))
    decode = S.decode_unknown_sync(schema)
    is_ = S.is_(schema)
    assert decode([]) == ()
    assert decode(["a"]) == ("a",)
    assert is_([]) is True
    assert is_(["a"]) is True
    assert is_([1]) is False


def test_preserves_the_input_sign_for_signed_zero_literals():
    """preserves the input sign for signed-zero literals"""
    import math

    decode = S.decode_unknown_sync(
        struct(
            negative=S.Literal(-0.0),
            positive=S.Union(S.Literal(0), S.Literal(1)),
            union=S.Union(S.Literal(-0.0), S.Literal(1)),
        )
    )
    output = decode({"negative": 0.0, "positive": -0.0, "union": 0.0})
    assert math.copysign(1, output["negative"]) == 1
    assert math.copysign(1, output["positive"]) == -1
    assert math.copysign(1, output["union"]) == 1


def test_compiles_primitive_anyof_and_oneof_unions():
    """compiles primitive anyOf and oneOf unions"""
    decode_any_of = S.decode_unknown_sync(S.Union(S.Literal("a"), S.Literal("b"), S.Number))
    assert decode_any_of("b") == "b"
    assert decode_any_of(1) == 1
    with pytest.raises(S.SchemaError) as raised:
        decode_any_of(True)
    assert _message(raised) == 'Expected "a" | "b" | number'

    decode_one_of = S.decode_unknown_sync(S.Union(S.String, S.Literal("a"), mode="one_of"))
    assert decode_one_of("b") == "b"
    with pytest.raises(S.SchemaError) as raised:
        decode_one_of("a")
    assert _message(raised) == "Expected exactly one member to match"


def test_compiles_structural_unions_through_canonical_candidate_selection():
    """compiles structural unions through canonical candidate selection"""
    decode_tagged = S.decode_unknown_sync(
        S.Union(
            struct(kind=S.Literal("a"), value=S.String),
            struct(kind=S.Literal("b"), value=S.Number),
        )
    )
    assert decode_tagged({"kind": "b", "value": 1, "extra": True}) == {"kind": "b", "value": 1}

    decode_untagged = S.decode_unknown_sync(
        S.Union(struct(first=S.String), struct(second=S.String))
    )
    assert decode_untagged({"first": "a", "second": "b"}) == {"first": "a"}

    decode_one_of = S.decode_unknown_sync(
        S.Union(struct(first=S.String), struct(second=S.String), mode="one_of")
    )
    with pytest.raises(S.SchemaError) as raised:
        decode_one_of({"first": "a", "second": "b"})
    assert _message(raised) == "Expected exactly one member to match"


def test_compiles_optional_object_properties():
    """compiles optional object properties"""
    decode = S.decode_unknown_sync(
        struct(required=S.String, optional=Opt(S.Number), undefined=Opt(S.Null))
    )
    assert decode({"required": "a"}) == {"required": "a"}
    assert decode({"required": "a", "optional": 1, "undefined": None, "extra": True}) == {
        "required": "a",
        "optional": 1,
        "undefined": None,
    }
    with pytest.raises(S.SchemaError) as raised:
        decode({"required": "a", "optional": "invalid"})
    assert _message(raised) == 'Expected number\n  at ["optional"]'


def test_compiles_string_records():
    """compiles string records"""
    decode = S.decode_unknown_sync(S.Record(S.String, struct(count=S.Number)))
    assert decode(
        {"a": {"count": 1}, "b": {"count": 2}, "extra": {"count": 3, "ignored": True}}
    ) == {
        "a": {"count": 1},
        "b": {"count": 2},
        "extra": {"count": 3},
    }
    with pytest.raises(S.SchemaError) as raised:
        decode({"a": {"count": "invalid"}})
    assert _message(raised) == 'Expected number\n  at ["a"]["count"]'


def test_compiles_symbol_and_template_literal_records():
    """compiles symbol and template-literal records"""
    # A record of non-string keys: the keys an int key schema takes.
    decode_ints = S.decode_unknown_sync(S.Record(S.Int, S.Number))
    output = decode_ints({"text": "ignored", 1: 1})
    assert output == {1: 1}
    assert list(output) == [1]

    decode_templates = S.decode_unknown_sync(
        S.Record(S.TemplateLiteral(["data-", S.String]), S.Number)
    )
    assert decode_templates({"data-a": 1, "ignored": 2, "data-b": 3}) == {"data-a": 1, "data-b": 3}


def test_compiles_fixed_properties_with_index_signatures():
    """compiles fixed properties with index signatures"""
    decode = S.decode_unknown_sync(
        S.StructWithRest(struct(fixed=S.Trim), S.Record(S.String, S.String))
    )
    assert decode({"fixed": "  value  ", "other": "other"}) == {"fixed": "value", "other": "other"}


def test_compiles_decoded_index_keys():
    """compiles decoded index keys"""
    decode_numbers = S.decode_unknown_sync(S.Record(S.Number, S.Number))
    # Python keys are not all strings: a number key schema takes number keys.
    assert decode_numbers({1: 1, "other": "ignored"}) == {1: 1}

    decode_upper = S.decode_unknown_sync(
        S.Record(S.String.pipe(S.decode_to(S.String, T.to_upper_case())), S.Number)
    )
    assert decode_upper({"a": 1, "b": 2}) == {"A": 1, "B": 2}


def test_compiles_encoding_checks():
    """compiles encoding checks"""
    checked = S.flip(
        S.flip(struct(value=S.String)).check(
            S.make_filter(lambda input: len(cast("str", input["value"])) > 1)
        )
    )
    decode = S.decode_unknown_sync(checked)
    assert decode({"value": "valid"}) == {"value": "valid"}
    with pytest.raises(S.SchemaError):
        decode({"value": ""})


def test_runs_checks_against_decoded_output():
    """runs checks against decoded output"""
    decode_string = S.decode_unknown_sync(S.String.check(S.is_min_length(2)))
    assert decode_string("ab") == "ab"
    with pytest.raises(S.SchemaError) as raised:
        decode_string("a")
    assert _message(raised) == "Expected a value with a length of at least 2"

    decode_object = S.decode_unknown_sync(struct(value=S.String).check(S.is_max_properties(1)))
    assert decode_object({"value": "a", "extra": True}) == {"value": "a"}


def test_runs_compiled_type_guard_checks_against_decoded_output():
    """runs compiled type guard checks against decoded output"""
    checked = struct(value=S.String).check(S.is_max_properties(1))
    is_root = S.is_(checked)
    is_nested = S.is_(struct(nested=checked))
    assert is_root({"value": "a", "extra": True}) is True
    assert is_nested({"nested": {"value": "a", "extra": True}, "extra": True}) is True
    assert is_nested({"nested": {"value": 1}}) is False


def test_uses_compiled_checkpoints_around_interpreted_declarations_and_transformations():
    """uses compiled checkpoints around interpreted declarations and transformations"""
    date = _Date()
    decode = S.decode_unknown_sync(struct(date=S.instance_of(_Date), count=S.FiniteFromString))
    output = decode({"date": date, "count": "1", "extra": True})
    assert output["date"] is date
    assert output["count"] == 1
    assert list(output) == ["date", "count"]


def test_uses_compiled_checkpoints_inside_root_encoding_chains():
    """uses compiled checkpoints inside root encoding chains"""
    decode_number = S.decode_unknown_sync(S.FiniteFromString)
    assert decode_number("1") == 1
    with pytest.raises(S.SchemaError) as raised:
        decode_number("invalid")
    assert _message(raised) == "Expected a finite number"

    decode_json = S.decode_unknown_sync(S.from_json_string(struct(value=S.Number)))
    assert decode_json('{"value":1,"extra":true}') == {"value": 1}


def test_does_not_replay_transformations_when_a_compiled_checkpoint_fails():
    """does not replay transformations when a compiled checkpoint fails"""
    counts = {"source": 0, "first": 0, "second": 0, "checks": 0}

    def source(value: str) -> bool:
        counts["source"] += 1
        return value != "blocked"

    def first(value: str) -> float:
        counts["first"] += 1
        return float(value)

    def second(value: float) -> str:
        counts["second"] += 1
        return str(value)

    def positive(value: float) -> bool:
        counts["checks"] += 1
        return value > 0

    field = (
        S.String.check(S.make_filter(source))
        .pipe(
            S.decode_to(
                S.Number.check(S.make_filter(positive)), T.transform(decode=first, encode=str)
            )
        )
        .pipe(S.decode_to(S.String, T.transform(decode=second, encode=float)))
    )
    schema = struct(value=field)

    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(schema)({"value": "blocked"})
    assert (counts["source"], counts["first"], counts["second"]) == (1, 0, 0)

    counts["source"] = 0
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(schema)({"value": "-1"})
    assert counts == {"source": 1, "first": 1, "second": 0, "checks": 1}


def test_preserves_mixed_causes_from_interpreted_encoding_chains():
    """preserves mixed causes from interpreted encoding chains"""
    cause = fail(InvalidValue({"message": "schema issue"})) + die(RuntimeError("defect"))
    failing: T.Transformation[str, str] = T.Transformation(
        G.transform_optional_effect(lambda _, __: fx.fail_cause(cause)), G.passthrough()
    )
    schema = S.String.pipe(S.decode(failing))
    with pytest.raises(RuntimeError) as raised:
        S.decode_unknown_sync(schema)("value")
    assert str(raised.value) == "Sync adapter can only throw schema errors"
    assert str(raised.value.__cause__) == "defect"
    # The cause's schema failure is kept beside the defect (Effect's
    # ``Encoding`` issue): the note holds the whole cause.
    assert "schema issue" in "".join(raised.value.__notes__)


def test_keeps_suspend_parsers_lazy():
    """keeps Suspend parsers lazy"""
    evaluations = 0

    def category() -> Any:
        nonlocal evaluations
        evaluations += 1
        return schema

    schema: Any = struct(value=S.String, children=S.Array(S.suspend(category)))
    decode = S.decode_unknown_sync(schema)
    assert decode({"value": "root", "children": []}) == {"value": "root", "children": ()}
    assert evaluations == 0
    child: dict[str, object] = {"value": "child", "children": []}
    assert decode({"value": "root", "children": [child]}) == {
        "value": "root",
        "children": ({"value": "child", "children": ()},),
    }
    assert evaluations == 1


def test_does_not_replay_declaration_defects():
    """does not replay declaration defects"""
    runs = 0

    def run(_: object) -> Any:
        def parse(_input: object, _ast: object, _options: object) -> Any:
            nonlocal runs
            runs += 1
            return fx.die(RuntimeError("declaration defect"))

        return parse

    declaration: Any = S.declare_constructor((), run)  # pyright: ignore[reportUnknownVariableType]
    decode = S.decode_unknown_sync(struct(declaration=declaration))
    with pytest.raises(RuntimeError) as raised:
        decode({"declaration": "value"})
    assert str(raised.value) == "Sync adapter can only throw schema errors"
    assert str(raised.value.__cause__) == "declaration defect"
    assert runs == 1
