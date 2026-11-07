"""Ports of Effect's ``ErrorInstance`` and ``Defect`` titles from
``Schema.test.ts``, ``toCodec.test.ts`` and ``schema/toJsonSchemaDocument.test.ts``.
Each test's docstring is the Effect test title, prefixed by its
``describe`` blocks. ``TestSchema.Asserts`` is ``testing.SchemaAsserts``.

As in Effect (``docs/PARITY.md`` §5, question 11), an error's JSON form decodes to an
exception with that ``name``, here always an ``S.ErrorInstance``, and any other defect to the
decoded value. Encoding writes a Python exception with its class name, ``str(e)`` and its
``__cause__``. So Effect's ``new Error("a")`` reads ``ErrorInstance("a")`` where it is decoded,
and ``ValueError("a")`` where it is encoded; an ``Error`` whose ``cause`` is not an ``Error``
(``"b"``) is an ``ErrorInstance`` with ``cause=Some("b")`` (a Python ``__cause__`` is always an
exception).

Omitted:
- "Defect" / "Error" ``verifyGeneration`` halves: drawn values are checked
  in ``test_arbitrary.py``'s catalog.
- The null-prototype object of "Defect" (Python mappings have no prototype).
- "toCodecStringTree / Error" is ported here; the other derivations' titles naming
  ``ErrorInstance`` are in their own files.
"""

from dataclasses import dataclass
from typing import Any, Never, cast

from pyfect import cause, exit
from pyfect import schema as S
from pyfect.errors import NoSuchElementException, TaggedError
from pyfect.option import Some
from pyfect.result import Err
from pyfect.testing import SchemaAsserts


def _raised(error: BaseException) -> BaseException:
    """``error`` once raised (with a traceback, as Effect's ``stack``)."""
    try:
        raise error
    except BaseException as caught:
        return caught


def _caused(error: BaseException, by: BaseException) -> BaseException:
    error.__cause__ = by
    return error


def _json(schema: S.Codec[Any, Any, Never, Never]) -> SchemaAsserts[Never, Never]:
    return SchemaAsserts(S.to_codec_json(schema))


# -------------------------------------------------------- Schema.test.ts


def test_defect():
    """Defect"""
    asserts = SchemaAsserts(S.Defect())

    decoding = asserts.decoding()
    # Error: message only
    decoding.succeed({"message": "a"}, S.ErrorInstance("a"))
    # Error: message and name
    decoding.succeed({"message": "a", "name": "b"}, S.ErrorInstance("a", name="b"))
    # Error: message, name, and stack
    decoding.succeed(
        {"message": "a", "name": "b", "stack": "c"},
        S.ErrorInstance("a", name="b", stack="c"),
    )
    # anything else
    decoding.succeed("a", "a")
    decoding.succeed({"a": 1}, {"a": 1})

    encoding = asserts.encoding()
    # Error
    encoding.succeed(ValueError("a"), {"name": "ValueError", "message": "a"})
    # anything else
    encoding.succeed("a", "a")
    encoding.succeed({"a": 1}, {"a": 1})
    encoding.succeed(S.ErrorInstance("a"), {"name": "Error", "message": "a"})


def test_errorinstance_and_defect_memoize_equivalent_options():
    """ErrorInstance and Defect memoize equivalent options"""
    for schema in (S.ErrorInstance.schema, S.Defect):
        assert schema() is schema(include_stack=False)
        assert schema() is schema(exclude_cause=False)
        assert schema() is schema(include_stack=False, exclude_cause=False)
        assert schema(include_stack=True) is schema(include_stack=True, exclude_cause=False)
        assert schema(exclude_cause=True) is schema(include_stack=False, exclude_cause=True)
        assert schema(include_stack=True, exclude_cause=True) is schema(
            include_stack=True, exclude_cause=True
        )
        assert schema() is not schema(include_stack=True)
        assert schema() is not schema(exclude_cause=True)
        assert schema(include_stack=True) is not schema(include_stack=True, exclude_cause=True)
        assert schema(exclude_cause=True) is not schema(include_stack=True, exclude_cause=True)
    assert S.ErrorInstance.__codec__() is S.ErrorInstance.schema()


