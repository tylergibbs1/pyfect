"""Ports of Effect's ``SchemaCompilerRegression.test.ts``.

Python mappings: ``globalThis.Function`` is ``builtins.exec``; a getter
property on the input is a ``Getters`` mapping and a getter on an installed
decoder a property; ``Schema.Date`` (a declaration) is ``S.Option``;
``undefined`` is ``None``; diagnostic issues are compared by their kind and
message (Effect compares their JSON). Python has no ``-0`` integer and no
function properties to inspect: "accepts both zero signs ..." uses ``0.0``
and ``-0.0``, and "calls installed operations with options without
inspecting extra function properties" gives the operations a raising
attribute. "does not reanalyse a nested schema ..." counts the analyses of
the declaration (Effect counts property reads through a ``Proxy``).
"""

from __future__ import annotations

import builtins
import math
from typing import Any, cast

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.exit import Success
from pyfect.option import Some
from pyfect.result import Err, Ok
from pyfect.schema import compiler as SC
from pyfect.schema import getter as G
from pyfect.schema import jit_compiler
from pyfect.schema import transformation as T
from pyfect.schema.compiler import _codegen
from pyfect.schema.issue import InvalidType, OneOf

from ._schema_binary import Opt, struct, struct_of
from ._schema_compiler import Getters, fresh_registry

__all__ = ["fresh_registry"]


def ok(input: object, _options: object = None) -> Any:
    return Success(input)


def _true(_input: object) -> bool:
    return True


def _same_input(input: object) -> object:
    return input


def _always(_input: object, _options: object) -> bool:
    return True


def _identity(input: object, _options: object) -> object:
    return input


def _invalid(_input: object, _options: object) -> object:
    return SC.INVALID


def _type_of(value: object) -> type:
    return type(value)


def _issue(result: Any) -> Any:
    assert isinstance(result, Err)
    return cast(Any, result).error.issue


@testing.effect
def test_re_running_a_compiled_struct_decoder_keeps_earlier_results_intact():
    """re-running a compiled Struct decoder keeps earlier results intact"""
    ids = 0

    def next_id(_value: object, _options: object) -> Any:
        def bump() -> int:
            nonlocal ids
            ids += 1
            return ids

        return fx.sync(bump)

    schema = struct(
        id=S.Number.pipe(S.decode(T.Transformation(G.transform_effect(next_id), G.passthrough())))
    )
    jit_compiler.enable(schema.ast)
    program = S.decode_unknown_effect(schema)({"id": 0})
    first = yield from program
    second = yield from program
    assert [first, second] == [{"id": 1}, {"id": 2}]


def test_preserves_template_literal_issues_after_compilation():
    """preserves template literal issues after compilation"""
    schema = S.TemplateLiteral("count:", S.Int.check(S.is_greater_than(0)))
    inputs: list[object] = ["count:1", "count:0", "count:1.5", "invalid", None]

    def snapshot() -> list[object]:
        decode = S.decode_unknown_result(schema)
        return [
            (type(r).__name__, r.value if isinstance(r, Ok) else str(r.error))
            for r in map(decode, inputs)
        ]

    interpreted = snapshot()
    jit_compiler.enable(schema.ast)
    assert snapshot() == interpreted


@pytest.mark.parametrize("suspended", [False, True])
@testing.effect
def test_preserves_missing_and_present_undefined_through_eager_and_suspended_transformations(
    suspended: bool,
):
    """preserves missing and present undefined through eager and suspended transformations"""
    seen: list[object] = []

    def decode(input: Any, _options: object) -> Any:
        seen.append(input)
        output = None if input is None or input.value == "omit" else Some(None)
        return fx.sync(lambda: output) if suspended else fx.succeed(output)

    value = S.Unknown.pipe(
        S.decode(T.Transformation(G.transform_optional_effect(decode), G.passthrough()))
    )
    schema = struct(value=Opt(value))
    for compiled in (False, True):
        if compiled:
            jit_compiler.enable(schema.ast)
        seen.clear()
        parse = S.decode_unknown_effect(schema)
        assert (yield from parse({})) == {}
        assert (yield from parse({"value": "omit"})) == {}
        assert (yield from parse({"value": "present"})) == {"value": None}
        assert seen == [None, Some("omit"), Some("present")]


