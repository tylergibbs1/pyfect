"""The schema parser at its boundary: options, messages, adapters and Python's
own values. Expected messages were printed by Effect's ``Schema`` under Node."""

import re
from collections.abc import Callable
from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import Cause, Die, Fail
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Some
from pyfect.result import Err, Ok
from pyfect.schema import ast
from pyfect.schema.issue import (
    Composite,
    Encoding,
    Forbidden,
    InvalidType,
    InvalidValue,
    Issue,
    MissingKey,
    Pointer,
    UnexpectedKey,
    format_issue,
)


def message(exit: Exit[object, S.SchemaError]) -> str:
    assert isinstance(exit, Failure)
    found = exit.cause.find_error()
    assert isinstance(found, Ok)
    return found.value.message


@pytest.mark.parametrize(
    ("schema", "input", "expected"),
    [
        (S.String, 1, "Expected string, got 1"),
        (S.String, None, "Expected string, got null"),
        (S.Never, None, "Expected never, got null"),
        (S.BigInt, 1.5, "Expected bigint, got 1.5"),
        (S.Boolean, [1, "a"], 'Expected boolean, got [1,"a"]'),
        (S.Boolean, {"a": 1}, 'Expected boolean, got {"a":1}'),
        (S.Number, "a", 'Expected number, got "a"'),
    ],
)
def test_report_input_prints_the_rejected_value(
    schema: S.Decoder[object], input: object, expected: str
):
    decode = S.decode_unknown_exit(schema, report_input=True)
    assert message(decode(input)) == expected


def test_issues_keep_the_input_only_under_report_input():
    plain = S.decode_unknown_result(S.String)(1)
    reported = S.decode_unknown_result(S.String)(1, report_input=True)
    assert plain == Err(S.SchemaError(InvalidType(ast.string)))
    assert reported == Err(S.SchemaError(InvalidType(ast.string, Some(1))))


def test_call_options_override_the_options_given_when_made():
    decode = S.decode_unknown_exit(S.String, report_input=True)
    assert message(decode(1, errors="all")) == "Expected string, got 1"
    assert message(decode(1, report_input=False)) == "Expected string"


def test_encoding_reports_the_type_side():
    encode = S.encode_unknown_exit(S.Number, report_input=True)
    assert message(encode("a")) == 'Expected number, got "a"'


def test_annotations_name_the_schema_or_replace_its_message():
    def decoded(schema: S.Decoder[object], *, report_input: bool = False) -> str:
        return message(S.decode_unknown_exit(schema)(1, report_input=report_input))

    assert decoded(S.String.annotate(message="my message")) == "my message"
    assert decoded(S.String.annotate(identifier="Name")) == "Expected Name"
    assert decoded(S.String.annotate(identifier="Name"), report_input=True) == (
        "Expected Name, got 1"
    )
    # ``expected`` names an InvalidValue, not the schema; titles only document.
    assert decoded(S.String.annotate(expected="a name")) == "Expected string"
    assert decoded(S.String.annotate(title="T", description="D")) == "Expected string"


def test_annotate_returns_a_new_schema_over_a_new_node():
    named = S.String.annotate(identifier="Name")
    assert named.ast is not S.String.ast
    assert S.String.ast.annotations is None
    assert named.annotate(title="T").ast.annotations == {"identifier": "Name", "title": "T"}


@pytest.mark.parametrize(
    ("schema", "accepted", "rejected"),
    [
        (S.Number, [1, 1.5, float("nan"), float("inf"), 10**30], [True, "1", None]),
        (S.BigInt, [0, 10**30], [True, 1.0, "1"]),
        (S.Boolean, [True, False], [0, 1, "true"]),
        (S.Null, [None], [0, "", False]),
        (S.String, ["", "a"], [b"a", None]),
    ],
)
def test_python_values(schema: S.Top, accepted: list[object], rejected: list[object]):
    guard = S.is_(schema)
    assert [guard(v) for v in accepted] == [True] * len(accepted)
    assert [guard(v) for v in rejected] == [False] * len(rejected)


@pytest.mark.parametrize(
    ("issue", "expected"),
    [
        (InvalidValue(None, Some(1)), "Invalid data 1"),
        (InvalidValue({"expected": "positive"}, Some(1)), "Expected positive, got 1"),
        (InvalidValue({"expected": "positive"}), "Expected positive"),
        (InvalidValue({"message": "m", "expected": "positive"}), "m"),
        (UnexpectedKey(ast.string, Some(1)), "Unexpected key with value 1"),
        (UnexpectedKey(ast.annotate(ast.string, {"message_unexpected_key": "nope"})), "nope"),
        (MissingKey({"message_missing_key": "need it"}), "need it"),
        (Forbidden({"message": "no"}), "no"),
        (Forbidden(None, Some(1)), "Forbidden operation"),
        (
            Pointer(
                ("a", 0, "b"),
                Composite(ast.string, (MissingKey(), Pointer((1,), InvalidType(ast.number)))),
            ),
            'Missing key\n  at ["a"][0]["b"]\nExpected number\n  at ["a"][0]["b"][1]',
        ),
        (Encoding(ast.string, Pointer(("x",), Forbidden())), 'Forbidden operation\n  at ["x"]'),
        (Pointer((), Forbidden()), "Forbidden operation"),
        (InvalidType(ast.annotate(ast.string, {"message": "m"}), Some(1)), "m"),
        (Pointer(("é\n",), Forbidden()), 'Forbidden operation\n  at ["é\\n"]'),
    ],
)
def test_default_formatter(issue: Issue, expected: str):
    assert format_issue(issue) == expected


