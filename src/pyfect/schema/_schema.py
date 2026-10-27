"""The schema types: ``Bottom`` (every schema object) and the ``Codec``
protocol (what takes a schema accepts)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Generic, Never, Protocol, Self, TypeIs, TypeVar, Unpack, cast

from pyfect._core import Effect
from pyfect.effect import from_exit
from pyfect.exit import Success
from pyfect.option import Option, Some
from pyfect.schema._adapters import CONSTRUCTOR, OPTION, raise_schema_failure, schema_error_of
from pyfect.schema._error import SchemaError
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast import AST, Check, annotate, append_checks
from pyfect.schema.issue import Issue

T_co = TypeVar("T_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=T_co)
RD_co = TypeVar("RD_co", covariant=True, default=Never)
RE_co = TypeVar("RE_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True, eq=False)
class Bottom(Generic[T_co, E_co, RD_co, RE_co]):
    """A schema: decodes an ``E`` (Encoded) into a ``T`` (Type) and encodes
    back, needing the services ``RD`` to decode and ``RE`` to encode
    (Effect's ``Bottom`` / ``Codec<T, E, RD, RE>``). ``ast`` is its node."""

    ast: AST

    def __codec__(self) -> Bottom[T_co, E_co, RD_co, RE_co]:
        return self

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        """``f(self)``. One function per call, as ``Effect.pipe``."""
        return f(self)

    def annotate(self, **annotations: object) -> Self:
        """This schema with annotations merged over its own: ``identifier``
        names it in messages (``Expected <identifier>``), ``message``
        replaces its message, ``title`` / ``description`` / ... document it.
        On a schema with checks they annotate the last check."""
        return replace(self, ast=annotate(self.ast, annotations))

    def check(self, first: Check[T_co], /, *rest: Check[T_co]) -> Self:
        """This schema with checks run, in order, on each value it accepts
        (``S.is_min_length(3)``, ``S.make_filter(...)``, ...)."""
        return replace(self, ast=append_checks(self.ast, (first, *rest)))

    def make[A](
        self: Bottom[A, object, object, object], input: A, /, **options: Unpack[ParseOptions]
    ) -> A:
        """``input`` checked against the decoded side; raises ``SchemaError``."""
        match self.ast.to_type().parse(input, options):
            case Success(value):
                return cast("A", value)
            case failure:
                raise_schema_failure(failure.cause.map(SchemaError), CONSTRUCTOR)

    def make_option[A](
        self: Bottom[A, object, object, object], input: A, /, **options: Unpack[ParseOptions]
    ) -> Option[A]:
        """``Some(value)``, or ``None`` when ``input`` is invalid."""
        match self.ast.to_type().parse(input, options):
            case Success(value):
                return Some(cast("A", value))
            case failure:
                schema_error_of(failure.cause.map(SchemaError), OPTION)
                return None

    def make_effect[A](
        self: Bottom[A, object, object, object], input: A, /, **options: Unpack[ParseOptions]
    ) -> Effect[A, Issue]:
        """``make`` as an effect failing with the bare ``Issue``, as Effect's
        ``makeEffect`` (so an enclosing schema can add its path)."""
        return cast("Effect[A, Issue]", from_exit(self.ast.to_type().parse(input, options)))


class Codec(Protocol[T_co, E_co, RD_co, RE_co]):
    """What takes a schema accepts: a schema object (``Bottom``) or, later,
    a schema class. ``Codec[T, E, RD, RE]`` reads as Effect's ``Codec``."""

    def __codec__(self) -> Bottom[T_co, E_co, RD_co, RE_co]: ...


type Top = Codec[object, object, object, object]
type Schema[A] = Codec[A, object, object, object]
type Decoder[A, R = Never] = Codec[A, object, R, object]
type Encoder[I, R = Never] = Codec[object, I, object, R]


def is_schema(value: object) -> TypeIs[Bottom[object, object, object, object]]:
    return isinstance(value, Bottom)
