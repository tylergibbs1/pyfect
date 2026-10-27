"""Schema test assertions (Effect's ``TestSchema.Asserts``)::

    asserts = testing.SchemaAsserts(S.String)
    asserts.decoding().succeed("a")
    asserts.decoding().fail(1, "Expected string")
    asserts.encoding(report_input=True).fail(1, "Expected string, got 1")

``succeed(input)`` expects the input back; ``succeed(input, expected)`` a
given value. ``fail(input, message)`` expects a schema failure whose issue
prints as ``message``. A defect fails the assertion with the whole cause.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, Never, TypeVar, Unpack

from pyfect._core import Effect
from pyfect.context import TagLike
from pyfect.effect import provide_service
from pyfect.exit import Exit, Failure, Success
from pyfect.result import Ok
from pyfect.run import run_sync_exit
from pyfect.schema import (
    Codec,
    ParseOptions,
    SchemaError,
    decode_unknown_effect,
    encode_unknown_effect,
)
from pyfect.testing._assertions import describe_exit

_SAME = object()
R_co = TypeVar("R_co", covariant=True)
RD_co = TypeVar("RD_co", covariant=True)
RE_co = TypeVar("RE_co", covariant=True)


@dataclass(frozen=True, slots=True)
class SchemaCheck(Generic[R_co]):
    """Assertions on one direction of a schema: make, decode or encode,
    needing the services ``R``. Assertions run once none are left:
    ``provide(tag, service)`` gives a direction its one service."""

    parse: Callable[[object], Effect[object, SchemaError, R_co]]

    def run(self: SchemaCheck[Never], input: object) -> Exit[object, SchemaError]:
        return run_sync_exit(self.parse(input))

    def provide[S, T](self: SchemaCheck[T], tag: TagLike[S, T], service: S) -> SchemaCheck[Never]:
        parse = self.parse
        return SchemaCheck(lambda input: parse(input).pipe(provide_service(tag, service)))

    def succeed(self: SchemaCheck[Never], input: object, expected: object = _SAME) -> None:
        want = input if expected is _SAME else expected
        ex = self.run(input)
        if not (isinstance(ex, Success) and ex.value == want):
            raise AssertionError(f"expected Success({want!r}), got {describe_exit(ex)}")

    def fail(self: SchemaCheck[Never], input: object, message: str) -> None:
        ex = self.run(input)
        if isinstance(ex, Failure) and len(ex.cause.reasons) == 1:
            match ex.cause.find_error():
                case Ok(error) if error.message == message:
                    return
                case _:
                    pass
        raise AssertionError(f"expected a SchemaError {message!r}, got {describe_exit(ex)}")


@dataclass(frozen=True, slots=True)
class SchemaAsserts(Generic[RD_co, RE_co]):
    """Assertions for one schema; a schema needing services to decode
    (``RD``) or encode (``RE``) gets them from ``provide`` on each direction."""

    schema: Codec[object, object, RD_co, RE_co]

    def make(self, **options: Unpack[ParseOptions]) -> SchemaCheck[RD_co]:
        """Construction: the decoded side, with constructor defaults."""
        schema = self.schema.__codec__()

        def parse(input: object) -> Effect[object, SchemaError, RD_co]:
            return schema.make_effect(input, **options).map_error(SchemaError)

        return SchemaCheck(parse)

    def decoding(self, **options: Unpack[ParseOptions]) -> SchemaCheck[RD_co]:
        return SchemaCheck(decode_unknown_effect(self.schema, **options))

    def encoding(self, **options: Unpack[ParseOptions]) -> SchemaCheck[RE_co]:
        return SchemaCheck(encode_unknown_effect(self.schema, **options))
