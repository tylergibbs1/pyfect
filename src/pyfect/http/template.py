"""Text templates whose interpolations may be effects or streams (Effect's
``Template``), for HTML responses.

A template is its literal strings and the values between them, as a tagged
template literal gives them; on Python 3.14 a t-string is one too::

    template.make(["<p>Hello, ", "!</p>"], current_user_name)
    template.make(t"<p>Hello, {current_user_name}!</p>")   # Python 3.14

A value is a primitive (``str``, ``int``, ``float``, ``bool``; ``None``
renders as nothing; a sequence renders its items joined), a ``Some``, or an
effect of one. ``stream`` also takes streams, and writes each part as soon
as it is known. Effects run concurrently.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Never, Protocol, cast, overload

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._js import js_number
from pyfect.effect import succeed
from pyfect.option import Some
from pyfect.stream import Stream, from_iterable
from pyfect.stream import succeed as succeed_stream

type PrimitiveValue = str | int | float | bool | None
type Primitive = PrimitiveValue | Sequence[PrimitiveValue]
type Interpolated[E = Never, R = Never] = Primitive | Some[Primitive] | Effect[Primitive, E, R]
type InterpolatedWithStream[E = Never, R = Never] = Interpolated[E, R] | Stream[Primitive, E, R]


class _Interpolation(Protocol):
    @property
    def value(self) -> object: ...


class TemplateLike(Protocol):
    """Python 3.14's ``string.templatelib.Template`` (a t-string)."""

    @property
    def strings(self) -> tuple[str, ...]: ...
    @property
    def interpolations(self) -> tuple[_Interpolation, ...]: ...


def primitive_to_string(value: Primitive) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return js_number(value)
    if value is None:
        return ""
    return "".join(primitive_to_string(item) for item in value)


def _parts(
    strings: Sequence[str] | TemplateLike, args: tuple[object, ...]
) -> tuple[Sequence[str], tuple[object, ...]]:
    if isinstance(strings, Sequence):
        return strings, args
    return strings.strings, tuple(i.value for i in strings.interpolations)


def _consolidate(strings: Sequence[str], values: list[str]) -> str:
    out = [part for pair in zip(strings, values, strict=False) for part in pair]
    return "".join(out) + strings[-1]


@overload
def make(strings: TemplateLike, /) -> Effect[str, Any, Any]: ...
@overload
def make[EE = Never, RR = Never](
    strings: Sequence[str], /, *args: Interpolated[EE, RR]
) -> Effect[str, EE, RR]: ...
def make(strings: Sequence[str] | TemplateLike, /, *args: object) -> Effect[str, Any, Any]:
    """The text of the template, after running its effects concurrently.
    ``strings`` holds one more string than there are ``args``."""
    texts, values = _parts(strings, args)
    rendered = [""] * len(values)
    effects: list[tuple[int, Effect[Primitive, Any, Any]]] = []
    for index, value in enumerate(values):
        if isinstance(value, Some):
            rendered[index] = primitive_to_string(cast("Some[Primitive]", value).value)
        elif isinstance(value, Effect):
            effects.append((index, cast("Effect[Primitive, Any, Any]", value)))
        else:
            rendered[index] = primitive_to_string(cast("Primitive", value))
    if not effects:
        return succeed(_consolidate(texts, rendered))

    def run(entry: tuple[int, Effect[Primitive, Any, Any]]) -> Effect[None, Any, Any]:
        index, effect = entry

        def store(value: Primitive) -> None:
            rendered[index] = primitive_to_string(value)

        return effect.map(store)

    return for_each(effects, run, concurrency="unbounded").map(
        lambda _: _consolidate(texts, rendered)
    )


type _Chunk = str | Effect[str, Any, Any] | Stream[str, Any, Any]


@overload
def stream(strings: TemplateLike, /) -> Stream[str, Any, Any]: ...
@overload
def stream[EE = Never, RR = Never](
    strings: Sequence[str], /, *args: InterpolatedWithStream[EE, RR]
) -> Stream[str, EE, RR]: ...
def stream(strings: Sequence[str] | TemplateLike, /, *args: object) -> Stream[str, Any, Any]:
    """The template's text as it is known, in order: literal text and plain
    values at once, effects (run concurrently) and streams in their
    place."""
    texts, values = _parts(strings, args)
    chunks: list[_Chunk] = []
    buffer = ""
    for index, value in enumerate(values):
        buffer += texts[index]
        if isinstance(value, Some):
            buffer += primitive_to_string(cast("Some[Primitive]", value).value)
        elif isinstance(value, Effect | Stream):
            if buffer:
                chunks.append(buffer)
                buffer = ""
            if isinstance(value, Effect):
                chunks.append(cast("Effect[Primitive, Any, Any]", value).map(primitive_to_string))
            else:
                chunks.append(cast("Stream[Primitive, Any, Any]", value).map(primitive_to_string))
        else:
            buffer += primitive_to_string(cast("Primitive", value))
    buffer += texts[-1]
    if buffer:
        chunks.append(buffer)

    def evaluate(chunk: _Chunk) -> Effect[str | Stream[str, Any, Any], Any, Any]:
        return chunk if isinstance(chunk, Effect) else succeed(chunk)

    def expand(chunk: str | Stream[str, Any, Any]) -> Stream[str, Any, Any]:
        return succeed_stream(chunk) if isinstance(chunk, str) else chunk

    return from_iterable(chunks).map_effect(evaluate, concurrency="unbounded").flat_map(expand)


__all__ = [
    "Interpolated",
    "InterpolatedWithStream",
    "Primitive",
    "PrimitiveValue",
    "TemplateLike",
    "make",
    "primitive_to_string",
    "stream",
]
