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
from typing import Never, Unpack

from pyfect.exit import Exit, Failure, Success
from pyfect.result import Ok
from pyfect.run import run_sync_exit
from pyfect.schema import (
    Codec,
    ParseOptions,
    SchemaError,
    decode_unknown_exit,
    encode_unknown_exit,
)
from pyfect.testing._assertions import describe_exit

_SAME = object()


@dataclass(frozen=True, slots=True)
class SchemaCheck:
    """Assertions on one direction of a schema: make, decode or encode."""

    run: Callable[[object], Exit[object, SchemaError]]

    def succeed(self, input: object, expected: object = _SAME) -> None:
        want = input if expected is _SAME else expected
        ex = self.run(input)
        if not (isinstance(ex, Success) and ex.value == want):
            raise AssertionError(f"expected Success({want!r}), got {describe_exit(ex)}")

    def fail(self, input: object, message: str) -> None:
        ex = self.run(input)
        if isinstance(ex, Failure) and len(ex.cause.reasons) == 1:
            match ex.cause.find_error():
                case Ok(error) if error.message == message:
                    return
                case _:
                    pass
        raise AssertionError(f"expected a SchemaError {message!r}, got {describe_exit(ex)}")


@dataclass(frozen=True, slots=True)
class SchemaAsserts:
    """Assertions for one schema that needs no services."""

    schema: Codec[object, object, Never, Never]

    def make(self, **options: Unpack[ParseOptions]) -> SchemaCheck:
        """Construction: the decoded side, with constructor defaults."""
        schema = self.schema.__codec__()

        def run(input: object) -> Exit[object, SchemaError]:
            return run_sync_exit(schema.make_effect(input, **options)).map_error(SchemaError)

        return SchemaCheck(run)

    def decoding(self, **options: Unpack[ParseOptions]) -> SchemaCheck:
        return SchemaCheck(decode_unknown_exit(self.schema, **options))

    def encoding(self, **options: Unpack[ParseOptions]) -> SchemaCheck:
        return SchemaCheck(encode_unknown_exit(self.schema, **options))
