"""Ports of Effect's ``JsonPatch.test.ts``. Each test's docstring is the
Effect test title, prefixed by its ``describe`` blocks.

Python mappings: Effect's thrown ``Error`` is a ``ValueError`` with the same
message; arrays are lists (a tuple is taken too), objects dicts. The
``__proto__`` titles check that the key is an ordinary key.

Omitted: "apply / errors / does not treat inherited properties as document
members" (a dict has no prototype chain).
"""

from typing import cast

import pytest

from pyfect import json_patch
from pyfect._json_value import JsonValue
from pyfect.json_patch import JsonPatch, JsonPatchOperation


def _expect_message(patch: JsonPatch, doc: JsonValue, includes: str) -> None:
    with pytest.raises(ValueError) as info:
        json_patch.apply(patch, doc)
    assert includes in str(info.value)


def _applies(patch: JsonPatch, old: JsonValue, new: JsonValue) -> None:
    assert json_patch.apply(patch, old) == new


def test_identical_values():
    """get / root values / returns [] for identical values"""
    for value in cast("list[JsonValue]", [1, "hello", True, None, [1, 2, 3], {"a": 1}]):
        assert json_patch.get(value, value) == []


def test_primitive_changes():
    """get / root values / emits a root replace for primitive changes"""
    cases: list[tuple[JsonValue, JsonValue]] = [
        (1, 2),
        ("hello", "world"),
        (True, False),
        (None, 42),
    ]
    for old, new in cases:
        assert json_patch.get(old, new) == [{"op": "replace", "path": "", "value": new}]


def test_type_changes():
    """get / root values / emits a root replace for type changes"""
    assert json_patch.get(1, "string") == [{"op": "replace", "path": "", "value": "string"}]
    assert json_patch.get([1, 2], {"a": 1}) == [{"op": "replace", "path": "", "value": {"a": 1}}]
    assert json_patch.get({"a": 1}, [1, 2]) == [{"op": "replace", "path": "", "value": [1, 2]}]


def test_array_append():
    """get / arrays / adds new elements (append semantics)"""
    assert json_patch.get([1, 2], [1, 2, 3]) == [{"op": "add", "path": "/2", "value": 3}]
    assert json_patch.get([], [1, 2, 3]) == [
        {"op": "add", "path": "/0", "value": 1},
        {"op": "add", "path": "/1", "value": 2},
        {"op": "add", "path": "/2", "value": 3},
    ]


def test_array_removes_descending():
    """get / arrays / removes elements in descending index order (no index shifting)"""
    assert json_patch.get([1, 2, 3], [1, 2]) == [{"op": "remove", "path": "/2"}]
    patch = json_patch.get([0, 1, 2, 3, 4, 5], [0, 1, 3])
    removed = [int(op["path"][1:]) for op in patch if op["op"] == "remove"]
    assert removed == sorted(removed, reverse=True)
    _applies(patch, [0, 1, 2, 3, 4, 5], [0, 1, 3])


def test_array_replaces():
    """get / arrays / replaces modified elements"""
    assert json_patch.get([1, 2, 3], [1, 4, 3]) == [{"op": "replace", "path": "/1", "value": 4}]


def test_array_mixed():
    """get / arrays / handles mixed operations"""
    assert json_patch.get([1, 2, 3], [1, 4, 5, 6]) == [
        {"op": "replace", "path": "/1", "value": 4},
        {"op": "replace", "path": "/2", "value": 5},
        {"op": "add", "path": "/3", "value": 6},
    ]
    assert json_patch.get([1, 2, 3, 4], [1, 5]) == [
        {"op": "replace", "path": "/1", "value": 5},
        {"op": "remove", "path": "/3"},
        {"op": "remove", "path": "/2"},
    ]


def test_array_nested():
    """get / arrays / supports nested arrays"""
    assert json_patch.get([[1, 2], [3, 4]], [[1, 2], [3, 5]]) == [
        {"op": "replace", "path": "/1/1", "value": 5}
    ]
    assert json_patch.get([[1, 2]], [[1, 2], [3, 4]]) == [
        {"op": "add", "path": "/1", "value": [3, 4]}
    ]


