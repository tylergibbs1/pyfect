"""Ports of Effect's ``SchemaJITCompilerCheckedSources.test.ts``
("Schema compilers: transformations with checked sources"): with each
compiler installed, decoding, guards and constructors give the
interpreter's results, and every check runs as often as there.

Python mappings: results are compared as values (``Ok`` / ``Err`` of the
``SchemaError``, whose issue holds the schema's own nodes), so Effect's
snapshot describer (identity labels, symbol keys) is plain equality here.
The AOT install writes the compiled module's source and runs it, as Effect
imports the written file. ``undefined`` is ``None``; ``Schema.optional(x)``
is an optional key of ``x | Undefined``; a symbol key is a non-string key.

"inlines a transformation whose source has checks" asserts the text of the
generated code; the port asserts the Python generator's spelling for a
field and, for structs (whose complete decoder inlines each single-link
field in ``runtime.decode``, Effect's ``emitObject``), that inlined fields'
own entries are resolved only once a source value fails the inline check.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

import pytest

import pyfect.schema as S
from pyfect import effect as fx
from pyfect.result import Err, Ok
from pyfect.schema import aot_compiler, ast, jit_compiler
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.compiler import _codegen, _registry

from ._schema_binary import Opt, struct, struct_of
from ._schema_compiler import fresh_registry

__all__ = ["fresh_registry"]

type Compiler = Literal["jit", "aot"]
COMPILERS: tuple[Compiler, ...] = ("jit", "aot")

_OPTION_SETS: list[S.ParseOptions] = [
    {},
    {"report_input": True},
    {"errors": "all", "report_input": True},
    {"on_excess_property": "error", "report_input": True},
    {"disable_checks": True, "report_input": True},
]


class _Counters:
    checks = 0
    transforms = 0


def _counted[A, B](f: Callable[[A], B]) -> Callable[[A], B]:
    def run(a: A) -> B:
        _Counters.transforms += 1
        return f(a)

    return run


def _counted_filter(predicate: Callable[[str], bool], expected: str) -> S.Filter[str]:
    def run(s: str) -> bool:
        _Counters.checks += 1
        return predicate(s)

    return S.make_filter(run, expected=expected)


def _js_number(s: str) -> float:
    """JavaScript's ``Number(s)``."""
    if not s.strip():
        return 0.0
    try:
        return float(s)
    except ValueError:
        return math.nan


def _same(s: str) -> str:
    return s


def _to_number_value(s: str) -> Any:
    return "thirteen" if s == "13" else _js_number(s)


def _prefix(s: str) -> Any:
    return 7 if s == "7" else f"#{s}"


@dataclass
class Fixtures:
    """Effect's ``makeFixtures``: fresh schemas for each case (the registry
    is shared, so no two cases share a node)."""

    def __post_init__(self) -> None:
        self.Digits: Any = S.String.check(
            _counted_filter(lambda s: re.fullmatch(r"[0-9]{1,6}", s) is not None, "digits")
        )
        self.Short: Any = S.String.check(
            _counted_filter(lambda s: len(s) >= 1, "non-empty"),
            _counted_filter(lambda s: len(s) <= 3, "short"),
        )
        self.Checked: Any = S.String.check(S.is_pattern(r"^[a-z ]*$"))
        self.OneOf: Any = S.TemplateLiteral([S.Union(S.String, S.Literal("x"), mode="one_of")])
        self.identity: Any = T.transform(decode=_counted(_same), encode=_same)
        self.to_number: Any = T.Transformation(
            G.transform(_counted(_to_number_value)), G.transform(str)
        )
        self.prefixed: Any = T.transform(decode=_counted(_prefix), encode=lambda s: s[1:])
        self.DigitsToNumber: Any = self.Digits.pipe(S.decode_to(S.Number, self.to_number))
        self.ShortToNumber: Any = self.Short.pipe(S.decode_to(S.Number, self.to_number))
        self.StringToNumber: Any = S.String.pipe(S.decode_to(S.Number, self.to_number))
        self.DigitsToString: Any = self.Digits.pipe(S.decode_to(S.String, self.prefixed))
        self.DigitsPassthrough: Any = self.Digits.pipe(S.decode_to(S.String))

        def two_links_decode(s: str) -> Any:
            return "thirteen" if s == "#13" else _js_number(s[1:])

        self.TwoLinks: Any = self.Digits.pipe(
            S.decode_to(
                S.String.pipe(
                    S.decode_to(
                        S.Number,
                        T.Transformation(
                            G.transform(_counted(two_links_decode)),
                            G.transform(lambda n: f"#{n}"),
                        ),
                    )
                ),
                self.prefixed,
            )
        )


