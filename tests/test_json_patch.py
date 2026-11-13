"""``json_patch`` beyond Effect's own tests (those are ports in
``tests/oracle/test_json_patch.py``), checked against Effect 4.1.2 in Node.

Effect's ``JsonPatch.apply`` throws a ``TypeError`` for a value that is not a
patch (``patch is not iterable``; reading ``path`` of a non-object), takes a
missing ``op`` or an unknown one as ``replace``, and ``get`` compares leaves
with ``Object.is``, where NaN is NaN.
"""

from typing import Any, cast

import pytest

from pyfect import json_patch

_DOC = {"a": 1}


@pytest.mark.parametrize(
    "patch",
    [
        {"op": "add"},
        "add",
        None,
        ["x"],
        [{"op": "add", "value": 1}],
        [{"op": "add", "path": 5, "value": 1}],
        [{"op": "replace", "path": "/a"}],
        [{"op": "add", "path": "/b"}],
        [{"op": "add", "path": "", "description": "no value"}],
    ],
    ids=[
        "an object",
        "a string",
        "None",
        "a string operation",
        "no path",
        "a number path",
        "replace without value",
        "add without value",
        "root add without value",
    ],
)
def test_a_value_that_is_not_a_patch_raises_type_error(patch: object) -> None:
    with pytest.raises(TypeError):
        json_patch.apply(cast("Any", patch), _DOC)


def test_an_unknown_or_missing_op_replaces_as_in_effect() -> None:
    test_op = cast("Any", [{"op": "test", "path": "/a", "value": 2}])
    no_op = cast("Any", [{"path": "/a", "value": 3}])
    assert json_patch.apply(test_op, _DOC) == {"a": 2}
    assert json_patch.apply(no_op, _DOC) == {"a": 3}


def test_a_remove_needs_no_value() -> None:
    assert json_patch.apply([{"op": "remove", "path": "/a"}], _DOC) == {}


def test_distinct_nan_objects_are_the_same_value() -> None:
    inf = float("inf")
    before, after = inf - inf, inf * 0
    assert before is not after
    assert json_patch.get({"w": before}, {"w": after}) == []
    assert json_patch.get([before], [after]) == []
    assert json_patch.get(before, after) == []


def test_numbers_compare_as_javascript_numbers() -> None:
    assert json_patch.get(1, 1.0) == []
    assert json_patch.get(0.0, -0.0) == [{"op": "replace", "path": "", "value": -0.0}]
    assert json_patch.get(1, True) == [{"op": "replace", "path": "", "value": True}]
    assert json_patch.get(float("nan"), 0) == [{"op": "replace", "path": "", "value": 0}]
