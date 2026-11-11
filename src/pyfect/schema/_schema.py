"""The schema types: ``Bottom`` (every schema object) and the ``Codec``
protocol (what takes a schema accepts)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Generic, Never, Protocol, Self, TypeIs, TypeVar, Unpack, cast

from pyfect._core import Effect
from pyfect.exit import Success
from pyfect.option import Option, Some
from pyfect.schema._adapters import CONSTRUCTOR, OPTION, raise_schema_failure, schema_error_of
from pyfect.schema._error import SchemaError
from pyfect.schema._make import Maker
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast import (
    AST,
    Check,
    annotate,
    append_checks,
    replace_context,
    run_now,
    to_effect,
)
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

    def __get_pydantic_core_schema__(
        self: Bottom[Any, Any, Never, Never], source: object, handler: object
    ) -> object:
        """This schema as a pydantic field type (``pyfect.pydantic``)."""
        from pyfect import pydantic

        return pydantic.get_pydantic_core_schema(self, source, cast("Any", handler))

    def __get_pydantic_json_schema__(
        self: Bottom[Any, Any, Never, Never], core: object, handler: object
    ) -> object:
        from pyfect import pydantic

        return pydantic.get_pydantic_json_schema(self, cast("Any", core), cast("Any", handler))

    def annotate(self, /, **annotations: object) -> Self:
        """This schema with annotations merged over its own: ``identifier``
        names it in messages (``Expected <identifier>``), ``message``
        replaces its message, ``title`` / ``description`` / ... document it.
        On a schema with checks they annotate the last check."""
        return replace(self, ast=annotate(self.ast, annotations))

    def annotate_encoded(self, /, **annotations: object) -> Self:
        """This schema with annotations on its encoded side (Effect's
        ``annotateEncoded``); a schema without a transformation is its own
        encoded side."""
        return replace(self, ast=annotate(self.ast.flip(), annotations).flip())

    def override_to_equivalence[A, E, RD, RE](
        self: Bottom[A, E, RD, RE], f: Callable[[], Callable[[A, A], bool]], /
    ) -> Bottom[A, E, RD, RE]:
        """This schema compared by ``f()`` in ``S.to_equivalence`` (Effect's
        ``overrideToEquivalence``)."""

        def derive(_: tuple[object, ...]) -> Callable[[A, A], bool]:
            return f()

        return self.annotate(to_equivalence=derive)

    def override_to_formatter[A, E, RD, RE](
        self: Bottom[A, E, RD, RE], f: Callable[[], Callable[[A], str]], /
    ) -> Bottom[A, E, RD, RE]:
        """This schema written by ``f()`` in ``S.to_formatter`` (Effect's
        ``overrideToFormatter``)."""

        def derive(_: tuple[object, ...]) -> Callable[[A], str]:
            return f()

        return self.annotate(to_formatter=derive)

    def annotate_key(self, /, **annotations: object) -> Self:
        """This schema with annotations for the struct key holding it
        (Effect's ``annotateKey``): ``message_missing_key`` replaces
        ``"Missing key"``."""
        key_annotations = {**(self.ast.key_annotations or {}), **annotations}
        return replace(self, ast=replace_context(self.ast, key_annotations=key_annotations))

    def check(self, first: Check[T_co], /, *rest: Check[T_co]) -> Self:
        """This schema with checks run, in order, on each value it accepts
        (``S.is_min_length(3)``, ``S.make_filter(...)``, ...)."""
        return replace(self, ast=append_checks(self.ast, (first, *rest)))

    def make[A](
        self: Bottom[A, object, object, object], input: A, /, **options: Unpack[ParseOptions]
    ) -> A:
        """``input`` checked against the decoded side, its missing keys and
        elements filled by their constructor defaults
        (``with_constructor_default``); raises ``SchemaError``."""
        match run_now(Maker(self.ast.to_type()).parse(input, options, True)):
            case Success(value):
                return cast("A", value)
            case failure:
                raise_schema_failure(failure.cause.map(SchemaError), CONSTRUCTOR)

    def make_option[A](
        self: Bottom[A, object, object, object], input: A, /, **options: Unpack[ParseOptions]
    ) -> Option[A]:
        """``Some(value)``, or ``None`` when ``input`` is invalid."""
        match run_now(Maker(self.ast.to_type()).parse(input, options, True)):
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
        parsed = Maker(self.ast.to_type()).parse(input, options, False)
        return cast("Effect[A, Issue]", to_effect(parsed))


class Codec(Protocol[T_co, E_co, RD_co, RE_co]):
    """What takes a schema accepts: a schema object (``Bottom``) or a schema
    class (``S.Class``, ...). ``Codec[T, E, RD, RE]`` reads as Effect's
    ``Codec``."""

    def __codec__(self) -> Bottom[T_co, E_co, RD_co, RE_co]: ...


type Top = Codec[object, object, object, object]
type Schema[A] = Codec[A, object, object, object]
type Decoder[A, R = Never] = Codec[A, object, R, object]
type Encoder[I, R = Never] = Codec[object, I, object, R]


def is_schema(value: object) -> TypeIs[Top]:
    """``value`` is a schema object, a schema class, or a schema adapted to
    Standard Schema."""
    from pyfect.schema._standard_schema import StandardSchemaV1

    return isinstance(value, (Bottom, StandardSchemaV1)) or (
        isinstance(value, type) and hasattr(value, "__codec__")
    )