_VALUES: list[object] = ["1", "123456", "13", "7", "", "abc", "1234567", 1, None]

type Replay = Literal["always", "fallback"] | None


@dataclass(frozen=True)
class Case:
    name: str
    schema: Callable[[Fixtures], Any]
    inputs: Sequence[object]
    make: Sequence[object] = ()
    replay: Replay = None


def _in_layouts(
    name: str,
    field: Callable[[Fixtures], Any],
    inputs: Sequence[object],
    *,
    replay: Replay = None,
    own_parser_replays: bool = False,
) -> list[Case]:
    return [
        Case(name, field, inputs, replay=replay or ("always" if own_parser_replays else None)),
        Case(
            f"{name} in a Struct",
            lambda f: struct(n=field(f)),
            [{"n": n} for n in inputs],
            replay=replay or ("fallback" if own_parser_replays else None),
        ),
        Case(
            f"{name} next to a checked field",
            lambda f: struct(s=f.Checked, n=field(f)),
            [{"s": "ok", "n": n} for n in inputs],
            replay=replay or ("fallback" if own_parser_replays else None),
        ),
    ]


_KEY = ("n",)

CASES: list[Case] = [
    *_in_layouts(
        "TemplateLiteral with overlapping oneOf parts", lambda f: f.OneOf, ["x", "y", "", 1]
    ),
    *_in_layouts(
        "nested TemplateLiteral with overlapping oneOf parts",
        lambda f: S.TemplateLiteral(["nested:", f.OneOf]),
        ["nested:x", "nested:y", "wrong", 1],
    ),
    *_in_layouts(
        "TemplateLiteral with oneOf inside anyOf",
        lambda _: S.TemplateLiteral(
            [S.Union(S.Union(S.String, S.Literal("x"), mode="one_of"), S.Literal("z"))]
        ),
        ["x", "y", "z", 1],
    ),
    *_in_layouts(
        "TemplateLiteral with overlapping numeric oneOf parts",
        lambda _: S.TemplateLiteral([S.Union(S.Number, S.Literal("1"), mode="one_of")]),
        ["1", "2", "wrong", 1],
    ),
    *_in_layouts(
        "TemplateLiteral transformation target",
        lambda f: S.String.pipe(S.decode_to(S.TemplateLiteral(["x-", S.String]), f.identity)),
        ["x-a", "wrong", 1],
    ),
    *_in_layouts(
        "TemplateLiteral transformation target with overlapping oneOf parts",
        lambda f: S.String.pipe(S.decode_to(f.OneOf, f.identity)),
        ["x", "y", 1],
    ),
    *_in_layouts(
        "checked source with a oneOf TemplateLiteral target",
        lambda f: f.Checked.pipe(S.decode_to(f.OneOf, f.identity)),
        ["x", "y", "INVALID", 1],
    ),
    *_in_layouts(
        "TemplateLiteral transformation source",
        lambda f: S.TemplateLiteral(["x-", S.String]).pipe(S.decode_to(S.String, f.identity)),
        ["x-a", "wrong", 1],
    ),
    *_in_layouts(
        "TemplateLiteral intermediate transformation",
        lambda f: S.String.pipe(
            S.decode_to(
                S.TemplateLiteral(["x-", S.String]).pipe(S.decode_to(S.String, f.identity)),
                f.identity,
            )
        ),
        ["x-a", "wrong", 1],
    ),
    *_in_layouts("checked source", lambda f: f.DigitsToNumber, _VALUES),
    *_in_layouts("several source checks", lambda f: f.ShortToNumber, _VALUES),
    *_in_layouts("string target", lambda f: f.DigitsToString, _VALUES),
    *_in_layouts("passthrough", lambda f: f.DigitsPassthrough, _VALUES, own_parser_replays=True),
    *_in_layouts("two-link chain", lambda f: f.TwoLinks, _VALUES, own_parser_replays=True),
    Case(
        "Struct with only transformed fields",
        lambda f: struct(a=f.DigitsToNumber, b=f.StringToNumber, c=f.DigitsToString),
        [
            *({"a": a, "b": "2", "c": "3"} for a in _VALUES),
            *({"a": "1", "b": "2", "c": c} for c in _VALUES),
            {"b": "2", "c": "3"},
            {"a": "1", "c": "3"},
            {"a": "abc", "b": 2, "c": "3"},
            {"a": "1", "b": "2", "c": "3", "d": "4"},
            None,
            [],
        ],
    ),
    Case(
        "Struct mixing checked and transformed fields",
        lambda f: struct(s=f.Checked, n=f.DigitsToNumber, m=f.ShortToNumber),
        [
            *({"s": "ok", "n": n, "m": "12"} for n in _VALUES),
            *({"s": "ok", "n": "1", "m": m} for m in _VALUES),
            {"s": "NOT OK", "n": "abc", "m": "1234"},
            {"s": "ok", "m": "12"},
            {"s": "ok", "n": "1", "m": "12", "extra": True},
        ],
    ),
    Case(
        "Struct with several checked transformations",
        lambda f: struct(a=f.DigitsToNumber, b=f.DigitsToNumber, c=f.DigitsToString),
        [
            {"a": "1", "b": "2", "c": "3"},
            {"a": "x", "b": "y", "c": "z"},
            {"a": "1", "b": "13", "c": "3"},
            {"a": "1", "b": "2", "c": "7"},
            {"a": "1", "b": "2", "c": 3},
        ],
    ),
    Case(
        "optional keys",
        lambda f: struct(a=Opt(f.DigitsToNumber), b=Opt(S.Union(f.DigitsToNumber, S.Undefined))),
        [{}, {"a": "1"}, {"a": "x"}, {"b": None}, {"b": "1"}, {"b": "x"}, {"a": None}],
    ),
    Case(
        "constructor defaults",
        lambda f: struct(n=f.DigitsToNumber.pipe(S.with_constructor_default(fx.succeed(0)))),
        [{}, {"n": None}, {"n": "1"}, {"n": "x"}],
        make=[{}, {"n": None}, {"n": 5}, {"n": "x"}],
    ),
    Case(
        "__proto__ key",
        lambda f: struct_of({"__proto__": f.DigitsToNumber, "a": f.DigitsToNumber}),
        [{"__proto__": "1", "a": "2"}, {"__proto__": "x", "a": "2"}, {"a": "2"}],
    ),
    Case(
        "symbol key",
        lambda f: S.Bottom[Any](
            S.ast.Objects(
                (
                    S.ast.PropertySignature(_KEY, f.DigitsToNumber.ast),
                    S.ast.PropertySignature("a", f.DigitsToNumber.ast),
                )
            )
        ),
        [{_KEY: "1", "a": "2"}, {_KEY: "x", "a": "2"}, {"a": "2"}],
    ),
    Case(
        "nested Struct",
        lambda f: struct(outer=struct(s=f.Checked, n=f.DigitsToNumber), n=f.DigitsToNumber),
        [
            {"outer": {"s": "ok", "n": "1"}, "n": "2"},
            {"outer": {"s": "ok", "n": "x"}, "n": "2"},
            {"outer": {"s": "ok", "n": "1"}, "n": "x"},
            {"outer": {"s": "OK", "n": "x"}, "n": "x"},
        ],
    ),
    Case(
        "Array of Structs",
        lambda f: S.Array(struct(s=f.Checked, n=f.DigitsToNumber)),
        [
            [{"s": "ok", "n": "1"}, {"s": "ok", "n": "2"}],
            [{"s": "ok", "n": "1"}, {"s": "ok", "n": "x"}, {"s": "OK", "n": "y"}],
        ],
    ),
    Case(
        "target checks",
        lambda f: struct(
            n=f.Digits.pipe(S.decode_to(S.Number.check(S.is_less_than(100)), f.to_number))
        ),
        [{"n": "1"}, {"n": "100"}, {"n": "x"}],
    ),
    *_in_layouts(
        "checked TemplateLiteral source",
        lambda f: (
            S.TemplateLiteral(["x-", S.String])
            .check(_counted_filter(lambda s: len(s) <= 4, "short"))
            .pipe(S.decode_to(S.String, f.prefixed))
        ),
        ["x-a", "x-abc", "wrong", 1],
        replay="always",
    ),
    *_in_layouts(
        "checked source with a TemplateLiteral target",
        lambda f: f.Digits.pipe(S.decode_to(S.TemplateLiteral(["#", S.String]), f.prefixed)),
        ["1", "7", "x"],
        replay="always",
    ),
    *_in_layouts(
        "checked TemplateLiteral source with a oneOf part",
        lambda f: f.OneOf.check(_counted_filter(lambda s: len(s) >= 1, "non-empty")).pipe(
            S.decode_to(S.String, f.prefixed)
        ),
        ["x", "y"],
        replay="always",
    ),
]