def test_make_checks_the_type_side():
    assert S.Number.make(1.5) == 1.5
    assert S.Number.make_option(1.5) == Some(1.5)
    assert S.Number.make_option("1") is None  # pyright: ignore[reportArgumentType]
    with pytest.raises(S.SchemaError, match=r"^Expected number$"):
        S.Number.make("1")  # pyright: ignore[reportArgumentType]


@testing.effect
def test_make_effect_fails_with_the_bare_issue():
    issue = yield from S.String.make_effect(1).flip()  # pyright: ignore[reportArgumentType]
    assert issue == InvalidType(ast.string)


def test_asserts_raises_schema_error():
    S.asserts(S.Number, 1)
    with pytest.raises(S.SchemaError, match=r"^Expected number$"):
        S.asserts(S.Number, "1")


def test_decode_typed_input():
    assert S.decode_sync(S.String)("a") == "a"
    assert S.decode_exit(S.String)("a") == Success("a")
    assert S.decode_option(S.String)("a") == Some("a")
    assert S.decode_result(S.String)("a") == Ok("a")
    assert S.encode_sync(S.Number)(1.5) == 1.5
    assert S.encode_exit(S.Number)(1.5) == Success(1.5)
    assert S.encode_option(S.Number)(1.5) == Some(1.5)
    assert S.encode_result(S.Number)(1.5) == Ok(1.5)


@testing.effect
def test_effect_adapters_fail_with_schema_error():
    assert (yield from S.decode_effect(S.String)("a")) == "a"
    assert (yield from S.encode_effect(S.String)("a")) == "a"
    error = yield from S.decode_unknown_effect(S.String)(1).flip()
    assert error.message == "Expected string"


# --------------------------------------------------- non-schema failures


@dataclass(frozen=True, slots=True, eq=False)
class Dying(ast.AST):
    """A node whose parse fails with ``cause``: a defect, or a schema issue
    beside a defect."""

    cause: Cause[Issue]
    tag = "Dying"

    def get_expected(self) -> str:
        return "dying"

    def _parse(self, input: object, options: S.ParseOptions) -> Exit[object, Issue]:
        return Failure(self.cause)


DEFECT = RuntimeError("defect")
CAUSES: dict[str, Cause[Issue]] = {
    "defect": Cause((Die(DEFECT),)),
    "issue and defect": Cause((Fail(InvalidValue({"message": "schema issue"})), Die(DEFECT))),
}


@pytest.mark.parametrize("cause", CAUSES.values(), ids=CAUSES.keys())
@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (S.decode_unknown_sync, "Sync adapter can only throw schema errors"),
        (S.encode_unknown_sync, "Sync adapter can only throw schema errors"),
        (S.decode_unknown_option, "Option adapter can only return none for schema issues"),
        (S.encode_unknown_option, "Option adapter can only return none for schema issues"),
        (S.decode_unknown_result, "Result adapter can only return schema issues"),
        (S.encode_unknown_result, "Result adapter can only return schema issues"),
        (S.is_, "Type guard adapter can only return false for schema issues"),
    ],
)
def test_adapters_raise_on_non_schema_failures(
    cause: Cause[Issue],
    adapter: Callable[[S.Bottom[object]], Callable[[object], object]],
    expected: str,
):
    schema = S.Bottom[object](Dying(cause=cause))
    parse = adapter(schema)
    with pytest.raises(RuntimeError, match=f"^{re.escape(expected)}\n") as raised:
        parse("a")
    assert raised.value.__cause__ is DEFECT


@pytest.mark.parametrize("cause", CAUSES.values(), ids=CAUSES.keys())
def test_asserts_and_make_raise_on_non_schema_failures(cause: Cause[Issue]):
    schema = S.Bottom[object](Dying(cause=cause))
    with pytest.raises(RuntimeError, match=r"^Assertion adapter can only throw schema issues\n"):
        S.asserts(schema, "a")
    with pytest.raises(RuntimeError, match=r"^Constructor adapter can only throw schema issues\n"):
        schema.make("a")
    with pytest.raises(
        RuntimeError, match=r"^Option adapter can only return none for schema issues\n"
    ):
        schema.make_option("a")


def test_exit_and_effect_adapters_keep_the_whole_cause():
    schema = S.Bottom[object](Dying(cause=CAUSES["issue and defect"]))
    exit = S.decode_unknown_exit(schema)("a")
    assert isinstance(exit, Failure)
    assert exit.cause.find_defect() is DEFECT
    found = exit.cause.find_error()
    assert isinstance(found, Ok)
    assert found.value.message == "schema issue"

    ran = fx.run_sync_exit(S.encode_unknown_effect(schema)("a"))
    assert isinstance(ran, Failure)
    assert ran.cause.find_defect() is DEFECT
