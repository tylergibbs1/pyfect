"""Ports of the "SchemaIssue reportInput" block of Effect's
``Formatter.test.ts``. Each test's docstring is the Effect test title,
prefixed by its ``describe`` block.

Python mappings: an issue keeps its input as ``Some(value)`` (``None``
without ``report_input``), so "present ``undefined``" is ``Some(None)``;
``SchemaParser.decodeUnknownResult`` is ``S.decode_unknown_result``, whose
``Err`` holds a ``SchemaError`` with the issue; JavaScript's property
descriptors and ``JSON.stringify`` of an issue have no counterpart (the
issue's ``input`` field is checked instead).

Omitted:
- "reports input in Standard Schema messages without adding an input
  field": ``toStandardSchemaV1`` is the pydantic adapter (§4
  StandardSchema); ``make_formatter_standard_schema_v1`` is covered by the
  hook titles.
"""

from typing import TypedDict

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.exit import Exit, Failure
from pyfect.option import Option, Some
from pyfect.redacted import make as redacted
from pyfect.result import Err, Ok, Result
from pyfect.run import run_sync_exit
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import (
    AnyOf,
    Composite,
    Encoding,
    Filter,
    Forbidden,
    InvalidType,
    InvalidValue,
    Issue,
    MissingKey,
    OneOf,
    Pointer,
    UnexpectedKey,
    has_input,
    make_formatter_default,
    make_formatter_standard_schema_v1,
)

format_issue = make_formatter_default()


def _union() -> S.ast.Union:
    node = S.Union(S.String, S.Number).ast
    assert isinstance(node, S.ast.Union)
    return node


UNION = _union()


def _failure(result: Result[object, S.SchemaError]) -> Issue:
    assert isinstance(result, Err)
    return result.error.issue


def _error(exit: Exit[object, Issue]) -> Issue:
    assert isinstance(exit, Failure)
    found = exit.cause.find_error()
    assert isinstance(found, Ok)
    return found.value


def _min_length() -> S.ast.Filter[str]:
    check = S.is_min_length(1)
    assert isinstance(check, S.ast.Filter)
    return check


def test_supports_every_value_bearing_issue_constructor():
    """SchemaIssue reportInput / supports every value-bearing issue constructor"""
    input = Some({"value": "secret"})
    invalid_value = InvalidValue()
    issues: list[Issue] = [
        InvalidType(S.String.ast, input),
        InvalidValue(None, input),
        UnexpectedKey(S.String.ast, input),
        Forbidden(None, input),
        OneOf(UNION, (S.String.ast,), input),
        Filter(_min_length(), invalid_value, input),
        Encoding(S.String.ast, invalid_value, input),
        Composite(S.String.ast, (invalid_value,), input),
        AnyOf(UNION, (invalid_value,), input),
    ]
    for issue in issues:
        assert has_input(issue)
    assert not has_input(InvalidType(S.String.ast))
    assert not has_input(Pointer((), invalid_value))
    assert not has_input(MissingKey(None))


def test_reports_input_only_when_enabled():
    """SchemaIssue reportInput / reports input only when enabled"""
    input = {"secret": "value"}
    disabled = _failure(S.decode_unknown_result(S.String)(input))
    assert isinstance(disabled, InvalidType)
    assert not has_input(disabled)
    assert format_issue(disabled) == "Expected string"

    enabled = _failure(S.decode_unknown_result(S.String)(input, report_input=True))
    assert isinstance(enabled, InvalidType)
    assert has_input(enabled)
    assert enabled.input == Some(input)
    assert format_issue(enabled) == 'Expected string, got {"secret":"value"}'


class _Value(TypedDict):
    value: str


class _Number(TypedDict):
    value: float


def test_distinguishes_undefined_input_from_missing_input():
    """SchemaIssue reportInput / distinguishes undefined input from missing input"""
    none = _failure(S.decode_unknown_result(S.String)(None, report_input=True))
    assert has_input(none)
    assert isinstance(none, InvalidType)
    assert none.input == Some(None)
    assert format_issue(none) == "Expected string, got null"

    missing = _failure(S.decode_unknown_result(S.Struct(_Value))({}, report_input=True))
    assert isinstance(missing, Composite)
    pointer = missing.issues[0]
    assert isinstance(pointer, Pointer)
    assert not has_input(pointer)
    assert isinstance(pointer.issue, MissingKey)
    assert not has_input(pointer.issue)
    assert format_issue(pointer.issue) == "Missing key"


