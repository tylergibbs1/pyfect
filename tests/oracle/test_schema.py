"""Ports of Effect's ``Schema.test.ts``: the primitive schemas, ``SchemaError``
and the schema guards. Each test's docstring is the Effect test title,
prefixed by its ``describe`` block where Effect nests it. ``TestSchema.Asserts``
is ``testing.SchemaAsserts``; Effect's ``Exit`` of a decoder is the ``_exit``
adapter's.

Ported in part: "keeps synchronous decode and encode effects eager" (a
pyfect ``Exit`` is not an ``Effect``, so the ``_effect`` adapters wrap the
parse's exit with ``from_exit``; the results are checked), "isSchema" (the
``Opaque`` half waits for ``Opaque``; a schema class is a schema), "toString" (Python's
``str(error)`` is the message; Effect prints ``Fail(SchemaError(<message>))``),
"SchemaError / extends Error and exposes the issue" (``isSchemaError`` is
``isinstance``; there is no ``name`` property).

Omitted:
- "Undefined", "Void", "Symbol", "UniqueSymbol", "ObjectKeyword",
  "StringForLiteralAutocomplete", "StringForLiteralAutocomplete | Literals":
  Python has one ``None``, no symbols, every value is an object, and
  autocompletion hints are TypeScript-only.
- "SchemaError / serializes as a tagged formatted message", "SchemaError /
  inspects as a tagged formatted message", "SchemaError / does not capture
  stack frames": ``toJSON``, Node's ``inspect`` and ``Error.stackTraceLimit``
  have no Python counterpart.
- Literal(s), Enum, Union of primitives, checks, Int, Natural, Trimmed,
  Finite, fromBrand and resolveAnnotations: ported in test_schema_checks.py.
- Struct, Record and class titles are in test_schema_struct.py and
  test_schema_class.py; tuples, arrays and data types in
  test_schema_composites.py; transformations, codecs and the decoding /
  encoding adapter titles ("decodeUnknownOption", "makeOption", ...) in
  test_schema_transform.py; the parser titles ("is", "asserts", the
  laziness and retry titles) in test_schema_parser.py.
"""

from dataclasses import dataclass, field

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import Fail
from pyfect.exit import Failure
from pyfect.result import Err
from pyfect.schema import ast
from pyfect.schema.issue import InvalidType


@dataclass(frozen=True, slots=True, eq=False)
class _Counted(ast.String):
    """A string node counting its parses."""

    parses: list[object] = field(default_factory=list[object])

    def parse(self, input: object, options: S.ParseOptions) -> ast.ParseResult:
        self.parses.append(input)
        return super(_Counted, self).parse(input, options)


@testing.effect
def test_keeps_synchronous_decode_and_encode_effects_eager():
    """keeps synchronous decode and encode effects eager"""
    # Effect checks that the adapter hands back the parse's ``Exit`` (an
    # ``Effect`` there): the parse has run before the effect does.
    node = _Counted()
    counted = S.Bottom[str](node)
    S.decode_unknown_effect(counted)("a")
    S.encode_unknown_effect(counted)(None)
    assert node.parses == ["a", None]

    assert (yield from S.decode_unknown_effect(S.String)("a")) == "a"
    assert (yield from S.encode_unknown_effect(S.String)("a")) == "a"

    for effect in (
        S.decode_unknown_effect(S.String)(None),
        S.encode_unknown_effect(S.String)(None),
    ):
        error = yield from effect.flip()
        assert isinstance(error, S.SchemaError)


def test_is_schema():
    """isSchema"""
    assert S.is_schema(S.String)

    class A(S.Class):
        a: str

    assert S.is_schema(A)
    assert not S.is_schema({})


def test_to_string():
    """toString"""
    result = S.decode_unknown_exit(S.String)(None)
    assert isinstance(result, Failure)
    reason = result.cause.reasons[0]
    assert isinstance(reason, Fail)
    assert str(reason.error) == "Expected string"


def test_schema_error_extends_error_and_exposes_the_issue():
    """SchemaError / extends Error and exposes the issue"""
    result = S.decode_unknown_result(S.String)(None)
    assert isinstance(result, Err)
    issue = result.error.issue
    error = S.SchemaError(issue)

    assert isinstance(error, Exception)
    assert isinstance(error, fx.TaggedError)
    assert error.issue is issue
    assert error.message == "Expected string"
    assert str(error) == "Expected string"
    assert isinstance(issue, InvalidType)


def test_never():
    """Never"""
    asserts = testing.SchemaAsserts(S.Never)

    asserts.make().fail(None, "Expected never")
    asserts.decoding().fail("a", "Expected never")
    asserts.encoding().fail("a", "Expected never")


def test_any():
    """Any"""
    asserts = testing.SchemaAsserts(S.Any)

    asserts.make().succeed("a")
    asserts.decoding().succeed("a")


def test_unknown():
    """Unknown"""
    asserts = testing.SchemaAsserts(S.Unknown)

    asserts.make().succeed("a")
    asserts.decoding().succeed("a")


def test_null():
    """Null"""
    asserts = testing.SchemaAsserts(S.Null)

    asserts.make().succeed(None)
    asserts.make().fail("a", "Expected null")


def test_string():
    """String"""
    asserts = testing.SchemaAsserts(S.String)

    asserts.make().succeed("a")
    asserts.make().fail(None, "Expected string")

    asserts.decoding().succeed("a")
    asserts.decoding().fail(1, "Expected string")

    asserts.encoding().succeed("a")
    asserts.encoding().fail(1, "Expected string")


def test_number():
    """Number"""
    asserts = testing.SchemaAsserts(S.Number)

    asserts.make().succeed(1)
    asserts.make().fail(None, "Expected number")

    asserts.decoding().succeed(1)
    asserts.decoding().fail("a", "Expected number")

    asserts.encoding().succeed(1)
    asserts.encoding().fail("a", "Expected number")


def test_boolean():
    """Boolean"""
    asserts = testing.SchemaAsserts(S.Boolean)

    asserts.make().succeed(True)
    asserts.make().succeed(False)
    asserts.make().fail(None, "Expected boolean")

    asserts.decoding().succeed(True)
    asserts.decoding().succeed(False)
    asserts.decoding().fail("a", "Expected boolean")

    asserts.encoding().succeed(True)
    asserts.encoding().succeed(False)
    asserts.encoding().fail("a", "Expected boolean")


def test_big_int():
    """BigInt"""
    asserts = testing.SchemaAsserts(S.BigInt)

    asserts.make().succeed(1)
    asserts.make().fail(None, "Expected bigint")

    asserts.decoding().succeed(1)
    asserts.decoding().fail("1", "Expected bigint")

    asserts.encoding().succeed(1)
    asserts.encoding().fail("1", "Expected bigint")