def test_object_stable_order():
    """get / objects / uses stable key order for deterministic patches"""
    patch = json_patch.get({"b": 1, "a": 1}, {"a": 2, "b": 2})
    assert [op["path"] for op in patch if op["op"] == "replace"] == ["/a", "/b"]
    _applies(patch, {"b": 1, "a": 1}, {"a": 2, "b": 2})


def test_object_add_remove_replace():
    """get / objects / adds / removes / replaces properties"""
    assert json_patch.get({"a": 1}, {"a": 1, "b": 2}) == [{"op": "add", "path": "/b", "value": 2}]
    assert json_patch.get({"a": 1, "b": 2}, {"a": 1}) == [{"op": "remove", "path": "/b"}]
    assert json_patch.get({"a": 1, "b": 2}, {"a": 1, "b": 3}) == [
        {"op": "replace", "path": "/b", "value": 3}
    ]


def test_object_removes_sorted():
    """get / objects / removes properties in sorted key order"""
    assert json_patch.get({"a": 1, "b": 2, "c": 3}, {}) == [
        {"op": "remove", "path": "/a"},
        {"op": "remove", "path": "/b"},
        {"op": "remove", "path": "/c"},
    ]


def test_object_mixed():
    """get / objects / handles mixed object operations"""
    assert json_patch.get({"a": 1, "b": 2}, {"a": 1, "c": 3, "d": 4}) == [
        {"op": "remove", "path": "/b"},
        {"op": "add", "path": "/c", "value": 3},
        {"op": "add", "path": "/d", "value": 4},
    ]


def test_object_nested():
    """get / objects / supports nested objects"""
    assert json_patch.get({"a": {"b": 1}}, {"a": {"b": 2}}) == [
        {"op": "replace", "path": "/a/b", "value": 2}
    ]
    assert json_patch.get({"a": {"b": 1}}, {"a": {"b": 1, "c": 2}}) == [
        {"op": "add", "path": "/a/c", "value": 2}
    ]
    assert json_patch.get({"a": {"b": 1, "c": 2}}, {"a": {"b": 1}}) == [
        {"op": "remove", "path": "/a/c"}
    ]


def test_escapes_keys():
    """get / objects / JSON Pointer escaping in keys / escapes '/' as '~1' and '~' as '~0'"""
    assert json_patch.get({"a/b": 1}, {"a/b": 2}) == [
        {"op": "replace", "path": "/a~1b", "value": 2}
    ]
    assert json_patch.get({"a~b": 1}, {"a~b": 2}) == [
        {"op": "replace", "path": "/a~0b", "value": 2}
    ]


def test_literal_tilde_one_key():
    """get / objects / JSON Pointer escaping in keys / represents a literal key '~1' as token '~01'"""  # noqa: E501
    assert json_patch.get({}, {"~1": 0}) == [{"op": "add", "path": "/~01", "value": 0}]


def test_unescape_order_in_keys():
    """get / objects / JSON Pointer escaping in keys / does not confuse '~01' with '/' (unescape order)"""  # noqa: E501
    assert json_patch.get({"a~1b": 1}, {"a~1b": 2}) == [
        {"op": "replace", "path": "/a~01b", "value": 2}
    ]


def test_proto_key():
    """get / objects / JSON Pointer escaping in keys / treats '__proto__' as an own key"""
    assert json_patch.get({"__proto__": {"value": 1}}, {"__proto__": {"value": 2}}) == [
        {"op": "replace", "path": "/__proto__/value", "value": 2}
    ]