@pytest.mark.parametrize("suspended", [False, True])
@testing.effect
def test_continues_encoding_checkpoints_after_middleware_recovery_without_replaying_transformations(
    suspended: bool,
):
    """continues encoding checkpoints after middleware recovery without replaying transformations"""
    events: list[str] = []

    def first(input: str) -> float:
        events.append("first")
        return float(input)

    def last(input: float) -> str:
        events.append("last")
        return str(int(input))

    def middleware(effect: Any, _options: object) -> Any:
        def recover(_: object) -> Any:
            events.append("recover")
            return fx.sync(lambda: Some(1.0)) if suspended else fx.succeed(Some(1.0))

        return effect.catch_eager(recover)

    schema = (
        S.String.pipe(
            S.decode_to(S.Number.check(S.is_greater_than(0)), T.transform(decode=first, encode=str))
        )
        .pipe(S.middleware_decoding(middleware))
        .pipe(S.decode_to(S.String, T.transform(decode=last, encode=float)))
    )
    for compiled in (False, True):
        if compiled:
            jit_compiler.enable(schema.ast)
        parse = S.decode_unknown_effect(schema)
        events.clear()
        assert (yield from parse("2")) == "2"
        assert events == ["first", "last"]
        events.clear()
        assert (yield from parse("-1")) == "1"
        assert events == ["first", "recover", "last"]
        events.clear()
        assert (yield from parse(False)) == "1"
        assert events == ["recover", "last"]


@testing.effect
def test_resolved_parsers_return_effects_containing_their_actual_output():
    """resolved parsers return Effects containing their actual output"""
    object_: Any = {"value": "a"}
    cases: list[tuple[Any, Any, Any]] = [
        (S.String, "a", "a"),
        (S.Number, -0.0, -0.0),
        (S.Literal(0), 0, 0),
        (S.Undefined, None, None),
        (S.Json, object_, object_),
        (struct(), 1, 1),
        (S.TemplateLiteral("a"), "a", "a"),
        (S.FiniteFromString, "1", 1.0),
    ]
    for schema, input, expected in cases:
        kind = _type_of(expected)
        for compiled in (False, True):
            if compiled:
                jit_compiler.enable(schema.ast)
            parser = S.decode_unknown_effect(schema)
            output: Any = yield from parser(input).map(lambda value: value)
            assert output == expected
            assert _type_of(output) is kind
            if isinstance(expected, float):
                assert math.copysign(1, output) == math.copysign(1, expected)
            if isinstance(expected, dict):
                assert output is expected or output == expected
            public = yield from S.decode_unknown_effect(schema)(input)
            assert public == expected


@testing.effect
def test_retains_public_success_values_across_subsequent_and_reentrant_parser_calls():
    """retains public success values across subsequent and reentrant parser calls"""
    reenter: list[Any] = []
    schema = S.String.check(
        S.make_filter(lambda value: value != "first" or reenter[0]("nested") == "nested")
    )
    for compiled in (False, True):
        if compiled:
            jit_compiler.enable(schema.ast)
        decode = S.decode_unknown_effect(schema)
        decode_sync = S.decode_unknown_sync(schema)
        reenter[:] = [decode_sync]
        first = decode("first")
        second = decode("second")

        def inner(value: str, decode_sync: Any = decode_sync) -> str:
            assert decode_sync("nested") == "nested"
            return value

        assert (yield from first.map(inner)) == "first"
        assert (yield from second) == "second"
        assert (yield from first) == "first"


@testing.effect
def test_preserves_unchanged_fields_before_and_after_asynchronous_transformations():
    """preserves unchanged fields before and after asynchronous transformations"""

    def to_number(input: Any, _options: object) -> Any:
        return fx.yield_now().as_(None if input is None else Some(float(input.value)))

    number = S.String.pipe(
        S.decode_to(
            S.Number, T.Transformation(G.transform_optional_effect(to_number), G.transform(str))
        )
    )
    tuple_ = S.Tuple(S.String, number, S.Undefined).check(
        S.make_filter(lambda v: v[0] == "before" and v[1] == 42 and v[2] is None)
    )
    struct_ = struct(before=S.String, middle=number, after=S.Undefined).check(
        S.make_filter(
            lambda v: v["before"] == "before" and v["middle"] == 42 and v["after"] is None
        )
    )
    for compiled in (False, True):
        if compiled:
            jit_compiler.enable(tuple_.ast)
            jit_compiler.enable(struct_.ast)
        assert (yield from S.decode_unknown_effect(tuple_)(["before", "42", None])) == (
            "before",
            42.0,
            None,
        )
        assert (
            yield from S.decode_unknown_effect(struct_)(
                {"before": "before", "middle": "42", "after": None}
            )
        ) == {"before": "before", "middle": 42.0, "after": None}


