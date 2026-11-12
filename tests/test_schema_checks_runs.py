"""How a schema's checks run, at the ``pyfect.schema`` boundary: the input
an issue keeps under ``report_input``, groups and aborts, ``disable_checks``,
annotations on combined checks, the checks of the encoded side, and checks
after an effectful part. Each runs with the interpreter and with a compiler
registry active (every node then parses through its registry entry)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any, Literal, TypedDict, TypeIs

import pytest
from oracle._schema_compiler import fresh_registry

import pyfect as fx
from pyfect import schema as S
from pyfect.exit import Failure, Success
from pyfect.option import Some
from pyfect.result import Err
from pyfect.schema import compiler
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.compiler import CompiledDecoder
from pyfect.schema.issue import Composite, Filter, InvalidValue, Issue, Pointer
from pyfect.testing import SchemaAsserts

__all__ = ["fresh_registry"]


def _identity(input: object, options: object) -> Success[object]:
    return Success(input)


@pytest.fixture(params=["interpreter", "registry"], autouse=True)
def mode(request: pytest.FixtureRequest, fresh_registry: None) -> Iterator[str]:
    if request.param == "registry":
        # A decoder for a node no test uses: the registry is active, and every
        # other node parses through its interpreted entry (``AST.interpret``).
        compiler.set(
            S.String.annotate(title="activator").ast, CompiledDecoder(decode_effect=_identity)
        )
    yield request.param


def _decoding_issue(schema: S.Decoder[object], input: object) -> Issue:
    result = S.decode_unknown_result(schema)(input, report_input=True)
    assert isinstance(result, Err)
    return result.error.issue


def _only_filter(issue: Issue) -> Filter:
    assert isinstance(issue, Composite)
    (failure,) = issue.issues
    assert isinstance(failure, Filter)
    return failure


# ---------------------------------------------------------- report_input


def test_a_failing_check_keeps_the_value_on_every_issue():
    issue = _decoding_issue(S.String.check(S.make_filter(lambda _: False)), "a")
    assert isinstance(issue, Composite)
    assert issue.input == Some("a")
    failure = _only_filter(issue)
    assert failure.input == Some("a")
    assert failure.issue == InvalidValue(None, Some("a"))


def test_a_message_from_a_filter_keeps_the_value():
    failure = _only_filter(_decoding_issue(S.String.check(S.make_filter(lambda _: "bad")), "a"))
    assert failure.issue == InvalidValue({"message": "bad"}, Some("a"))


def test_messages_from_a_filter_keep_the_value_each_and_together():
    schema = S.String.check(S.make_filter(lambda _: ["x", "y"]))
    inner = _only_filter(_decoding_issue(schema, "a")).issue
    assert isinstance(inner, Composite)
    assert inner.input == Some("a")
    assert inner.issues == (
        InvalidValue({"message": "x"}, Some("a")),
        InvalidValue({"message": "y"}, Some("a")),
    )


def test_a_message_at_a_path_keeps_the_value():
    schema = S.String.check(S.make_filter(lambda _: (("k",), "bad")))
    inner = _only_filter(_decoding_issue(schema, "a")).issue
    assert inner == Pointer(("k",), InvalidValue({"message": "bad"}, Some("a")))


def _is_b(value: str) -> TypeIs[Literal["b"]]:
    return value == "b"


def test_a_refinement_reports_the_rejected_value():
    schema = S.String.pipe(S.refine(_is_b))
    SchemaAsserts(schema).decoding(report_input=True).fail("a", 'Expected <filter>, got "a"')
    SchemaAsserts(schema).decoding().fail("a", "Expected <filter>")
    failure = _only_filter(_decoding_issue(schema, "a"))
    assert failure.issue == InvalidValue(None, Some("a"))


class _A(TypedDict):
    a: str


def test_a_check_of_the_encoded_side_runs_on_the_value_being_encoded():
    schema = S.Struct(_A).check(S.make_filter(lambda v: v["a"] != "bad"))
    encode = S.encode_unknown_result(schema)
    assert encode({"a": "ok"}) == fx.result.Ok({"a": "ok"})
    result = encode({"a": "bad"}, report_input=True)
    assert isinstance(result, Err)
    issue = result.error.issue
    assert isinstance(issue, Composite)
    assert issue.input == Some({"a": "bad"})
    assert _only_filter(issue).input == Some({"a": "bad"})


# ------------------------------------------------------ groups and aborts


def _rejecting(name: str) -> S.Filter[str]:
    return S.make_filter(lambda _: False, expected=name)


def _accepting() -> S.Filter[str]:
    return S.make_filter(lambda _: True)


def test_a_group_that_stops_the_checks_stops_those_after_it():
    schema = S.String.check(S.make_filter_group(_rejecting("first")), _rejecting("second"))
    SchemaAsserts(schema).decoding().fail("a", "Expected first")


def test_a_nested_group_that_stops_the_checks_stops_those_after_its_parent():
    schema = S.String.check(
        S.make_filter_group(S.make_filter_group(_rejecting("first")), _accepting()),
        _rejecting("second"),
    )
    SchemaAsserts(schema).decoding().fail("a", "Expected first")


def test_the_checks_after_a_passing_group_run():
    schema = S.String.check(S.make_filter_group(_accepting()), _rejecting("after"))
    SchemaAsserts(schema).decoding().fail("a", "Expected after")
    nested = S.String.check(
        S.make_filter_group(S.make_filter_group(_accepting()), _rejecting("inner")),
        _rejecting("outer"),
    )
    SchemaAsserts(nested).decoding(errors="all").fail("a", "Expected inner\nExpected outer")


def test_a_filter_does_not_abort_unless_asked_to():
    schema = S.String.check(_rejecting("first"), _rejecting("second"))
    SchemaAsserts(schema).decoding(errors="all").fail("a", "Expected first\nExpected second")


# -------------------------------------------- annotations of combined checks


def test_and_annotates_the_group_it_makes():
    paired = _accepting().and_(_rejecting("member"), identifier="Paired")
    SchemaAsserts(S.String.check(paired)).decoding().fail(1, "Expected Paired")
    grouped = S.make_filter_group(_accepting()).and_(_rejecting("member"), identifier="Grouped")
    asserts = SchemaAsserts(S.String.check(grouped))
    asserts.decoding().fail(1, "Expected Grouped")
    asserts.decoding().fail("a", "Expected member")


def test_annotate_on_a_group_describes_it():
    group = S.make_filter_group(_rejecting("member")).annotate(identifier="Named")
    SchemaAsserts(S.String.check(group)).decoding().fail(1, "Expected Named")


# --------------------------------------------------------- disable_checks


class _Named(S.Class):
    name: str


def test_disable_checks_skips_the_checks_of_a_literal_and_a_class():
    literal = S.Literal("a").check(_rejecting("never"))
    assert S.decode_unknown_sync(literal)("a", disable_checks=True) == "a"
    SchemaAsserts(literal).decoding().fail("a", "Expected never")
    checked = _Named.check(S.make_filter(lambda _: False, expected="never"))
    assert S.decode_unknown_sync(checked)({"name": "x"}, disable_checks=True) == _Named(name="x")
    SchemaAsserts(checked).decoding().fail({"name": "x"}, "Expected never")


def test_disable_checks_skips_the_checks_of_a_string():
    schema = S.String.check(_rejecting("never"))
    assert S.decode_unknown_sync(schema)("a", disable_checks=True) == "a"


# -------------------------------------------- checks after an effectful part


def _echo(value: str, _: object) -> fx.Effect[str]:
    return fx.sync(lambda: value)


_EFFECTFUL = S.String.pipe(
    S.decode(T.Transformation(G.transform_effect(_echo), G.transform_effect(_echo)))
)


class _Effectful(S.Class):
    name: str = S.field(_EFFECTFUL)


def _not_bad(value: Any) -> bool:
    return value["a"] != "bad"


def test_a_check_after_an_effectful_part_gets_the_parsed_value():
    schema = S.Struct(_A, a=_EFFECTFUL).check(S.make_filter(_not_bad))
    decode = S.decode_unknown_effect(schema)
    assert fx.run_sync_exit(decode({"a": "ok"})) == Success({"a": "ok"})
    assert isinstance(fx.run_sync_exit(decode({"a": "bad"})), Failure)
    encode = S.encode_unknown_effect(schema)
    assert fx.run_sync_exit(encode({"a": "ok"})) == Success({"a": "ok"})
    assert isinstance(fx.run_sync_exit(encode({"a": "bad"})), Failure)


def test_a_class_check_after_an_effectful_field_gets_the_instance():
    schema = _Effectful.check(S.make_filter(lambda e: e.name != "bad"))
    decode = S.decode_unknown_effect(schema)
    assert fx.run_sync_exit(decode({"name": "ok"})) == Success(_Effectful(name="ok"))
    assert isinstance(fx.run_sync_exit(decode({"name": "bad"})), Failure)


# ----------------------------------------------------------- has_check


@pytest.mark.parametrize(
    ("checks", "message"),
    [
        # Not kept finite: "NaN" decodes, then the check rejects it.
        ((S.is_greater_than(0),), "Expected a value greater than 0"),
        # Kept finite by a check after a group: "NaN" is not a number.
        ((S.make_filter_group(S.is_greater_than(-10)), S.is_int()), "Expected number"),
    ],
)
def test_the_json_codec_of_a_number_reads_its_finiteness_from_its_checks(
    checks: tuple[S.Check[float], ...], message: str
):
    codec = S.to_codec_json(S.Number.check(*checks))
    SchemaAsserts(codec).decoding().fail("NaN", message)
    assert S.encode_unknown_exit(S.to_codec_json(S.Number))(math.inf) == Success("Infinity")


def test_a_literal_key_parses_through_the_registry_when_it_is_active():
    schema = S.Struct(_A, a=S.Literal("x"))
    assert S.decode_unknown_sync(schema)({"a": "x"}) == {"a": "x"}
    SchemaAsserts(schema).decoding().fail({"a": "y"}, 'Expected "x"\n  at ["a"]')


def test_a_check_of_the_encoded_side_reached_through_a_transformation_gets_its_input():
    checked = S.Struct(_A, a=_EFFECTFUL).check(S.make_filter(_not_bad))
    schema = S.Unknown.pipe(S.decode_to(S.flip(checked), T.passthrough_supertype()))
    decode = S.decode_unknown_effect(schema)
    assert fx.run_sync_exit(decode({"a": "ok"})) == Success({"a": "ok"})
    assert isinstance(fx.run_sync_exit(decode({"a": "bad"})), Failure)