def test_deep_updates():
    """get / complex nested structures / emits a minimal-ish patch for deep updates (and is applicable)"""  # noqa: E501
    old: JsonValue = {
        "users": [
            {"id": 1, "name": "Alice", "tags": ["admin"]},
            {"id": 2, "name": "Bob", "tags": []},
        ],
        "metadata": {"version": 1},
    }
    new: JsonValue = {
        "users": [
            {"id": 1, "name": "Alice", "tags": ["admin", "moderator"]},
            {"id": 2, "name": "Bob", "tags": []},
            {"id": 3, "name": "Charlie", "tags": []},
        ],
        "metadata": {"version": 2},
    }
    patch = json_patch.get(old, new)
    assert patch == [
        {"op": "replace", "path": "/metadata/version", "value": 2},
        {"op": "add", "path": "/users/0/tags/1", "value": "moderator"},
        {"op": "add", "path": "/users/2", "value": {"id": 3, "name": "Charlie", "tags": []}},
    ]
    _applies(patch, old, new)


def test_get_does_not_mutate():
    """get / immutability / does not mutate input values"""
    old_array: list[JsonValue] = [1, 2, 3]
    json_patch.get(old_array, [1, 2, 4])
    assert old_array == [1, 2, 3]
    old_object: dict[str, JsonValue] = {"a": 1, "b": 2}
    json_patch.get(old_object, {"a": 1, "b": 3, "c": 4})
    assert old_object == {"a": 1, "b": 2}


def test_identical_references():
    """get / immutability / returns empty array for identical references"""
    value: JsonValue = {"a": 1, "b": [2, 3]}
    assert json_patch.get(value, value) == []


def test_empty_arrays():
    """get / empty structures / handles empty array to empty array"""
    assert json_patch.get([], []) == []


def test_empty_objects():
    """get / empty structures / handles empty object to empty object"""
    assert json_patch.get({}, {}) == []


def test_empty_to_non_empty_array():
    """get / empty structures / handles empty array to non-empty array"""
    assert json_patch.get([], [1, 2]) == [
        {"op": "add", "path": "/0", "value": 1},
        {"op": "add", "path": "/1", "value": 2},
    ]


def test_non_empty_to_empty_array():
    """get / empty structures / handles non-empty array to empty array"""
    patch = json_patch.get([1, 2], [])
    assert patch == [{"op": "remove", "path": "/1"}, {"op": "remove", "path": "/0"}]
    _applies(patch, [1, 2], [])


def test_empty_to_non_empty_object():
    """get / empty structures / handles empty object to non-empty object"""
    assert json_patch.get({}, {"a": 1, "b": 2}) == [
        {"op": "add", "path": "/a", "value": 1},
        {"op": "add", "path": "/b", "value": 2},
    ]


def test_non_empty_to_empty_object():
    """get / empty structures / handles non-empty object to empty object"""
    patch = json_patch.get({"a": 1, "b": 2}, {})
    assert patch == [{"op": "remove", "path": "/a"}, {"op": "remove", "path": "/b"}]
    _applies(patch, {"a": 1, "b": 2}, {})


def test_structurally_equal_and_same():
    """get / reference equality optimization / returns empty patch for structurally equal objects and same references"""  # noqa: E501
    value1: JsonValue = {"a": 1}
    value2: JsonValue = {"a": 1}
    patch = json_patch.get(value1, value2)
    assert patch == []
    _applies(patch, value1, value2)
    assert json_patch.get(value1, value1) == []


def test_structurally_equal_different():
    """get / reference equality optimization / returns empty patch for structurally equal but different objects"""  # noqa: E501
    assert json_patch.get({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {"c": 2}}) == []


def test_structurally_different():
    """get / reference equality optimization / emits the property replace for structurally different objects"""  # noqa: E501
    patch = json_patch.get({"a": 1}, {"a": 2})
    assert len(patch) > 0
    _applies(patch, {"a": 1}, {"a": 2})


def test_same_array_reference():
    """get / reference equality optimization / returns empty patch for same array reference"""
    array: JsonValue = [1, 2, 3]
    assert json_patch.get(array, array) == []


def test_same_object_reference():
    """get / reference equality optimization / returns empty patch for same object reference"""
    obj: JsonValue = {"a": 1, "b": 2}
    assert json_patch.get(obj, obj) == []