class _Operation:
    """A callable operation with an attribute that must not be read."""

    def __init__(self, seen: list[object], result: Any) -> None:
        self.seen = seen
        self.result = result

    def __call__(self, input: object, options: object) -> Any:
        self.seen.append(options)
        return self.result(input)

    @property
    def default(self) -> Any:
        raise RuntimeError("Not part of the compiled decoder contract")


def test_calls_installed_operations_with_options_without_inspecting_extra_function_properties():
    """calls installed operations with options without inspecting extra function properties"""
    schema = struct(value=S.String)
    seen: list[object] = []
    is_ = _Operation(seen, _true)
    decode = _Operation(seen, _same_input)
    SC.set(schema.ast, SC.CompiledDecoder(is_=is_, decode=decode, decode_effect=ok))
    input = {"value": "a"}
    assert S.is_(schema)(input) is True
    assert S.decode_unknown_sync(schema)(input) is input
    options: S.ParseOptions = {"report_input": True}
    assert S.decode_unknown_sync(schema, **options)(input) is input
    assert seen == [SC.DEFAULT_PARSE_OPTIONS, SC.DEFAULT_PARSE_OPTIONS, options]
    assert seen[0] is SC.DEFAULT_PARSE_OPTIONS
    assert seen[1] is SC.DEFAULT_PARSE_OPTIONS


def test_bounds_inlining_of_shared_subgraphs():
    """bounds inlining of shared subgraphs"""
    schema: Any = struct(value=Opt(S.String))
    valid: object = {"value": "value"}
    invalid: object = {"value": 1}
    for _ in range(16):
        schema = struct(left=Opt(schema), right=Opt(schema))
        valid = {"left": valid}
        invalid = {"left": invalid}
    cases: list[tuple[Any, object, object]] = [
        (schema, valid, invalid),
        (schema, {"left": {"right": {}}}, {"left": {"right": 1}}),
        (S.Array(schema), ({},), (1,)),
        (S.Union(schema, S.String), {}, 1),
    ]
    for case, ok_input, bad_input in cases:
        expected = S.decode_unknown_result(case)(bad_input)
        assert isinstance(expected, Err)
        jit_compiler.enable(case.ast)
        assert S.decode_unknown_sync(case)(ok_input) == ok_input
        assert S.is_(case)(ok_input) is True
        assert S.is_(case)(bad_input) is False
        assert S.decode_unknown_result(case)(bad_input) == expected


def test_bounds_generated_composed_parsers_for_wide_objects():
    """bounds generated composed parsers for wide objects"""
    schema = struct_of({f"key{i}": Opt(S.String) for i in range(4096)})
    jit_compiler.enable(schema.ast)
    input = {"key4095": "last"}
    assert S.decode_unknown_sync(schema)(input) == input
    assert S.is_(schema)(input) is True
    assert S.is_(schema)({"key4095": 1}) is False


def test_applies_generation_limits_to_every_occurrence_of_a_reused_schema():
    """applies generation limits to every occurrence of a reused schema"""

    def compiles(schema: Any) -> bool:
        return _codegen.generate(schema.ast, "decode") is not None

    def nest(schema: Any, depth: int) -> Any:
        for _ in range(depth):
            schema = struct(n=schema)
        return schema

    assert compiles(nest(S.String, 256))
    assert not compiles(nest(S.String, 257))
    inner = nest(S.String, 200)
    assert not compiles(nest(inner, 57))
    assert compiles(nest(inner, 56))
    assert not compiles(nest(inner, 57))

    field = struct_of({f"f{i}": S.String for i in range(600)})
    assert not compiles(struct(a=field, b=field, c=field, d=field))
    assert compiles(struct(a=field, b=field, c=field))


def test_does_not_generate_code_for_schemas_nesting_a_declaration_or_suspension():
    """does not generate code for schemas nesting a declaration or suspension"""
    recursive: Any = None
    recursive = struct(next=Opt(S.suspend(lambda: recursive)))
    for field in (S.Option(S.Number), recursive):
        assert _codegen.generate(struct(a=struct(b=field)).ast, "decode") is None


def test_does_not_reanalyse_a_nested_schema_that_cannot_be_generated_for_each_enclosing_schema(
    monkeypatch: pytest.MonkeyPatch,
):
    """does not reanalyse a nested schema that cannot be generated for each enclosing schema"""
    from pyfect.schema import ast as A

    date = S.Option(S.Number).ast
    levels: list[A.AST] = [date]
    for i in range(50):
        levels.append(A.Objects((A.PropertySignature("n", levels[i]),)))
    reads = 0
    children = _codegen._children  # pyright: ignore[reportPrivateUsage]
    blocks = _codegen._blocks  # pyright: ignore[reportPrivateUsage]

    def counting_children(ast: A.AST) -> Any:
        nonlocal reads
        reads += ast is date
        return children(ast)

    def counting_blocks(ast: A.AST) -> bool:
        nonlocal reads
        reads += ast is date
        return blocks(ast)

    monkeypatch.setattr(_codegen, "_children", counting_children)
    monkeypatch.setattr(_codegen, "_blocks", counting_blocks)
    for ast in reversed(levels[1:]):
        assert _codegen.generate(ast, "decode") is None
    assert reads < 10


