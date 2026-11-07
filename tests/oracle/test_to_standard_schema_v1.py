"""Ports of Effect's ``toStandardSchemaV1.test.ts``.

Python mappings: ``schema["~standard"]`` is ``adapted.__standard__``; a
``Promise`` result is an awaitable; ``Schema.Class<A>("A")({...})`` is
``class A(S.Class)`` and ``extend`` is subclassing the adapter.
``Object.freeze`` has no Python equivalent, so "can re-adapt a frozen
adapter with a custom hook" re-adapts a plain adapter.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, cast

import pytest

import pyfect as fx
import pyfect.schema as S
from pyfect.context import Tag
from pyfect.option import Option
from pyfect.result import Err
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema.issue import make_formatter_default

from ._schema_binary import struct

type Issues = Sequence[dict[str, object]]


def _validate(schema: Any, input: object) -> Any:
    return schema.__standard__.validate(input)


def _issues(result: Any) -> list[dict[str, object]]:
    assert "issues" in result, f"expected issues, got {result!r}"
    return [{"message": i["message"], "path": i.get("path")} for i in result["issues"]]


def _sync_success(schema: Any, input: object, value: object) -> None:
    result = _validate(schema, input)
    assert not inspect.isawaitable(result), "Expected value, got awaitable"
    assert result == {"value": value}


def _sync_failure(
    schema: Any, input: object, issues: Issues | Callable[[list[dict[str, object]]], None]
) -> None:
    result = _validate(schema, input)
    assert not inspect.isawaitable(result), "Expected value, got awaitable"
    if callable(issues):
        issues(_issues(result))
    else:
        assert _issues(result) == [{**i, "path": tuple(cast("Any", i["path"]))} for i in issues]


def _awaited(schema: Any, input: object) -> Any:
    result = _validate(schema, input)
    assert inspect.isawaitable(result), "Expected awaitable, got value"
    return asyncio.run(_wait(result))


async def _wait(result: Awaitable[Any]) -> Any:
    return await result


def _formatted_failure(schema: Any, input: object, issues: Issues, message: str) -> None:
    _sync_failure(S.to_standard_schema_v1(schema), input, issues)
    result = S.decode_unknown_result(schema, errors="all")(input)
    assert isinstance(result, Err)
    assert make_formatter_default()(result.error.issue) == message


def _async_string() -> Any:
    def later(os: Option[str], _: object) -> Any:
        return fx.sleep(0.01).as_(os)

    return S.String.pipe(
        S.decode(T.Transformation(G.transform_optional_effect(later), G.passthrough()))
    )


_ASYNC_NON_EMPTY_STRING = _async_string().check(S.is_non_empty())


def test_can_re_adapt_a_frozen_adapter_with_a_custom_hook():
    """can re-adapt a frozen adapter with a custom hook"""
    frozen = S.to_standard_schema_v1(S.String)
    custom = S.to_standard_schema_v1(frozen, leaf_hook=lambda _: "Custom message")
    _sync_failure(custom, None, [{"message": "Custom message", "path": []}])


def test_isolates_leaf_hook_between_adaptations_of_the_same_schema():
    """isolates leafHook between adaptations of the same schema"""
    schema = S.String.annotate()
    standard = S.to_standard_schema_v1(schema)
    custom = S.to_standard_schema_v1(schema, leaf_hook=lambda _: "Custom message")
    _sync_failure(custom, None, [{"message": "Custom message", "path": []}])
    _sync_failure(standard, None, [{"message": "Expected string", "path": []}])


def test_retains_validation_when_piping_a_class_adapter_into_the_json_schema_adapter():
    """retains validation when piping a class adapter into the JSON-schema adapter"""

    class Parent(S.Class):
        a: str

    adapted = S.to_standard_schema_v1(Parent, leaf_hook=lambda _: "Custom message")
    both = adapted.pipe(S.to_standard_json_schema_v1)
    _sync_failure(both, {"a": None}, [{"message": "Custom message", "path": ["a"]}])


def test_validates_subclass_fields_when_the_parent_already_has_a_standard_schema_adapter():
    """validates subclass fields when the parent already has a Standard Schema adapter"""

    class Parent(S.Class):
        a: str

    parent: Any = S.to_standard_json_schema_v1(S.to_standard_schema_v1(Parent))

    class Child(parent):
        b: float

    child = S.to_standard_schema_v1(cast("Any", Child))
    assert child.__standard__.json_schema is None
    _sync_success(parent, {"a": "a"}, Parent(a="a"))
    _sync_failure(child, {"a": "a"}, [{"path": ["b"], "message": "Missing key"}])
    _sync_success(child, {"a": "a", "b": 1}, Child(a="a", b=1))


def test_should_return_a_standard_schema_v1_schema():
    """should return a Standard Schema V1 schema"""
    standard = S.to_standard_schema_v1(S.FiniteFromString)
    assert S.is_schema(standard)
    assert standard.__standard__.version == 1
    assert standard.__standard__.vendor == "pyfect"


def test_should_support_both_standards():
    """should support both standards"""
    both = S.to_standard_json_schema_v1(S.to_standard_schema_v1(S.String))
    _sync_success(both, "a", "a")


def test_sync_decoding():
    """sync decoding"""
    standard = S.to_standard_schema_v1(S.NonEmptyString)
    _sync_success(standard, "a", "a")
    _sync_failure(standard, None, [{"message": "Expected string", "path": []}])
    _sync_failure(
        standard, "", [{"message": "Expected a value with a length of at least 1", "path": []}]
    )


def test_async_decoding():
    """async decoding"""
    standard = S.to_standard_schema_v1(_ASYNC_NON_EMPTY_STRING)
    assert _awaited(standard, "a") == {"value": "a"}
    _sync_failure(standard, None, [{"message": "Expected string", "path": []}])
    assert _issues(_awaited(standard, "")) == [
        {"message": "Expected a value with a length of at least 1", "path": ()}
    ]


class _MagicNumber(Tag[int], key="MagicNumber"):
    pass


def _expect_missing_service(issues: list[dict[str, object]]) -> None:
    assert len(issues) == 1
    assert issues[0]["path"] is None
    assert "Service not found: MagicNumber" in cast("str", issues[0]["message"])


def test_missing_dependencies_sync_decoding_should_throw():
    """missing dependencies / sync decoding should throw"""

    def decode(n: float, _: object) -> Any:
        return _MagicNumber().map(lambda magic: n * magic)

    schema: Any = S.Number.pipe(
        S.decode(T.Transformation(G.transform_effect(decode), G.passthrough()))
    )
    _sync_failure(S.to_standard_schema_v1(schema), 1, _expect_missing_service)


def test_missing_dependencies_async_decoding_should_report_a_missing_dependency():
    """missing dependencies / async decoding should report a missing dependency"""

    def decode(n: float, _: object) -> Any:
        return _MagicNumber().flat_map(lambda magic: fx.sleep(0.01).as_(n * magic))

    schema: Any = S.Number.pipe(
        S.decode(T.Transformation(G.transform_effect(decode), G.passthrough()))
    )
    _sync_failure(S.to_standard_schema_v1(schema), 1, _expect_missing_service)


_MIN_1 = "Expected a value with a length of at least 1"


def test_by_default_should_return_all_issues():
    """by default should return all issues"""
    standard = S.to_standard_schema_v1(struct(a=S.NonEmptyString, b=S.NonEmptyString))
    _sync_success(standard, {"a": "a", "b": "b"}, {"a": "a", "b": "b"})
    _sync_failure(standard, None, [{"message": "Expected object", "path": []}])
    _sync_failure(standard, {"a": "a", "b": ""}, [{"message": _MIN_1, "path": ["b"]}])
    _sync_failure(standard, {"a": "", "b": "b"}, [{"message": _MIN_1, "path": ["a"]}])
    _sync_failure(
        standard,
        {"a": "", "b": ""},
        [{"message": _MIN_1, "path": ["a"]}, {"message": _MIN_1, "path": ["b"]}],
    )


def test_with_parse_options_errors_first_should_return_only_the_first_issue():
    """with parseOptions: { errors: 'first' } should return only the first issue"""
    standard = S.to_standard_schema_v1(
        struct(a=S.NonEmptyString, b=S.NonEmptyString), parse_options={"errors": "first"}
    )
    _sync_failure(standard, {"a": "", "b": ""}, [{"message": _MIN_1, "path": ["a"]}])


@pytest.mark.parametrize("message", ["Custom message", ""])
def test_preserves_a_custom_filters_path_with_message(message: str):
    """should respect the `message` annotation / preserves a custom filter's path with message %j"""
    passwords = struct(password=S.String, confirm=S.String)
    schema = passwords.check(
        S.make_filter(
            lambda value: (
                value["password"] == value["confirm"] or (("confirm",), "Passwords must match")
            ),
            message=message,
        )
    )
    _formatted_failure(
        schema,
        {"password": "a", "confirm": "b"},
        [{"message": message, "path": ["confirm"]}],
        f'{message}\n  at ["confirm"]',
    )