def test_cause_strict_encoding_preserves_the_default_wire_format_for_every_reason_variant():
    """Cause / strict encoding preserves the default wire format for every reason variant"""
    schema = S.from_json_string(S.to_codec_json(S.Cause(S.String, S.Defect())))
    value = cause.Cause(
        (
            cause.Fail("boom"),
            cause.Die(42),
            cause.Interrupt(7),
            cause.Interrupt(),
        )
    )
    wire = (
        '[{"_tag":"Fail","error":"boom"},{"_tag":"Die","defect":42},'
        '{"_tag":"Interrupt","fiberId":7},{"_tag":"Interrupt","fiberId":null}]'
    )
    assert S.encode_sync(schema)(value) == wire
    assert S.encode_sync(schema, on_excess_property="error")(value) == wire
    assert S.decode_sync(schema)(wire) == value
    assert S.decode_sync(schema, on_excess_property="error")(wire) == value


def test_error():
    """Error"""
    asserts = SchemaAsserts(S.ErrorInstance)
    error = ValueError("a")
    custom = S.ErrorInstance("b", name="CustomError", stack="stack")

    decoding = asserts.decoding()
    decoding.succeed(error)
    decoding.succeed(custom)
    decoding.fail({"message": "a"}, "Expected Error")
    decoding.fail("a", "Expected Error")

    encoding = asserts.encoding()
    encoding.succeed(error)
    encoding.succeed(custom)
    encoding.fail({"message": "a"}, "Expected Error")
    encoding.fail("a", "Expected Error")


def test_exit_exit_finitefromstring_string_defect():
    """Exit / Exit(FiniteFromString, String, Defect)"""
    asserts = SchemaAsserts(S.Exit(S.FiniteFromString, S.String, S.Defect()))
    # The encoded side of a Die holds the defect's JSON form.
    encoded_die = exit.die(cast("BaseException", {"name": "boom", "message": "boom message"}))
    asserts.decoding().succeed(encoded_die, exit.die(S.ErrorInstance("boom message", name="boom")))


# ------------------------------------------------------- toCodec.test.ts


def test_tocodecjson_schemas_without_encoding_error():
    """toCodecJson / schemas without encoding / Error"""
    asserts = _json(S.ErrorInstance)

    encoding = asserts.encoding()
    encoding.succeed(ValueError("a"), {"name": "ValueError", "message": "a"})
    encoding.succeed(
        _caused(ValueError("a"), ValueError("b")),
        {"name": "ValueError", "message": "a", "cause": {"name": "ValueError", "message": "b"}},
    )
    encoding.succeed(
        S.ErrorInstance("a", cause=Some("b")), {"name": "Error", "message": "a", "cause": "b"}
    )
    self_cause = ValueError("a")
    self_cause.__cause__ = self_cause
    encoding.succeed(self_cause, {"name": "ValueError", "message": "a", "cause": "[Circular]"})

    decoding = asserts.decoding()
    # Error: message only
    decoding.succeed({"message": "a"}, S.ErrorInstance("a"))
    # Error: message and name
    decoding.succeed({"name": "b", "message": "a"}, S.ErrorInstance("a", name="b"))
    # Error: message, name, and stack
    decoding.succeed(
        {"name": "b", "message": "a", "stack": "c"}, S.ErrorInstance("a", name="b", stack="c")
    )
    # Error: message and cause
    decoding.succeed(
        {"message": "a", "cause": {"message": "b"}},
        S.ErrorInstance("a", cause=Some(S.ErrorInstance("b"))),
    )
    # Error: explicit null cause
    decoding.succeed({"message": "a", "cause": None}, S.ErrorInstance("a", cause=Some(None)))


def test_tocodecjson_schemas_without_encoding_error_with_stack():
    """toCodecJson / schemas without encoding / Error with stack"""
    asserts = _json(S.ErrorInstance.schema(include_stack=True))
    error = S.ErrorInstance("a", stack="stack")
    custom = S.ErrorInstance("b", name="CustomError", stack="custom stack")

    encoding = asserts.encoding()
    encoding.succeed(error, {"name": "Error", "message": "a", "stack": "stack"})
    encoding.succeed(custom, {"name": "CustomError", "message": "b", "stack": "custom stack"})
    raised = _raised(ValueError("a"))
    stack = S.encode_sync(S.to_codec_json(S.ErrorInstance.schema(include_stack=True)))(raised)
    assert "Traceback" in cast("dict[str, str]", stack)["stack"]

    decoding = asserts.decoding()
    decoding.succeed({"message": "a", "stack": "stack"}, error)
    decoding.succeed({"name": "CustomError", "message": "b", "stack": "custom stack"}, custom)