@pytest.mark.parametrize("mode", ["any_of", "one_of"])
def test_preserves_repeated_union_members_when_selecting_generated_decoders(mode: Any):
    """preserves repeated Union members when selecting generated decoders"""
    member = struct(kind=S.Literal("a"), value=S.Number)
    schema = S.Union(
        member, struct(kind=S.Literal("b"), value=S.String), member, S.Never, mode=mode
    )
    jit_compiler.enable(schema.ast)
    decode = S.decode_unknown_result(schema)
    is_ = S.is_(schema)
    input = {"kind": "a", "value": 1}
    assert is_(input) is (mode == "any_of")
    result = decode(input)
    if mode == "any_of":
        assert result == Ok(input)
    else:
        assert isinstance(_issue(result), OneOf)
    other = {"kind": "b", "value": "value"}
    assert is_(other) is True
    assert decode(other) == Ok(other)


def test_stops_one_of_after_its_second_successful_candidate():
    """stops oneOf after its second successful candidate"""

    def third(_: object) -> bool:
        raise RuntimeError("The third candidate must not be evaluated")

    schema = S.Union(
        S.String.check(S.is_min_length(1)),
        S.String.check(S.is_max_length(10)),
        S.String.check(S.make_filter(third)),
        mode="one_of",
    )
    for compiled in (False, True):
        if compiled:
            jit_compiler.enable(schema.ast)
        assert S.is_(schema)("hello") is False
        options: list[S.ParseOptions] = [{}, {"errors": "all"}]
        for option in options:
            assert isinstance(_issue(S.decode_unknown_result(schema, **option)("hello")), OneOf)


def _same(a: object, b: object) -> bool:
    return a == b and type(a) is type(b) and math.copysign(1, a) == math.copysign(1, b)  # type: ignore[arg-type]


@pytest.mark.parametrize("literal", [0.0, -0.0])
@testing.effect
def test_accepts_both_zero_signs_and_preserves_the_input_across_parser_adapters(literal: float):
    """accepts both zero signs and preserves the input across parser adapters"""
    options: list[S.ParseOptions] = [{}, {"errors": "all"}, {"report_input": True}]
    schemas: list[Any] = [
        S.Literal(literal),
        S.Union(S.Literal(literal), S.Literal(1)),
        S.Literal(literal).check(S.make_filter(lambda n: math.copysign(1, n) < 0)),
    ]
    for schema in schemas:
        nested = struct(values=S.Array(schema))
        for compiled in (False, True):
            if compiled:
                jit_compiler.enable(schema.ast)
                jit_compiler.enable(nested.ast)
            for input in (0.0, -0.0):
                if schema.ast.checks and math.copysign(1, input) > 0:
                    assert S.is_(schema)(input) is False
                    assert isinstance(S.decode_unknown_result(schema)(input), Err)
                    continue
                assert S.is_(schema)(input) is True
                for option in options:
                    assert _same(S.decode_unknown_sync(schema, **option)(input), input)
                    assert _same(S.encode_unknown_sync(schema, **option)(input), input)
                    result = S.decode_unknown_result(schema, **option)(input)
                    assert isinstance(result, Ok)
                    assert _same(result.value, input)
                    exit = S.decode_unknown_exit(schema, **option)(input)
                    assert isinstance(exit, Success)
                    assert _same(exit.value, input)
                    optional = S.decode_unknown_option(schema, **option)(input)
                    assert isinstance(optional, Some)
                    assert _same(optional.value, input)
                    output = yield from S.decode_unknown_effect(schema, **option)(input)
                    assert _same(output, input)
                    decoded = S.decode_unknown_sync(nested, **option)({"values": [input]})
                    assert _same(decoded["values"][0], input)