def test_single_element_arrays():
    """get / edge cases / handles single-element arrays"""
    assert json_patch.get([1], [2]) == [{"op": "replace", "path": "/0", "value": 2}]
    assert json_patch.get([1], []) == [{"op": "remove", "path": "/0"}]
    assert json_patch.get([], [1]) == [{"op": "add", "path": "/0", "value": 1}]


def test_single_property_objects():
    """get / edge cases / handles single-property objects"""
    assert json_patch.get({"a": 1}, {"a": 2}) == [{"op": "replace", "path": "/a", "value": 2}]
    assert json_patch.get({"a": 1}, {}) == [{"op": "remove", "path": "/a"}]
    assert json_patch.get({}, {"a": 1}) == [{"op": "add", "path": "/a", "value": 1}]


def test_array_index_zero():
    """get / edge cases / handles array index 0 operations"""
    assert json_patch.get([1, 2, 3], [0, 2, 3]) == [{"op": "replace", "path": "/0", "value": 0}]
    patch = json_patch.get([1, 2, 3], [2, 3])
    _applies(patch, [1, 2, 3], [2, 3])
    assert patch == [
        {"op": "replace", "path": "/0", "value": 2},
        {"op": "replace", "path": "/1", "value": 3},
        {"op": "remove", "path": "/2"},
    ]


def test_last_array_index():
    """get / edge cases / handles operations at last array index"""
    assert json_patch.get([1, 2, 3], [1, 2, 4]) == [{"op": "replace", "path": "/2", "value": 4}]
    assert json_patch.get([1, 2, 3], [1, 2]) == [{"op": "remove", "path": "/2"}]


def test_deeply_nested():
    """get / deep nesting / handles deeply nested structures"""
    old: JsonValue = {"level1": {"level2": {"level3": {"level4": {"level5": {"value": "old"}}}}}}
    new: JsonValue = {
        "level1": {"level2": {"level3": {"level4": {"level5": {"value": "new", "extra": "added"}}}}}
    }
    _applies(json_patch.get(old, new), old, new)


def test_nested_arrays_in_objects():
    """get / deep nesting / handles nested arrays within objects"""
    old: JsonValue = {"items": [[1, 2], [3, 4]]}
    new: JsonValue = {"items": [[1, 2], [3, 5], [6, 7]]}
    _applies(json_patch.get(old, new), old, new)


def test_after_root_replace():
    """apply / happy paths / applies operations after a root replace"""
    patch: JsonPatch = [
        {"op": "replace", "path": "", "value": {}},
        {"op": "add", "path": "/a", "value": 1},
    ]
    assert json_patch.apply(patch, {"old": True}) == {"a": 1}


def test_replace():
    """apply / happy paths / replace"""
    assert json_patch.apply([{"op": "replace", "path": "", "value": 42}], 1) == 42
    assert json_patch.apply([{"op": "replace", "path": "/a", "value": 2}], {"a": 1}) == {"a": 2}
    assert json_patch.apply([{"op": "replace", "path": "/1", "value": 20}], [1, 2, 3]) == [1, 20, 3]
    assert json_patch.apply([{"op": "replace", "path": "/a/b", "value": 2}], {"a": {"b": 1}}) == {
        "a": {"b": 2}
    }


def test_add():
    """apply / happy paths / add"""
    assert json_patch.apply([{"op": "add", "path": "/b", "value": 2}], {"a": 1}) == {"a": 1, "b": 2}
    assert json_patch.apply([{"op": "add", "path": "/1", "value": 10}], [1, 2, 3]) == [1, 10, 2, 3]
    assert json_patch.apply([{"op": "add", "path": "/-", "value": 4}], [1, 2, 3]) == [1, 2, 3, 4]
    assert json_patch.apply(
        [{"op": "add", "path": "/users/0/tags/-", "value": "admin"}],
        {"users": [{"id": 1, "tags": []}]},
    ) == {"users": [{"id": 1, "tags": ["admin"]}]}


def test_add_to_tuple():
    """apply / happy paths / add (a tuple is an array)"""
    assert json_patch.apply([{"op": "add", "path": "/1", "value": 10}], (1, 2)) == [1, 10, 2]


