"""Ports of Effect's ``SchemaIssue.test.ts``. Each test's docstring is the
Effect test title. ``isIssue`` is ``issue.is_issue``.

Ported in part: "does not expose an actual field", "preserves structural
metadata" and "formats leaf issues with static built-in messages" leave out
the ``OneOf``, ``AnyOf`` and ``Filter`` issues, which come with unions and
checks. Omitted: "uses an empty AnyOf when no union candidates apply"
(unions).
"""

from pyfect import schema as S
from pyfect.schema import issue
from pyfect.schema.issue import (
    Composite,
    Encoding,
    Forbidden,
    InvalidType,
    InvalidValue,
    Leaf,
    MissingKey,
    Pointer,
    UnexpectedKey,
)


def test_is_issue():
    """isIssue"""
    assert issue.is_issue(MissingKey(None))
    assert not issue.is_issue({"~effect/SchemaIssue/Issue": False})


def test_does_not_expose_an_actual_field():
    """does not expose an actual field"""
    invalid_value = InvalidValue()
    issues: list[issue.Issue] = [
        InvalidType(S.String.ast),
        invalid_value,
        MissingKey(None),
        UnexpectedKey(S.String.ast),
        Forbidden(None),
        Encoding(S.String.ast, invalid_value),
        Pointer(("value",), invalid_value),
        Composite(S.String.ast, (invalid_value,)),
    ]

    for i in issues:
        assert not hasattr(i, "actual")


def test_preserves_structural_metadata():
    """preserves structural metadata"""
    annotations = {"message": "custom message"}
    invalid_type = InvalidType(S.String.ast)
    invalid_value = InvalidValue(annotations)
    unexpected_key = UnexpectedKey(S.Number.ast)

    assert invalid_type.ast is S.String.ast
    assert invalid_value.annotations is annotations
    assert unexpected_key.ast is S.Number.ast


def test_formats_leaf_issues_with_static_built_in_messages():
    """formats leaf issues with static built-in messages"""
    cases: list[tuple[Leaf, str]] = [
        (InvalidType(S.String.ast), "Expected string"),
        (InvalidValue(), "Expected a valid value"),
        (MissingKey(None), "Missing key"),
        (UnexpectedKey(S.String.ast), "Expected no excess property"),
        (Forbidden(None), "Forbidden operation"),
    ]

    for leaf, expected in cases:
        assert issue.format_issue(leaf) == expected
