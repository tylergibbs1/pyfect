"""Schemas for the ahead-of-time compiler integration run (Effect's
``test/schema/fixtures/aot.ts`` and ``construction.ts``), without the
JavaScript-only cases (symbol keys, unique symbols, ``undefined``).

``build_module`` is the module ``SchemaAOTCompilerBuild`` loads (Effect's
``fixtures/aot-build.ts``)."""

from __future__ import annotations

import enum
from collections.abc import Callable
from typing import Any

import pyfect as fx
import pyfect.schema as S
from pyfect.option import Option, Some
from pyfect.option import map as option_map
from pyfect.schema import getter as G
from pyfect.schema import transformation as T

from ._schema_binary import Opt, struct

events: list[str] = []


def _transform_number(input: str) -> float:
    events.append("transform")
    return float(input)


_transformed = S.String.pipe(
    S.decode_to(
        S.Number.check(S.is_greater_than(0)), T.transform(decode=_transform_number, encode=str)
    )
)


def _pure(input: str) -> Any:
    events.append("pure transform")
    return "invalid" if input == "invalid" else float(input)


_pure_transformed = S.String.pipe(S.decode_to(S.Number, T.transform(decode=_pure, encode=str)))


def _pure_transform(decode: Callable[[str], float]) -> Any:
    return S.String.pipe(S.decode_to(S.Number, T.transform(decode=decode, encode=str)))


_shared_pure_transform = _pure_transform(float)
_repeated_union_member = struct(kind=S.Literal("a"), value=S.Number)


def _middleware(effect: Any, _: object) -> Any:
    events.append("middleware")

    def recover(_: object) -> Any:
        events.append("recover")
        return fx.succeed(Some(1.0))

    return effect.catch_eager(recover)


_with_middleware = _transformed.pipe(S.middleware_decoding(_middleware))


def _async_decode(input: Option[str], _: object) -> Any:
    events.append("async")
    return fx.yield_now().as_(option_map(input, float))


_asynchronous = S.String.pipe(
    S.decode_to(
        S.Number.check(S.is_greater_than(0)),
        T.Transformation(G.transform_optional_effect(_async_decode), G.transform(str)),
    )
)


class _Letters(enum.Enum):
    a = "a"
    b = "b"
    c = 0
    d = 1
    e = 2


def _record(name: str, check: Callable[[Any], bool]) -> Any:
    def run(value: Any) -> bool:
        events.append(name)
        return check(value)

    return S.make_filter(run)


synchronous: dict[str, tuple[Any, list[object]]] = {
    "struct": (
        struct(
            name=S.String,
            nested=struct(count=S.Number.check(S.is_greater_than(0))),
            optional=Opt(S.String),
        ).check(S.make_filter(lambda input: len(input) <= 3)),
        [
            {"name": "a", "nested": {"count": 1, "ignored": True}, "extra": True},
            {"name": "a", "nested": {"count": -1}},
            {"name": 1, "nested": {"count": "invalid"}},
            {"name": "a"},
        ],
    ),
    "array": (
        S.Array(struct(value=S.String)),
        [[{"value": "a", "extra": True}], [{"value": 1}, {}], None],
    ),
    "tuple": (
        S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean),
        [["a", 1, 2, True], ["a", True], ["a", "invalid", False], ["a"]],
    ),
    "tagged": (
        S.Union(
            struct(kind=S.Literal("a"), value=S.String),
            struct(kind=S.Literal("b"), value=S.Number),
        ),
        [{"kind": "b", "value": 1}, {"kind": "b", "value": "invalid"}, {"kind": "c"}],
    ),
    "literals": (S.Literals("a", "b", 0, 1, 2, 3, 4, 5, 6, 7, 8), ["a", -0.0, 8, 9, None]),
    "one_of": (S.Union(S.String, S.Literal("a"), mode="one_of"), ["b", "a", False]),
    "repeated_one_of": (
        S.Union(
            _repeated_union_member,
            struct(kind=S.Literal("b"), value=S.String),
            _repeated_union_member,
            S.Never,
            mode="one_of",
        ),
        [{"kind": "a", "value": 1}, {"kind": "b", "value": "value"}, {"kind": "c"}],
    ),
    "enumeration": (S.Enum(_Letters), ["a", -0.0, 2, "invalid"]),
    "record": (
        S.Record(S.String, struct(count=S.Number)),
        [{"a": {"count": 1}}, {"a": {"count": "invalid"}, "b": {}}, {}],
    ),
    "mixed_record": (
        S.StructWithRest(
            struct(fixed=S.Number), S.Record(S.TemplateLiteral("data-", S.String), S.Number)
        ),
        [
            {"fixed": 1, "data-a": 2},
            {"fixed": 1, "ignored": True},
            {"fixed": 1, "data-a": "invalid"},
        ],
    ),
    "template_literal": (
        S.TemplateLiteral("count:", S.Int.check(S.is_greater_than(0))),
        ["count:1", "count:0", "count:1.5", "invalid", None],
    ),
    "template_literal_parser": (
        S.TemplateLiteralParser("bit:", S.BooleanFromBit),
        ["bit:1", "bit:0", "bit:true", None],
    ),
    "transformed": (_transformed, ["2", "-1", False]),
    "checked_transformed_struct": (
        struct(value=_transformed).check(
            _record("struct check", lambda output: output["value"] < 10 and len(output) == 1)
        ),
        [{"value": "2", "extra": True}, {"value": "12"}, {"value": "-1"}, {}],
    ),
    "encoding_checked_transformed_struct": (
        S.flip(
            S.flip(struct(value=_transformed)).check(
                _record("encoding check", lambda input: input["value"] != "02")
            )
        ),
        [{"value": "2"}, {"value": "02"}, {"value": "-1"}],
    ),
    "transformed_struct": (
        struct(before=S.String, value=_transformed, after=S.Boolean),
        [
            {"before": "a", "value": "2", "after": True},
            {"before": "a", "value": "-1", "after": True},
            {"before": "a", "value": "2", "after": "invalid"},
        ],
    ),
    "pure_transformed_struct": (
        struct(value=_pure_transformed),
        [{"value": "2"}, {"value": False}, {"value": "invalid"}],
    ),
    "pure_transformed_fields": (
        struct(
            first=_shared_pure_transform,
            second=_shared_pure_transform,
            incremented=_pure_transform(lambda input: float(input) + 1),
            doubled=_pure_transform(lambda input: float(input) * 2),
        ),
        [
            {"first": "1", "second": "2", "incremented": "3", "doubled": "4"},
            {"first": False, "second": "2", "incremented": "3", "doubled": "4"},
        ],
    ),
    "middleware": (_with_middleware, ["2", "-1", False]),
}