def test_remove():
    """apply / happy paths / remove"""
    assert json_patch.apply([{"op": "remove", "path": "/a"}], {"a": 1, "b": 2}) == {"b": 2}
    assert json_patch.apply([{"op": "remove", "path": "/1"}], [1, 2, 3]) == [1, 3]
    assert json_patch.apply([{"op": "remove", "path": "/a/b"}], {"a": {"b": 1, "c": 2}}) == {
        "a": {"c": 2}
    }


def test_sequence():
    """apply / happy paths / applies multiple operations in sequence"""
    patch: JsonPatch = [
        {"op": "add", "path": "/c", "value": 3},
        {"op": "replace", "path": "/a", "value": 10},
        {"op": "remove", "path": "/b"},
    ]
    assert json_patch.apply(patch, {"a": 1, "b": 2}) == {"a": 10, "c": 3}


def test_decodes_pointer():
    """apply / JSON Pointer decoding / decodes '~1' as '/' and '~0' as '~'"""
    assert json_patch.apply([{"op": "replace", "path": "/a~1b", "value": 2}], {"a/b": 1}) == {
        "a/b": 2
    }
    assert json_patch.apply([{"op": "add", "path": "/a~0b", "value": 1}], {}) == {"a~b": 1}
    assert json_patch.apply([{"op": "add", "path": "/path~1to~0key", "value": "value"}], {}) == {
        "path/to~key": "value"
    }


def test_decodes_tilde_zero_one():
    """apply / JSON Pointer decoding / decodes '~01' as a literal '~1' (unescape order)"""
    assert json_patch.apply([{"op": "add", "path": "/a~01b", "value": 1}], {}) == {"a~1b": 1}


def test_literal_tilde_one_token():
    """apply / JSON Pointer decoding / addresses a literal key '~1' via token '~01'"""
    assert json_patch.apply([{"op": "add", "path": "/~01", "value": 0}], {}) == {"~1": 0}


def test_rejects_relative_pointer():
    """apply / errors / rejects non-empty pointers that do not start with '/'"""
    _expect_message([{"op": "add", "path": "invalid", "value": 1}], {}, 'must start with "/"')


def test_rejects_invalid_indices():
    """apply / errors / rejects invalid array indices"""
    _expect_message([{"op": "add", "path": "/abc", "value": 1}], [], "Invalid array index")
    _expect_message(
        [{"op": "replace", "path": "/-1", "value": 1}], [1, 2, 3], "Invalid array index"
    )
    _expect_message(
        [{"op": "add", "path": "/items/abc/value", "value": 1}],
        {"items": []},
        'Invalid array index: "abc"',
    )


def test_rejects_out_of_bounds():
    """apply / errors / rejects out-of-bounds array access"""
    out_of_bounds = "Array index out of bounds"
    _expect_message([{"op": "replace", "path": "/10", "value": 1}], [1, 2, 3], out_of_bounds)
    _expect_message([{"op": "add", "path": "/10", "value": 1}], [1, 2, 3], out_of_bounds)
    _expect_message([{"op": "remove", "path": "/10"}], [1, 2, 3], out_of_bounds)


def test_rejects_dash():
    """apply / errors / rejects '-' for replace/remove"""
    _expect_message(
        [{"op": "replace", "path": "/-", "value": 1}], [1, 2, 3], '"-" is not valid for replace'
    )
    _expect_message([{"op": "remove", "path": "/-"}], [1, 2, 3], '"-" is not valid for remove')


def test_rejects_missing_members():
    """apply / errors / rejects replace/remove of non-existent object members"""
    _expect_message(
        [{"op": "replace", "path": "/nonexistent", "value": 1}], {"a": 1}, "does not exist"
    )
    _expect_message([{"op": "remove", "path": "/nonexistent"}], {"a": 1}, "does not exist")