def test_tocodecjson_schemas_without_encoding_error_with_excluded_cause():
    """toCodecJson / schemas without encoding / Error with excluded cause"""
    asserts = _json(S.ErrorInstance.schema(exclude_cause=True))
    asserts.encoding().succeed(
        _caused(ValueError("a"), ValueError("b")), {"name": "ValueError", "message": "a"}
    )


def test_tocodecjson_schemas_with_encoding_defect():
    """toCodecJson / schemas with encoding / Defect"""
    asserts = _json(S.Defect())

    encoding = asserts.encoding()
    encoding.succeed(ValueError("a"), {"name": "ValueError", "message": "a"})
    encoding.succeed(
        _caused(ValueError("a"), ValueError("b")),
        {"name": "ValueError", "message": "a", "cause": {"name": "ValueError", "message": "b"}},
    )
    encoding.succeed(
        S.ErrorInstance("a", cause=Some("b")),
        {"name": "Error", "message": "a", "cause": "b"},
    )
    encoding.succeed(NoSuchElementException(), {"name": "NoSuchElementException", "message": ""})
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    encoding.succeed(cyclic, {})
    encoding.succeed("a", "a")
    encoding.succeed({"a": 1}, {"a": 1})

    decoding = asserts.decoding()
    decoding.succeed(
        {"message": "a", "cause": {"message": "b"}},
        S.ErrorInstance("a", cause=Some(S.ErrorInstance("b"))),
    )
    decoding.succeed({"message": "a", "cause": None}, S.ErrorInstance("a", cause=Some(None)))


def test_tocodecjson_schemas_with_encoding_defect_with_excluded_cause():
    """toCodecJson / schemas with encoding / Defect with excluded cause"""
    _json(S.Defect(exclude_cause=True)).encoding().succeed(
        _caused(ValueError("a"), ValueError("b")), {"name": "ValueError", "message": "a"}
    )


def test_tocodecstringtree_schemas_without_encoding_error():
    """toCodecStringTree / schemas without encoding / Error"""
    asserts = SchemaAsserts(S.to_codec_string_tree(S.ErrorInstance))

    asserts.encoding().succeed(ValueError("a"), {"name": "ValueError", "message": "a"})

    decoding = asserts.decoding()
    decoding.succeed({"message": "a"}, S.ErrorInstance("a"))
    decoding.succeed({"name": "b", "message": "a"}, S.ErrorInstance("a", name="b"))
    decoding.succeed(
        {"name": "b", "message": "a", "stack": "c"}, S.ErrorInstance("a", name="b", stack="c")
    )


# ------------------------------------------ toJsonSchemaDocument.test.ts


def test_declaration_error():
    """Declaration / Error"""
    document = S.to_json_schema_document(S.ErrorInstance, on_excess_property="error")
    assert document.schema == {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "message": {"type": "string"},
            "stack": {"type": "string"},
            "cause": {},
        },
        "required": ["message"],
        "additionalProperties": False,
    }


class _NamedError(S.Error, identifier="SErrId"):
    message: str


class _NamedTagged(S.TaggedError, identifier="STaggedId", tag="STag"):
    a: float


class _TagNamed(S.TaggedError, tag="STag2"):
    a: float


@dataclass
class _Plain(TaggedError):
    a: int


@dataclass
class _Said(TaggedError):
    message: str


def test_defect_json_writes_the_name_an_error_carries():
    """Not an Effect title: ``Defect`` writes ``error.name``, a schema error class's identifier
    or tag, as Effect's encoder does (each value printed by Effect under Node)."""
    encode = S.encode_sync(S.Defect())
    assert encode(_NamedError(message="m")) == {"name": "SErrId", "message": "m"}
    assert encode(_NamedTagged(a=1)) == {"name": "STaggedId", "message": ""}
    assert encode(_TagNamed(a=1)) == {"name": "STag2", "message": ""}
    match S.decode_unknown_result(S.Number)("a"):
        case Err(error=error):
            assert encode(error) == {"name": "SchemaError", "message": "Expected number"}
        case other:
            raise AssertionError(other)
    assert encode(TypeError("t")) == {"name": "TypeError", "message": "t"}
    # Effect's ``Data.TaggedError("Plain")``: the tag, which is the class here, and no message.
    assert encode(_Plain(a=1)) == {"name": "_Plain", "message": ""}
    # ``message``, not ``str()`` (which adds the cause).
    caused = _caused(_Said(message="said"), ValueError("why"))
    assert encode(caused) == {
        "name": "_Said",
        "message": "said",
        "cause": {"name": "ValueError", "message": "why"},
    }