def _install(compiler: Compiler, schema: Any) -> None:
    node = schema.__codec__().ast
    asts = [node, node.to_type()]
    if compiler == "jit":
        for target in asts:
            jit_compiler.enable(target)
        return
    source = aot_compiler.compile(
        [aot_compiler.Target(target, ["decode", "is", "make"]) for target in asts]
    )
    namespace: dict[str, Any] = {}
    exec(compile(source, "<schema-aot-checked-sources>", "exec"), namespace)
    namespace["install"](asts)


def _fallback_options(options: S.ParseOptions) -> bool:
    return options.get("errors") == "all" or "on_excess_property" in options


def _snapshot(schema: Any, case: Case, checks: list[tuple[int, bool]]) -> list[object]:
    decode = S.decode_unknown_result(schema)
    construct = S.make(schema)
    out: list[object] = []

    def run(fallback: bool, f: Callable[[], object]) -> None:
        _Counters.checks = 0
        _Counters.transforms = 0
        result = f()
        checks.append((_Counters.checks, fallback))
        out.append((result, _Counters.transforms))

    for options in _OPTION_SETS:
        for input in case.inputs:
            run(
                _fallback_options(options),
                lambda input=input, options=options: decode(input, **options),
            )
    for input in case.make:

        def made(input: object = input) -> object:
            try:
                return Ok(construct(input))
            except S.SchemaError as error:
                return Err(error)

        run(False, made)
    return out