def test_rejects_missing_parent():
    """apply / errors / rejects add/replace when the parent is missing or not a container"""
    _expect_message([{"op": "add", "path": "/a/b", "value": 1}], {"a": None}, "Cannot add at")
    _expect_message([{"op": "add", "path": "/a/b", "value": 1}], {}, "Cannot add at")
    _expect_message([{"op": "add", "path": "/a/b", "value": 1}], {"a": "string"}, "not a container")
    _expect_message([{"op": "replace", "path": "/a/b", "value": 1}], {"a": 42}, "not a container")
    _expect_message(
        [{"op": "add", "path": "/a/b/c", "value": 1}], {"a": {"b": "not-object"}}, "not a container"
    )


def test_rejects_unresolvable_parent():
    """apply / errors / rejects operations when a nested parent cannot be resolved"""
    cases: list[tuple[JsonPatchOperation, JsonValue]] = [
        ({"op": "add", "path": "/a/b/c", "value": 1}, {"a": None}),
        ({"op": "add", "path": "/a/0/b", "value": 1}, {"a": []}),
        ({"op": "replace", "path": "/a/b", "value": 1}, {}),
        ({"op": "remove", "path": "/a/b"}, {}),
        ({"op": "remove", "path": "/a/b/c"}, {"a": "not-object"}),
    ]
    for operation, doc in cases:
        _expect_message([operation], doc, f"Cannot {operation['op']} at")


def test_rejects_root_remove():
    """apply / errors / rejects remove at the root"""
    _expect_message([{"op": "remove", "path": ""}], {"a": 1}, "root")


def test_apply_does_not_mutate():
    """apply / immutability / does not mutate input document"""
    original: JsonValue = {"a": 1, "b": [2, 3]}
    json_patch.apply([{"op": "replace", "path": "/a", "value": 10}], original)
    assert original == {"a": 1, "b": [2, 3]}
    array: JsonValue = [1, 2, 3]
    json_patch.apply([{"op": "add", "path": "/1", "value": 99}], array)
    assert array == [1, 2, 3]


def test_does_not_mutate_patch():
    """apply / immutability / does not mutate patch array"""
    patch: list[JsonPatchOperation] = [{"op": "add", "path": "/b", "value": 2}]
    json_patch.apply(patch, {"a": 1})
    assert patch == [{"op": "add", "path": "/b", "value": 2}]


def test_preserves_references():
    """apply / immutability / preserves references outside the modified path"""
    unchanged: JsonValue = {"value": 1}
    original: JsonValue = {"changed": {"value": 1}, "unchanged": unchanged}
    result = json_patch.apply([{"op": "replace", "path": "/changed/value", "value": 2}], original)
    assert isinstance(result, dict)
    assert result["unchanged"] is unchanged
    assert original == {"changed": {"value": 1}, "unchanged": {"value": 1}}


def test_proto_as_data_property():
    """apply / immutability / handles '__proto__' as an own data property"""
    original: JsonValue = {"nested": {"__proto__": {"value": 1}}}
    result = json_patch.apply(
        [
            {"op": "replace", "path": "/nested/__proto__/value", "value": 2},
            {"op": "add", "path": "/__proto__", "value": {"value": 3}},
        ],
        original,
    )
    assert result == {"nested": {"__proto__": {"value": 2}}, "__proto__": {"value": 3}}
    assert original == {"nested": {"__proto__": {"value": 1}}}


def test_empty_patch_reference():
    """apply / empty patch optimization / returns original reference for empty patch"""
    doc: JsonValue = {"a": 1, "b": 2}
    assert json_patch.apply([], doc) is doc


def test_empty_patch_array_reference():
    """apply / empty patch optimization / returns original reference for empty patch with arrays"""
    array: JsonValue = [1, 2, 3]
    assert json_patch.apply([], array) is array


def test_empty_patch_primitives():
    """apply / empty patch optimization / returns original reference for empty patch with primitives"""  # noqa: E501
    for value in cast("list[JsonValue]", [1, "hello", True, None]):
        assert json_patch.apply([], value) is value