def test_reports_local_inputs_for_structs():
    """SchemaIssue reportInput / reports local inputs for structs"""
    input = {"value": "not a number", "extra": "secret"}
    failure = _failure(
        S.decode_unknown_result(S.Struct(_Number))(
            input, errors="all", on_excess_property="error", report_input=True
        )
    )
    assert isinstance(failure, Composite)
    assert failure.input == Some(input)
    extra, value = failure.issues[0], failure.issues[1]
    assert isinstance(extra, Pointer)
    assert not has_input(extra)
    assert isinstance(extra.issue, UnexpectedKey)
    assert extra.issue.input == Some("secret")
    assert isinstance(value, Pointer)
    assert not has_input(value)
    assert isinstance(value.issue, InvalidType)
    assert value.issue.input == Some("not a number")


def test_reports_filter_input_on_parser_created_issues():
    """SchemaIssue reportInput / reports filter input on parser-created issues"""
    schema = S.String.check(S.is_min_length(1))
    failure = _failure(S.decode_unknown_result(schema)("", report_input=True))
    assert isinstance(failure, Composite)
    filter = failure.issues[0]
    assert isinstance(filter, Filter)
    assert filter.input == Some("")
    assert isinstance(filter.issue, InvalidValue)
    assert filter.issue.input == Some("")
    assert format_issue(filter) == 'Expected a value with a length of at least 1, got ""'


def test_allows_user_provided_transformations_to_report_their_input():
    """SchemaIssue reportInput / allows user-provided transformations to report their input"""

    def decode(input: str, options: S.ParseOptions) -> fx.Effect[str, Issue]:
        return fx.fail(InvalidValue(None, Some(input) if options.get("report_input") else None))

    schema = S.String.pipe(S.decode(T.Transformation(G.transform_effect(decode), G.passthrough())))
    failure = _failure(S.decode_unknown_result(schema)("secret", report_input=True))
    assert isinstance(failure, Encoding)
    assert isinstance(failure.issue, InvalidValue)
    assert failure.issue.input == Some("secret")
    assert format_issue(failure) == 'Invalid data "secret"'


def test_reports_input_from_effectful_checks():
    """SchemaIssue reportInput / reports input from effectful checks"""

    def reject(_: str, __: S.ParseOptions) -> fx.Effect[G.CheckOutput]:
        return fx.succeed(False)

    check = G.check_effect(reject)
    schema = S.String.pipe(S.decode(T.Transformation(check, G.passthrough())))
    failure = _failure(S.decode_unknown_result(schema)("secret", report_input=True))
    assert isinstance(failure, Encoding)
    assert isinstance(failure.issue, InvalidValue)
    assert failure.issue.input == Some("secret")
    assert format_issue(failure) == 'Invalid data "secret"'


def test_does_not_infer_input_through_a_user_provided_pointer():
    """SchemaIssue reportInput / does not infer input through a user-provided pointer"""
    inner = InvalidValue()
    pointer = Pointer(("value",), inner)
    schema = S.String.check(S.make_filter(lambda _: pointer))
    failure = _failure(S.decode_unknown_result(schema)("secret", report_input=True))
    assert isinstance(failure, Composite)
    filter = failure.issues[0]
    assert isinstance(filter, Filter)
    assert filter.input == Some("secret")
    assert filter.issue is pointer
    assert not has_input(pointer)
    assert not has_input(inner)


def test_reports_input_for_union_wrappers():
    """SchemaIssue reportInput / reports input for union wrappers"""
    any_of = _failure(
        S.decode_unknown_result(S.Union(S.Literal("a"), S.Literal("b")))("c", report_input=True)
    )
    assert isinstance(any_of, AnyOf)
    assert any_of.input == Some("c")
    assert format_issue(any_of) == 'Expected "a" | "b", got "c"'

    one_of = _failure(
        S.decode_unknown_result(S.Union(S.Literal("a"), S.Literal("a"), mode="one_of"))(
            "a", report_input=True
        )
    )
    assert isinstance(one_of, OneOf)
    assert one_of.input == Some("a")
    assert format_issue(one_of) == 'Expected exactly one member to match the input "a"'


def test_runtime_report_input_overrides_preset_options_and_reaches_nested_schemas():
    """SchemaIssue reportInput / runtime reportInput overrides preset options and reaches nested schemas"""  # noqa: E501
    enabled = _failure(S.decode_unknown_result(S.String, report_input=False)(1, report_input=True))
    assert isinstance(enabled, InvalidType)
    assert enabled.input == Some(1)

    disabled = _failure(S.decode_unknown_result(S.String, report_input=True)(1, report_input=False))
    assert not has_input(disabled)

    nested_input = {"value": 1}
    nested = _failure(S.decode_unknown_result(S.Struct(_Value))(nested_input, report_input=True))
    assert isinstance(nested, Composite)
    assert nested.input == Some(nested_input)
    pointer = nested.issues[0]
    assert isinstance(pointer, Pointer)
    assert has_input(pointer.issue)
    assert isinstance(pointer.issue, InvalidType)
    assert pointer.issue.input == Some(1)