@pytest.mark.parametrize("compiler", COMPILERS)
@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_matches_the_interpreter(compiler: Compiler, case: Case):
    """aot matches the interpreter: every checked-source case"""
    schema = case.schema(Fixtures())
    node = schema.__codec__().ast
    assert _registry.resolve(node).compiled is None
    interpreted_checks: list[tuple[int, bool]] = []
    compiled_checks: list[tuple[int, bool]] = []
    interpreted = _snapshot(schema, case, interpreted_checks)
    _install(compiler, schema)
    assert _registry.resolve(node).compiled is not None
    compiled = _snapshot(schema, case, compiled_checks)
    # ``repr``: a NaN is equal to itself there (Effect's describer prints it).
    assert compiled == interpreted or repr(compiled) == repr(interpreted)
    for index, (count, fallback) in enumerate(compiled_checks):
        expected = interpreted_checks[index][0]
        if case.replay == "always" or (case.replay == "fallback" and fallback):
            assert expected <= count <= 2 * expected
        else:
            assert count == expected, f"check runs for decode #{index}"


def _preserves_one_of_guards(compiler: Compiler) -> None:
    shapes: list[Callable[[Fixtures], tuple[Any, Callable[[str], object]]]] = [
        lambda f: (f.OneOf, lambda value: value),
        lambda f: (struct(value=f.OneOf), lambda value: {"value": value}),
        lambda f: (S.Array(f.OneOf), lambda value: (value,)),
        lambda f: (S.TemplateLiteral(["nested:", f.OneOf]), lambda value: f"nested:{value}"),
    ]
    for shape in shapes:
        schema, input = shape(Fixtures())
        for compiled in (False, True):
            if compiled:
                _install(compiler, schema)
            is_ = S.is_(schema)
            make = S.make(schema)
            assert is_(input("x")) is False
            assert is_(input("y")) is True
            with pytest.raises(S.SchemaError):
                make(input("x"))
            assert make(input("y")) == input("y")


