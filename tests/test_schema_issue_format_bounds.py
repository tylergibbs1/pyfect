"""``format_issue`` writes at most ``DEFAULT_MAX_FORMATTED_ISSUES`` leaves
and counts the rest: each line repeats its whole path, so the message of
every failing leaf of a deep value grew as (leaves x depth), and the MCP
server sends that message back for invalid tool arguments."""

from __future__ import annotations

import json
from typing import Any, TypedDict

from _growth import Work, assert_near_linear
from _guards import guards

from pyfect import schema as S
from pyfect.schema import issue as I


class Node(TypedDict):
    children: tuple[Node, ...]


Tree: Any = None
Tree = S.Struct(Node, children=S.Array(S.suspend(lambda: Tree)))
_decode = S.decode_unknown_exit(Tree, errors="all")


def _deep(depth: int, leaves: int) -> object:
    value: object = {"children": [1] * leaves}
    for _ in range(depth):
        value = {"children": [value]}
    return value


def _message(value: object) -> str:
    result: Any = _decode(value)
    return result.cause.reasons[0].error.message


def test_a_deep_failure_of_many_leaves_has_a_message_linear_in_its_input() -> None:
    value = _deep(100, 2000)
    message = _message(value)
    assert len(message) < 50 * len(json.dumps(value, separators=(",", ":")))
    assert message.endswith(f"... and {2000 - I.DEFAULT_MAX_FORMATTED_ISSUES} more issues")
    assert message.count("\n  at ") == I.DEFAULT_MAX_FORMATTED_ISSUES


@guards("8608f02f", "issue-format-writes-every-leaf")
def test_formatting_a_deep_failure_takes_near_linear_time() -> None:
    def sized(n: int) -> Work:
        result: Any = _decode(_deep(n, n))
        issue = result.cause.reasons[0].error.issue
        return lambda: I.format_issue(issue)

    assert_near_linear(sized, 200, 8 * 200, bound=32)


def test_max_issues_none_writes_every_leaf_and_small_failures_are_unchanged() -> None:
    result: Any = _decode(_deep(2, 3))
    issue = result.cause.reasons[0].error.issue
    full = I.format_issue(issue, max_issues=None)
    assert full == I.format_issue(issue)
    assert full.count("\n  at ") == 3
    assert I.format_issue(issue, max_issues=1).endswith("... and 2 more issues")
    assert I.format_issue(issue, max_issues=2).endswith("... and 1 more issue")