def test_paths_created_earlier():
    """apply / sequential path dependencies / applies operations on paths created by earlier operations"""  # noqa: E501
    result = json_patch.apply(
        [
            {"op": "add", "path": "/new", "value": {}},
            {"op": "add", "path": "/new/nested", "value": {"value": 1}},
            {"op": "replace", "path": "/new/nested/value", "value": 2},
        ],
        {},
    )
    assert result == {"new": {"nested": {"value": 2}}}


def test_array_paths_created_earlier():
    """apply / sequential path dependencies / applies operations on array paths created by earlier operations"""  # noqa: E501
    result = json_patch.apply(
        [
            {"op": "add", "path": "/items", "value": []},
            {"op": "add", "path": "/items/-", "value": 1},
            {"op": "add", "path": "/items/-", "value": 2},
            {"op": "replace", "path": "/items/0", "value": 10},
        ],
        {},
    )
    assert result == {"items": [10, 2]}


def test_same_path_many_times():
    """apply / sequential path dependencies / applies multiple operations on same path"""
    result = json_patch.apply(
        [
            {"op": "add", "path": "/counter", "value": 0},
            {"op": "replace", "path": "/counter", "value": 1},
            {"op": "replace", "path": "/counter", "value": 2},
        ],
        {},
    )
    assert result == {"counter": 2}


def test_remove_then_add():
    """apply / sequential path dependencies / applies remove then add on same path"""
    result = json_patch.apply(
        [{"op": "remove", "path": "/a"}, {"op": "add", "path": "/a", "value": "new"}],
        {"a": "old", "b": 2},
    )
    assert result == {"a": "new", "b": 2}


def test_on_empty_arrays():
    """apply / edge cases / handles operations on empty arrays"""
    assert json_patch.apply([{"op": "add", "path": "/-", "value": 1}], []) == [1]
    assert json_patch.apply([{"op": "add", "path": "/0", "value": 1}], []) == [1]


def test_on_empty_objects():
    """apply / edge cases / handles operations on empty objects"""
    assert json_patch.apply([{"op": "add", "path": "/key", "value": "value"}], {}) == {
        "key": "value"
    }


def test_array_ops_index_zero():
    """apply / edge cases / handles array operations at index 0"""
    assert json_patch.apply([{"op": "replace", "path": "/0", "value": 10}], [1, 2, 3]) == [10, 2, 3]
    assert json_patch.apply([{"op": "remove", "path": "/0"}], [1, 2, 3]) == [2, 3]
    assert json_patch.apply([{"op": "add", "path": "/0", "value": 0}], [1, 2, 3]) == [0, 1, 2, 3]


def test_array_ops_last_index():
    """apply / edge cases / handles array operations at last index"""
    array: JsonValue = [1, 2, 3]
    assert json_patch.apply([{"op": "replace", "path": "/2", "value": 30}], array) == [1, 2, 30]
    assert json_patch.apply([{"op": "remove", "path": "/2"}], array) == [1, 2]


def test_single_element_array_ops():
    """apply / edge cases / handles single-element array operations"""
    assert json_patch.apply([{"op": "replace", "path": "/0", "value": 2}], [1]) == [2]
    assert json_patch.apply([{"op": "remove", "path": "/0"}], [1]) == []
    assert json_patch.apply([{"op": "add", "path": "/0", "value": 0}], [1]) == [0, 1]


def test_single_property_object_ops():
    """apply / edge cases / handles single-property object operations"""
    assert json_patch.apply([{"op": "replace", "path": "/a", "value": 2}], {"a": 1}) == {"a": 2}
    assert json_patch.apply([{"op": "remove", "path": "/a"}], {"a": 1}) == {}


def test_root_add():
    """apply / root operations / applies root add"""
    assert json_patch.apply(
        [{"op": "add", "path": "", "value": {"replacement": True}}], {"old": True}
    ) == {"replacement": True}


def test_root_replace_then_nested():
    """apply / root operations / applies root replace followed by nested operations"""
    result = json_patch.apply(
        [
            {"op": "replace", "path": "", "value": {}},
            {"op": "add", "path": "/a", "value": 1},
            {"op": "add", "path": "/b", "value": 2},
        ],
        {"old": "data"},
    )
    assert result == {"a": 1, "b": 2}