def test_distinguishes_present_undefined_from_absent_input_in_forbidden():
    """SchemaIssue reportInput / distinguishes present undefined from absent input in forbidden"""

    def message(_: Option[None]) -> str:
        return "not allowed"

    getter = G.forbidden(message)
    options: S.ParseOptions = {"report_input": True}
    issue = _error(run_sync_exit(fx.suspend(lambda: G.run(getter, Some(None), options))))
    assert isinstance(issue, Forbidden)
    assert has_input(issue)
    assert issue.input == Some(None)
    assert format_issue(issue) == "not allowed"

    issue = _error(run_sync_exit(fx.suspend(lambda: G.run(getter, None, options))))
    assert isinstance(issue, Forbidden)
    assert not has_input(issue)


def test_formats_reported_inputs_with_the_historical_templates():
    """SchemaIssue reportInput / formats reported inputs with the historical templates"""
    one = Some(1)
    invalid_value = InvalidValue()
    assert format_issue(InvalidType(S.String.ast, one)) == "Expected string, got 1"
    assert format_issue(InvalidValue(None, one)) == "Invalid data 1"
    assert format_issue(UnexpectedKey(S.String.ast, one)) == "Unexpected key with value 1"
    assert (
        format_issue(OneOf(UNION, (S.String.ast,), one))
        == "Expected exactly one member to match the input 1"
    )
    assert format_issue(Forbidden(None, one)) == "Forbidden operation"
    assert (
        format_issue(Filter(_min_length(), invalid_value, one))
        == "Expected a value with a length of at least 1, got 1"
    )
    assert format_issue(AnyOf(UNION, (), one)) == "Expected string | number, got 1"


def test_does_not_inherit_input_from_wrappers():
    """SchemaIssue reportInput / does not inherit input from wrappers"""
    secret = Some("secret")
    inner = InvalidValue()
    assert format_issue(Encoding(S.String.ast, inner, secret)) == "Expected a valid value"
    assert format_issue(Composite(S.String.ast, (inner,), secret)) == "Expected a valid value"
    assert (
        format_issue(Filter(_min_length(), InvalidValue(None, secret)))
        == "Expected a value with a length of at least 1"
    )


def test_uses_expected_annotations_only_for_invalid_value():
    """SchemaIssue reportInput / uses expected annotations only for InvalidValue"""
    secret = Some("secret")
    assert format_issue(InvalidValue({"expected": "a valid value"})) == "Expected a valid value"
    assert (
        format_issue(InvalidValue({"expected": "a valid value"}, secret))
        == 'Expected a valid value, got "secret"'
    )
    assert (
        format_issue(InvalidValue({"expected": "ignored", "message": "custom message"}, secret))
        == "custom message"
    )
    assert (
        format_issue(Forbidden({"expected": "a permitted operation"}, secret))
        == "Forbidden operation"
    )
    filter = Filter(_min_length(), InvalidValue({"expected": "a custom value"}, secret))
    assert format_issue(filter) == 'Expected a custom value, got "secret"'
    formatter = make_formatter_standard_schema_v1(check_hook=lambda _: None)
    assert formatter(filter)["issues"] == [
        {"message": 'Expected a custom value, got "secret"', "path": ()}
    ]


def test_uses_expected_annotations_in_built_ins():
    """SchemaIssue reportInput / uses expected annotations in built-ins"""
    disabled = _failure(S.decode_unknown_result(S.URLFromString)("invalid"))
    assert format_issue(disabled) == "Expected a valid URL string"
    enabled = _failure(S.decode_unknown_result(S.URLFromString)("invalid", report_input=True))
    assert format_issue(enabled) == 'Expected a valid URL string, got "invalid"'


def test_keeps_redacted_input_redacted():
    """SchemaIssue reportInput / keeps Redacted input redacted"""
    input = redacted("secret", label="password")
    failure = _failure(S.decode_unknown_result(S.Redacted(S.Number))(input, report_input=True))
    assert isinstance(failure, Composite)
    pointer = failure.issues[0]
    assert isinstance(pointer, Pointer)
    assert isinstance(pointer.issue, InvalidValue)
    assert pointer.issue.input == Some(input)
    assert format_issue(failure) == 'Invalid data <redacted:password>\n  at ["value"]'


def test_preserves_custom_messages_and_hooks():
    """SchemaIssue reportInput / preserves custom messages and hooks"""
    secret = Some("secret")
    invalid_type = InvalidType(S.String.annotate(message="custom message").ast, secret)
    assert format_issue(invalid_type) == "custom message"

    leaf_formatter = make_formatter_standard_schema_v1(leaf_hook=lambda _: "redacted leaf")
    assert leaf_formatter(invalid_type)["issues"] == [{"message": "redacted leaf", "path": ()}]

    filter = Filter(_min_length(), InvalidValue(), secret)
    check_formatter = make_formatter_standard_schema_v1(check_hook=lambda _: "redacted check")
    assert check_formatter(filter)["issues"] == [{"message": "redacted check", "path": ()}]