def test_preserves_annotated_filter_paths_ancestor_paths_and_sibling_messages():
    """should respect the `message` annotation / preserves annotated filter paths, ancestor paths, and sibling messages"""  # noqa: E501
    record = S.Record(S.String, S.Number).check(
        S.is_property_names(S.String.check(S.is_max_length(2)), message="Custom message")
    )
    _formatted_failure(
        record,
        {"abc": 1},
        [{"message": "Custom message", "path": ["abc"]}],
        'Custom message\n  at ["abc"]',
    )
    schema = struct(records=S.Array(record), other=S.String)
    _formatted_failure(
        schema,
        {"records": [{"abc": 1}], "other": None},
        [
            {"message": "Custom message", "path": ["records", 0, "abc"]},
            {"message": "Expected string", "path": ["other"]},
        ],
        'Custom message\n  at ["records"][0]["abc"]\nExpected string\n  at ["other"]',
    )


@pytest.mark.parametrize(
    ("annotations", "messages"),
    [({}, ("Invalid a", "Invalid b")), ({"message": "Custom message"}, ("Custom message",) * 2)],
)
def test_formats_grouped_filter_failures_with_annotations(
    annotations: dict[str, Any], messages: tuple[str, str]
):
    """should respect the `message` annotation / formats grouped filter failures with annotations $annotations"""  # noqa: E501
    a, b = messages
    schema = (
        struct(a=S.String, b=S.String)
        .annotate(message="Struct message")
        .check(
            S.make_filter(lambda _: [(("a",), "Invalid a"), (("b",), "Invalid b")], **annotations)
        )
    )
    _formatted_failure(schema, None, [{"message": "Struct message", "path": []}], "Struct message")
    _formatted_failure(
        schema,
        {"a": "a", "b": "b"},
        [{"message": a, "path": ["a"]}, {"message": b, "path": ["b"]}],
        f'{a}\n  at ["a"]\n{b}\n  at ["b"]',
    )