async_fixture: tuple[Any, list[object]] = (
    struct(before=S.String, value=_asynchronous, after=S.Boolean).check(
        _record("async struct check", lambda output: output["value"] < 10)
    ),
    [
        {"before": "a", "value": "2", "after": True},
        {"before": "a", "value": "12", "after": True},
        {"before": "a", "value": "-1", "after": True},
        {"before": "a", "value": "2", "after": "invalid"},
    ],
)

suspend_evaluations = [0]


def _lazy() -> Any:
    suspend_evaluations[0] += 1
    return struct(value=S.String)


lazy = S.suspend(_lazy)
proof = struct(value=S.String)

construction_events: list[str] = []


def _default() -> float:
    construction_events.append("default")
    return 1.0


_value = S.Number.pipe(S.with_constructor_default(fx.sync(_default)))


def _construction_check(input: Any) -> bool:
    construction_events.append("check")
    return input["value"] > 0


construction_cases: dict[str, tuple[Any, list[object]]] = {
    "struct": (
        struct(value=_value, optional=Opt(S.String)).check(S.make_filter(_construction_check)),
        [{}, {"value": -1}, {"value": "bad", "optional": 1}, {"value": 2, "extra": True}],
    ),
    "array": (S.Array(S.Number), [[1, 2], ["bad", 3], None]),
    "tuple": (
        S.TupleWithRest(S.Tuple(S.Number), S.String, S.Boolean),
        [[], [1, "a", True], ["bad", 1, False], [1, True]],
    ),
    "record": (S.Record(S.String, S.Number), [{"a": 1}, {"a": "bad", "b": "bad"}, {}, None]),
    "union": (
        S.Union(
            struct(_tag=S.tag("A"), value=_value),
            struct(_tag=S.tag("B"), text=S.String),
        ),
        [{}, {"text": "a"}, {"_tag": "A", "value": "bad"}, {"_tag": "C"}],
    ),
    "one_of": (S.Union(S.String, S.Literal("a"), mode="one_of"), ["a", "b", 1]),
    "transformed": (
        struct(value=S.FiniteFromString.pipe(S.with_constructor_default(fx.succeed(1.0)))),
        [{}, {"value": "1"}, {"value": 2}],
    ),
    "empty": (struct(), [{}, 1, [], None]),
}

construction_options: list[S.ParseOptions] = [
    {},
    {"errors": "all", "report_input": True},
    {"on_excess_property": "error"},
    {"disable_checks": True},
]

construction_schemas: dict[str, Any] = {
    f"construct_{name}": S.Bottom(schema.__codec__().ast.to_type())
    for name, (schema, _) in construction_cases.items()
}

schemas: dict[str, Any] = {
    **construction_schemas,
    **{name: schema for name, (schema, _) in synchronous.items()},
    "asynchronous": async_fixture[0],
    "lazy": lazy,
    "proof_array": S.Array(proof),
    "proof": proof,
}


def roots() -> list[Any]:
    return [*(schema.__codec__().ast for schema in schemas.values()), proof.ast]