def test_retains_the_original_encoding_ast_in_local_checks():
    """retains the original encoding AST in local checks"""
    from pyfect.schema.ast import Filter

    holder: list[Any] = []

    def run(_input: object, ast: Any, _options: object) -> Any:
        if ast is holder[0].ast and ast.encoding is not None:
            return None
        from pyfect.schema.issue import InvalidValue

        return InvalidValue()

    schema = S.NumberFromString.check(Filter(run, None, False))
    holder.append(schema)
    assert S.decode_unknown_sync(schema)("1") == 1
    jit_compiler.enable(schema.ast)
    assert S.decode_unknown_sync(schema)("1") == 1


def test_retains_the_original_encoding_ast_in_structural_issues():
    """retains the original encoding AST in structural issues"""
    schema = S.String.pipe(
        S.decode_to(S.Number, cast(Any, T.transform(decode=lambda _: "invalid", encode=str)))
    )
    for compiled in (False, True):
        if compiled:
            jit_compiler.enable(schema.ast)
        issue = _issue(S.decode_unknown_result(schema)("input"))
        assert isinstance(issue, InvalidType)
        assert issue.ast is schema.ast


class _Accessors:
    def __init__(self) -> None:
        self.reads: list[str] = []

    @property
    def is_(self) -> Any:
        self.reads.append("is")
        return _always

    @property
    def decode(self) -> Any:
        self.reads.append("decode")
        return _identity

    @property
    def decode_effect(self) -> Any:
        self.reads.append("decode_effect")
        return ok


def test_installs_accessors_without_evaluating_them_and_reads_only_the_selected_operation_once():
    """installs accessors without evaluating them and reads only the selected operation once"""
    schema = struct(value=S.String)
    decoder = _Accessors()
    SC.set(schema.ast, decoder)
    assert decoder.reads == []
    assert S.is_(schema)({"value": "a"}) is True
    assert S.is_(schema)({"value": "b"}) is True
    assert decoder.reads == ["is"]
    input = {"value": "a"}
    assert S.decode_unknown_sync(schema)(input) is input
    assert S.decode_unknown_sync(schema)(input) is input
    assert decoder.reads == ["is", "decode"]


class _AbsentIs:
    def __init__(self) -> None:
        self.reads = 0

    @property
    def is_(self) -> None:
        self.reads += 1

    decode = staticmethod(_identity)
    decode_effect = staticmethod(ok)


def test_memoizes_an_absent_optional_operation():
    """memoizes an absent optional operation"""
    schema = struct(value=S.String)
    decoder = _AbsentIs()
    SC.set(schema.ast, decoder)
    assert S.is_(schema)({"value": "a"}) is True
    assert S.is_(schema)({"value": "b"}) is True
    assert decoder.reads == 1


class _InvalidFast:
    __slots__ = ("reads",)

    def __init__(self) -> None:
        self.reads: list[str] = []

    @property
    def decode(self) -> Any:
        self.reads.append("decode")
        return _invalid

    @property
    def decode_effect(self) -> Any:
        self.reads.append("decode_effect")
        return ok


def test_shares_lazy_detailed_decoding_across_public_adapters_without_mutating_the_decoder():
    """shares lazy detailed decoding across public adapters without mutating the supplied decoder"""
    schema = struct(value=S.String)
    decoder = _InvalidFast()
    SC.set(schema.ast, decoder)
    input = {"value": "a"}
    assert S.decode_unknown_sync(schema)(input) is input
    assert S.decode_unknown_result(schema)(input) == Ok(input)
    assert S.decode_unknown_sync(schema, report_input=True)(input) is input
    assert decoder.reads == ["decode", "decode_effect"]


def test_does_not_restart_validation_inside_the_detailed_decoder():
    """does not restart validation inside the detailed decoder"""
    schema = struct(values=S.Array(struct(value=S.String)))
    jit_compiler.enable(schema.ast)
    item = Getters({"value": 1})
    assert isinstance(S.decode_unknown_result(schema)({"values": [item]}), Err)
    assert item.reads["value"] == 2


def test_uses_the_interpreter_after_selective_jit_generation_fails(
    monkeypatch: pytest.MonkeyPatch,
):
    """uses the interpreter after selective JIT generation fails"""
    schema = struct(value=S.String)
    original = builtins.exec
    attempts = 0

    def failing(source: Any, *args: Any) -> None:
        nonlocal attempts
        if source == "pass":
            original(source, *args)
            return
        attempts += 1
        raise SyntaxError("generated source defect")

    monkeypatch.setattr(builtins, "exec", failing)
    jit_compiler.enable(schema.ast)
    decode = S.decode_unknown_sync(schema)
    assert decode({"value": "a", "extra": True}) == {"value": "a"}
    assert isinstance(S.decode_unknown_result(schema)({"value": 1}), Err)
    assert decode({"value": "b"}) == {"value": "b"}
    assert attempts == 1