def test_root_replace_types():
    """apply / root operations / applies root replace to different types"""
    assert json_patch.apply([{"op": "replace", "path": "", "value": []}], {"a": 1}) == []
    assert json_patch.apply([{"op": "replace", "path": "", "value": "string"}], 42) == "string"
    assert json_patch.apply([{"op": "replace", "path": "", "value": None}], True) is None


_ROUND_TRIP_CASES: list[tuple[JsonValue, JsonValue]] = [
    (
        {
            "users": [
                {"id": 1, "name": "Alice", "active": True},
                {"id": 2, "name": "Bob", "active": False},
            ],
            "metadata": {"version": 1, "tags": ["v1"]},
        },
        {
            "users": [
                {"id": 1, "name": "Alice Updated", "active": True},
                {"id": 3, "name": "Charlie", "active": True},
            ],
            "metadata": {"version": 2, "tags": ["v2", "latest"]},
        },
    ),
    ([1, 2, 3, 4, 5], [1, 20, 3, 40, 50, 60]),
    ({"a": 1, "b": 2, "c": 3}, {"a": 10, "d": 4, "e": 5}),
    (
        {"level1": {"level2": {"level3": {"value": "old"}}}},
        {"level1": {"level2": {"level3": {"value": "new", "extra": "added"}}}},
    ),
]


def _round_trip(cases: list[tuple[JsonValue, JsonValue]]) -> None:
    for old, new in cases:
        _applies(json_patch.get(old, new), old, new)


def test_round_trip():
    """round-trip / apply(get(old, new), old) === new"""
    _round_trip(_ROUND_TRIP_CASES)


def test_round_trip_empty():
    """round-trip / round-trip with empty structures"""
    _round_trip([([], [1, 2, 3]), ([1, 2, 3], []), ({}, {"a": 1, "b": 2}), ({"a": 1, "b": 2}, {})])


def test_round_trip_nested():
    """round-trip / round-trip with nested arrays and objects"""
    old: JsonValue = {
        "matrix": [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
        "config": {"settings": {"nested": {"deep": {"value": "old"}}}},
    }
    new: JsonValue = {
        "matrix": [[1, 2, 3], [4, 50, 6], [7, 8, 9], [10, 11, 12]],
        "config": {"settings": {"nested": {"deep": {"value": "new", "extra": "field"}}}},
    }
    _round_trip([(old, new)])


def test_round_trip_complex_arrays():
    """round-trip / round-trip with complex array operations"""
    _round_trip([([0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [10, 1, 20, 3, 40, 50, 6, 70, 8])])


def test_round_trip_escaped_keys():
    """round-trip / round-trip with escaped keys"""
    old: JsonValue = {"key/with/slash": 1, "key~with~tilde": 2, "normal": 3}
    new: JsonValue = {"key/with/slash": 10, "key~with~tilde": 20, "normal": 30, "new/key": 40}
    _round_trip([(old, new)])


def test_round_trip_type_changes():
    """round-trip / round-trip with type changes"""
    _round_trip([(1, "string"), ("string", 42), (True, None), (None, []), ([], {}), ({}, [])])


def test_round_trip_identical():
    """round-trip / round-trip preserves identical values (empty patch)"""
    values = cast(
        "list[JsonValue]",
        [
            {"a": 1, "b": 2},
            [1, 2, 3],
            "string",
            42,
            True,
            None,
            {"nested": {"deep": {"value": "test"}}},
        ],
    )
    for value in [*values, [[1, 2], [3, 4]]]:
        patch = json_patch.get(value, value)
        assert patch == []
        assert json_patch.apply(patch, value) == value


def test_booleans_are_not_numbers():
    """get / root values / emits a root replace for primitive changes (True is not 1)"""
    assert json_patch.get(1, True) == [{"op": "replace", "path": "", "value": True}]
    assert json_patch.get(1, 1.0) == []