@pytest.mark.parametrize(
    ("annotations", "message"),
    [
        ({}, "Returned message"),
        ({"message": "Filter message"}, "Filter message"),
        ({"message": ""}, ""),
    ],
)
def test_formats_a_directly_returned_message_with_annotations(
    annotations: dict[str, Any], message: str
):
    """should respect the `message` annotation / formats a directly returned message with annotations $annotations"""  # noqa: E501
    schema = S.String.check(S.make_filter(lambda _: "Returned message", **annotations))
    _formatted_failure(schema, "", [{"message": message, "path": []}], message)


def test_string_and_annotation():
    """should respect the `message` annotation / String / String & annotation"""
    standard = S.to_standard_schema_v1(S.String.annotate(message="Custom message"))
    _sync_failure(standard, None, [{"message": "Custom message", "path": []}])


def test_string_and_annotation_and_is_non_empty():
    """should respect the `message` annotation / String / String & annotation & isNonEmpty"""
    schema = S.String.annotate(message="Custom message").check(S.is_non_empty())
    _sync_failure(
        S.to_standard_schema_v1(schema), None, [{"message": "Custom message", "path": []}]
    )


def test_string_and_is_non_empty_and_annotation():
    """should respect the `message` annotation / String / String & isNonEmpty & annotation"""
    schema = S.String.check(S.is_non_empty()).annotate(message="Custom message")
    standard = S.to_standard_schema_v1(schema)
    _sync_failure(standard, None, [{"message": "Expected string", "path": []}])
    _sync_failure(standard, "", [{"message": "Custom message", "path": []}])


def test_string_and_is_non_empty_annotation():
    """should respect the `message` annotation / String / String & isNonEmpty(annotation)"""
    schema = S.String.check(S.is_non_empty(message="Custom message"))
    standard = S.to_standard_schema_v1(schema)
    _sync_failure(standard, None, [{"message": "Expected string", "path": []}])
    _sync_failure(standard, "", [{"message": "Custom message", "path": []}])


