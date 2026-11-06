"""Guard (trawl T4): no combinator caps how many classes it matches.

Effect's ``catchTag`` takes any number of tags. ``catch_tag((A, B, C, D), f)``
once failed to type-check because its overloads spelled tuples of exactly
two and three classes. Classes to match are typed ``Tags[T]``
(``pyfect._tags``): one class, or a tuple of any number. This walks the
source for fixed-length ``tuple[type[...], ...]`` annotations and checks the
runtime takes many tags.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

import pyfect as fx
from pyfect import layer

SRC = Path(fx.__file__).parent


def _fixed_type_tuples(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "tuple"
            and isinstance(node.slice, ast.Tuple)
        ):
            continue
        items = node.slice.elts
        variadic = any(isinstance(i, ast.Constant) and i.value is Ellipsis for i in items)
        all_types = all(
            isinstance(i, ast.Subscript) and isinstance(i.value, ast.Name) and i.value.id == "type"
            for i in items
        )
        if all_types and not variadic and len(items) > 1:
            lines.append(node.lineno)
    return lines


def test_no_fixed_length_tuple_of_classes_in_signatures() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{line}"
        for path in sorted(SRC.rglob("*.py"))
        for line in _fixed_type_tuples(ast.parse(path.read_text(), str(path)))
    ]
    assert offenders == [], f"use pyfect._tags.Tags[T] instead of a fixed tuple: {offenders}"


def test_the_guard_finds_a_fixed_tuple() -> None:
    tree = ast.parse("def f(tag: tuple[type[A], type[B]]) -> None: ...")
    assert _fixed_type_tuples(tree) == [1]
    assert _fixed_type_tuples(ast.parse("def f(tag: tuple[type[A], ...]) -> None: ...")) == []


@dataclass
class _A(fx.TaggedError):
    pass


@dataclass
class _B(fx.TaggedError):
    pass


@dataclass
class _C(fx.TaggedError):
    pass


@dataclass
class _D(fx.TaggedError):
    pass


@dataclass
class _E(fx.TaggedError):
    pass


_TAGS = (_A, _B, _C, _D, _E)


def test_catch_tag_catches_the_fifth_of_five_classes() -> None:
    caught = fx.fail(_E()).pipe(fx.catch_tag(_TAGS, lambda e: fx.succeed(type(e).__name__)))
    assert fx.run_blocking(caught) == "_E"


def test_stream_channel_and_layer_catch_tag_take_five_classes() -> None:
    stream = fx.stream.fail(_D()).pipe(fx.stream.catch_tag(_TAGS, lambda _: fx.stream.make(1)))
    assert fx.run_blocking(stream.run_collect()) == [1]
    channel = fx.channel.fail(_C()).pipe(
        fx.channel.catch_tag(_TAGS, lambda _: fx.channel.succeed(2))
    )
    assert fx.run_blocking(channel.run_collect()) == [2]

    class Port(fx.Tag[int]): ...

    built = layer.effect(Port, fx.fail(_B())).pipe(
        layer.catch_tag(_TAGS, lambda _: layer.succeed(Port, 3))
    )
    assert fx.run_blocking(Port().pipe(fx.provide(built))) == 3