def test_jit_preserves_oneof_templateliteral_guards_and_constructors():
    """jit preserves oneOf TemplateLiteral guards and constructors"""
    _preserves_one_of_guards("jit")


def test_aot_preserves_oneof_templateliteral_guards_and_constructors():
    """aot preserves oneOf TemplateLiteral guards and constructors"""
    _preserves_one_of_guards("aot")


def _runs_source_checks_once(compiler: Compiler) -> None:
    shapes: list[Callable[[Fixtures], tuple[Any, Callable[[str], object]]]] = [
        lambda f: (f.DigitsToNumber, lambda n: n),
        lambda f: (struct(n=f.DigitsToNumber), lambda n: {"n": n}),
        lambda f: (struct(s=f.Checked, n=f.DigitsToNumber), lambda n: {"s": "ok", "n": n}),
        lambda f: (struct(n=f.TwoLinks), lambda n: {"n": n}),
        lambda f: (struct(s=f.Checked, n=f.TwoLinks), lambda n: {"s": "ok", "n": n}),
        lambda f: (struct(n=f.DigitsPassthrough), lambda n: {"n": n}),
    ]
    for shape in shapes:
        schema, input = shape(Fixtures())
        _install(compiler, schema)
        decode = S.decode_unknown_result(schema)
        for value, succeeds in (("1", True), ("x", False)):
            _Counters.checks = 0
            assert isinstance(decode(input(value)), Ok) is succeeds
            assert _Counters.checks == 1


def test_jit_runs_inlined_source_checks_once():
    """jit runs inlined source checks once"""
    _runs_source_checks_once("jit")


def test_aot_runs_inlined_source_checks_once():
    """aot runs inlined source checks once"""
    _runs_source_checks_once("aot")


def test_inlines_a_transformation_whose_source_has_checks():
    """inlines a transformation whose source has checks"""
    f = Fixtures()
    field = _codegen.generate(f.DigitsToNumber.ast, "decode_effect")
    assert field is not None
    assert "R.decode(" not in field
    assert "R.issues_of(source," in field

    # Every property is inlined, so the properties are resolved lazily.
    both = struct(a=f.DigitsToNumber, b=f.StringToNumber)
    jit_compiler.enable(both.ast)
    a, b = (p.type for p in cast("ast.Objects", both.ast).properties)
    assert S.decode_unknown_sync(both)({"a": "1", "b": "2"}) == {"a": 1, "b": 2}
    assert not a.compiler_entry and not b.compiler_entry
    assert isinstance(S.decode_unknown_result(both)({"a": 1, "b": "2"}), Err)
    assert a.compiler_entry and not b.compiler_entry

    mixed = struct(s=f.Checked, n=f.TwoLinks)
    jit_compiler.enable(mixed.ast)
    n = cast("ast.Objects", mixed.ast).properties[1].type
    assert S.decode_unknown_sync(mixed)({"s": "ok", "n": "1"}) == {"s": "ok", "n": 1}
    assert not n.compiler_entry


def test_distinguishes_symbol_keys_in_snapshots():
    """distinguishes symbol keys in snapshots"""
    a = ("n",)
    b = ("n",)
    shared = object()
    assert {_KEY: 1} != {"('n',)": 1}
    assert {object(): 1} != {object(): 1}
    assert {shared: 1} == {shared: 1}
    assert {a: 1} == {b: 1}  # equal keys are the same key, as Symbol.for's


def test_uses_templateliteral_parsers_for_transformation_diagnostics():
    """uses TemplateLiteral parsers for transformation diagnostics"""
    f = Fixtures()
    source = (
        S.TemplateLiteral(["x-", S.String])
        .check(S.is_max_length(4))
        .pipe(S.decode_to(S.String, f.prefixed))
    )
    target = f.Digits.pipe(S.decode_to(S.TemplateLiteral(["#", S.String]), f.prefixed))
    unchecked = S.String.pipe(S.decode_to(S.TemplateLiteral(["#", S.String]), f.prefixed))
    for schema in (source, target, unchecked):
        own = _codegen.generate(schema.ast, "decode_effect")
        assert own is not None
        assert "R.decode(" in own
        in_struct = _codegen.generate(struct(n=schema).ast, "decode_effect")
        assert in_struct is not None
        assert "R.issues_of(" not in in_struct