def test_string_and_annotation_and_is_non_empty_and_annotation():
    """should respect the `message` annotation / String / String & annotation & isNonEmpty & annotation"""  # noqa: E501
    schema = (
        S.String.annotate(message="Custom message")
        .check(S.is_non_empty())
        .annotate(message="Custom message 2")
    )
    standard = S.to_standard_schema_v1(schema)
    _sync_failure(standard, None, [{"message": "Custom message", "path": []}])
    _sync_failure(standard, "", [{"message": "Custom message 2", "path": []}])


def test_string_and_annotation_and_is_non_empty_annotation():
    """should respect the `message` annotation / String / String & annotation & isNonEmpty(annotation)"""  # noqa: E501
    schema = S.String.annotate(message="Custom message").check(
        S.is_non_empty(message="Custom message 2")
    )
    standard = S.to_standard_schema_v1(schema)
    _sync_failure(standard, None, [{"message": "Custom message", "path": []}])
    _sync_failure(standard, "", [{"message": "Custom message 2", "path": []}])


def test_string_and_annotation_and_is_non_empty_annotation_and_is_max_length_annotation():
    """should respect the `message` annotation / String / String & annotation & isNonEmpty(annotation) & isMaxLength(annotation)"""  # noqa: E501
    schema = (
        S.String.annotate(message="Custom message")
        .check(S.is_non_empty(message="Custom message 2"))
        .check(S.is_max_length(2, message="Custom message 3"))
    )
    standard = S.to_standard_schema_v1(schema)
    _sync_failure(standard, None, [{"message": "Custom message", "path": []}])
    _sync_failure(standard, "", [{"message": "Custom message 2", "path": []}])
    _sync_failure(standard, "abc", [{"message": "Custom message 3", "path": []}])


def test_struct_message_missing_key():
    """should respect the `message` annotation / Struct / messageMissingKey"""
    schema = struct(a=S.String.annotate_key(message_missing_key="Custom message"))
    _sync_failure(
        S.to_standard_schema_v1(schema), {}, [{"message": "Custom message", "path": ["a"]}]
    )


def test_struct_message_unexpected_key():
    """should respect the `message` annotation / Struct / messageUnexpectedKey"""
    schema = struct(a=S.String).annotate(message_unexpected_key="Custom message")
    standard = S.to_standard_schema_v1(schema, parse_options={"on_excess_property": "error"})
    _sync_failure(standard, {"a": "a", "b": "b"}, [{"message": "Custom message", "path": ["b"]}])


def test_tuple_message_missing_key():
    """should respect the `message` annotation / Tuple / messageMissingKey"""
    schema = S.Tuple(S.String.annotate_key(message_missing_key="Custom message"))
    _sync_failure(S.to_standard_schema_v1(schema), [], [{"message": "Custom message", "path": [0]}])


def test_tuple_message_unexpected_key():
    """should respect the `message` annotation / Tuple / messageUnexpectedKey"""
    schema = S.Tuple(S.String).annotate(message_unexpected_key="Custom message")
    standard = S.to_standard_schema_v1(schema, parse_options={"on_excess_property": "error"})
    _sync_failure(standard, ["a", "b"], [{"message": "Custom message", "path": [1]}])


def test_union_literals():
    """should respect the `message` annotation / Union / Literals"""
    schema = S.Literals("a", "b").annotate(message="Custom message")
    standard = S.to_standard_schema_v1(schema)
    _sync_failure(standard, None, [{"message": "Custom message", "path": []}])
    _sync_failure(standard, "-", [{"message": "Custom message", "path": []}])


def test_tree_leaf_hook_string():
    """treeLeafHook & verboseCheckHook / String"""
    from pyfect.schema.issue import leaf_message

    standard = S.to_standard_schema_v1(S.String, leaf_hook=leaf_message)
    _sync_failure(standard, None, [{"message": "Expected string", "path": []}])


def test_tree_leaf_hook_non_empty_string():
    """treeLeafHook & verboseCheckHook / NonEmptyString"""
    from pyfect.schema.issue import leaf_message

    standard = S.to_standard_schema_v1(S.NonEmptyString, leaf_hook=leaf_message)
    _sync_failure(standard, "", [{"message": _MIN_1, "path": []}])
