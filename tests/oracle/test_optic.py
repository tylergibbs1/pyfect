"""Ports of Effect's ``Optic.test.ts``. Each test's docstring is the Effect
test title, prefixed by its ``describe`` blocks.

Python mappings: ``Optic.id<S>()`` is ``optic.Id[S]()``; ``undefined`` is
``None`` (a missing key or index reads as ``None``); records are dicts,
tuples and arrays are tuples and lists; ``Option.none()`` is ``None``;
``Result.succeed`` / ``fail`` are ``Ok`` / ``Err``. ``notUndefined`` is
``not_none``; ``pick`` / ``omit`` take their keys as arguments.

Omitted:
- "replace should throw an error if the object has a non-Object
  constructor or null prototype": its first half is ported as "replace
  raises for a value it cannot copy"; Python objects have no null
  prototype.
- "preserves __proto__ as an own property": JavaScript prototypes.
- "standalone functions / supports data-first usage" and "supports
  data-last usage": the operations are methods (``lens.get(s)``,
  ``optional.get_result(s)``, ...), pyfect's rule for combinators that
  remove nothing from a type; ``get_all`` is a method too.
- "optionalKey / Tuple / string index": indexes are ``int``s.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict, TypeIs

import pytest

from pyfect import optic
from pyfect import schema as S
from pyfect.result import Err, Ok, Result
from pyfect.schema.issue import Composite, InvalidValue, Issue, MissingKey, Pointer, format_issue


def add_one(n: int) -> int:
    return n + 1


def increment(n: int | None) -> int | None:
    return None if n is None else n + 1


def failure_of(result: Result[object, Issue]) -> Issue:
    assert isinstance(result, Err)
    return result.error


def assert_failure_message(result: Result[object, Issue], message: str) -> None:
    assert format_issue(failure_of(result)) == message


def assert_missing_key(result: Result[object, Issue], key: object) -> None:
    issue = failure_of(result)
    assert isinstance(issue, Pointer)
    assert issue.path == (key,)
    assert isinstance(issue.issue, MissingKey)


def test_replace_raises_for_a_value_it_cannot_copy():
    """replace should throw an error if the object has a non-Object
    constructor or null prototype (Python: a plain class instance)"""

    class A:
        def __init__(self, x: int) -> None:
            self.x = x

    lens = optic.Id[A]().key("x")
    with pytest.raises(TypeError, match="Cannot copy a A"):
        lens.replace(2, A(1))


def test_replace_copies_a_dataclass():
    """(Python) dataclasses are copied with ``copy.replace``"""

    @dataclass(frozen=True)
    class Point:
        x: int
        y: int

    lens = optic.Id[Point]().key("x")
    assert lens.get(Point(1, 2)) == 1
    assert lens.replace(3, Point(1, 2)) == Point(3, 2)


def test_id():
    """id"""
    iso = optic.Id[int]()
    assert iso.get(1) == 1
    assert iso.set(1) == 1
    assert iso.modify(add_one)(1) == 2


class Value(TypedDict):
    value: int


def _value_of(s: Value) -> int:
    return s["value"]


def _value(n: int) -> Value:
    return {"value": n}


def test_compose_sets_through_composed_isos_without_reading_a_source():
    """compose / sets through composed isos without reading a source"""
    value = optic.make_iso(_value_of, _value)
    text = optic.make_iso(str, int)
    composed = value.compose(text)
    assert composed.set("2") == {"value": 2}
    assert composed.replace("2", {"value": 1}) == {"value": 2}


def test_compose_sets_through_composed_prisms_without_reading_a_source():
    """compose / sets through composed prisms without reading a source"""

    def get_value(s: Value) -> Result[int, Issue]:
        return Ok(s["value"])

    def get_text(n: int) -> Result[str, Issue]:
        return Ok(str(n))

    value = optic.make_prism(get_value, _value)
    text = optic.make_prism(get_text, int)
    assert value.compose(text).set("2") == {"value": 2}


def _same(n: int) -> int:
    return n


def _ok(n: int) -> Result[int, Issue]:
    return Ok(n)


def _replace_ok(n: int, _: int) -> Result[int, Issue]:
    return Ok(n)


def test_compose_preserves_capabilities_and_behavior_across_every_optic_kind():
    """compose / preserves capabilities and behavior across every optic kind"""
    optics: dict[str, optic.Optional[int, int]] = {
        "Iso": optic.make_iso(_same, _same),
        "Lens": optic.make_lens(_same, lambda n, _: n),
        "Prism": optic.make_prism(_ok, _same),
        "Optional": optic.make_optional(_ok, _replace_ok),
    }
    expected = {
        "Iso": {"Iso": "Iso", "Lens": "Lens", "Prism": "Prism", "Optional": "Optional"},
        "Lens": {"Iso": "Lens", "Lens": "Lens", "Prism": "Optional", "Optional": "Optional"},
        "Prism": {"Iso": "Prism", "Lens": "Optional", "Prism": "Prism", "Optional": "Optional"},
        "Optional": {
            "Iso": "Optional",
            "Lens": "Optional",
            "Prism": "Optional",
            "Optional": "Optional",
        },
    }
    for left, a in optics.items():
        for right, b in optics.items():
            composed: Any = a.compose(b)
            kind = expected[left][right]
            assert hasattr(composed, "get") == (kind in ("Iso", "Lens"))
            assert hasattr(composed, "set") == (kind in ("Iso", "Prism"))
            assert composed.get_result(1) == Ok(1)
            assert composed.replace_result(2, 1) == Ok(2)


def test_compose_preserves_optional_setter_failures():
    """compose / preserves optional setter failures"""
    issue = InvalidValue({"message": "cannot replace"})

    def fail(_: int, __: int) -> Result[int, Issue]:
        return Err(issue)

    composed = optic.make_optional(_ok, fail).compose(optic.make_iso(_same, _same))
    assert failure_of(composed.replace_result(2, 1)) is issue
    assert composed.replace(2, 1) == 1
    assert composed.modify(add_one)(1) == 1


def test_compose_composes_identity_in_both_directions():
    """compose / composes identity in both directions"""
    value = optic.make_iso(str, int)
    left = optic.Id[int]().compose(value)
    right = value.compose(optic.Id[str]())
    identity = optic.Id[int]().compose(optic.Id[int]())
    assert left.get(1) == "1"
    assert right.get(1) == "1"
    assert left.set("2") == 2
    assert right.set("2") == 2
    assert identity.get(1) == 1
    assert identity.set(2) == 2


def _chars(s: str) -> list[str]:
    return list(s)


def _join(chars: list[str]) -> str:
    return "".join(chars)


def test_compose_is_independent_of_composition_grouping():
    """compose / is independent of composition grouping"""
    wrapped = optic.make_iso(_value_of, _value)
    text = optic.make_iso(str, int)
    chars = optic.make_iso(_chars, _join)
    left = wrapped.compose(text).compose(chars)
    right = wrapped.compose(text.compose(chars))
    assert left.get({"value": 12}) == ["1", "2"]
    assert right.get({"value": 12}) == ["1", "2"]
    assert left.set(["3", "4"]) == {"value": 34}
    assert right.set(["3", "4"]) == {"value": 34}


class A(TypedDict):
    a: int


def test_key_struct_required_key():
    """key / Struct / required key"""
    lens = optic.Id[A]().key("a")
    assert lens.get({"a": 1}) == 1
    assert lens.replace(2, {"a": 1}) == {"a": 2}
    assert lens.modify(add_one)({"a": 1}) == {"a": 2}


class Nested(TypedDict):
    a: A


def test_key_struct_nested_required_keys():
    """key / Struct / nested required keys"""
    lens = optic.Id[Nested]().key("a").key("a")
    assert lens.get({"a": {"a": 1}}) == 1
    assert lens.replace(2, {"a": {"a": 1}}) == {"a": {"a": 2}}
    assert lens.modify(add_one)({"a": {"a": 1}}) == {"a": {"a": 2}}


class OptionalA(TypedDict):
    a: NotRequired[int | None]


def test_key_struct_optional_key_with_undefined():
    """key / Struct / optional key (with undefined)"""
    lens = optic.Id[OptionalA]().key("a")
    assert lens.get({"a": 1}) == 1
    assert lens.get({}) is None
    assert lens.get({"a": None}) is None
    assert lens.replace(2, {"a": 1}) == {"a": 2}
    assert lens.replace(2, {}) == {"a": 2}
    assert lens.replace(2, {"a": None}) == {"a": 2}
    assert lens.replace(None, {"a": 1}) == {"a": None}
    assert lens.replace(None, {}) == {"a": None}
    assert lens.modify(increment)({"a": 1}) == {"a": 2}
    assert lens.modify(increment)({}) == {"a": None}
    assert lens.modify(increment)({"a": None}) == {"a": None}


def test_key_tuple_required_element():
    """key / Tuple / required element"""
    lens = optic.Id[tuple[int]]().key(0)
    assert lens.get((1,)) == 1
    assert lens.replace(2, (1,)) == (2,)
    assert lens.modify(add_one)((1,)) == (2,)


def test_key_tuple_nested_required_element():
    """key / Tuple / nested required element"""
    lens = optic.Id[tuple[str, tuple[int]]]().key(1).key(0)
    assert lens.get(("a", (1,))) == 1
    assert lens.replace(2, ("a", (1,))) == ("a", (2,))
    assert lens.modify(add_one)(("a", (1,))) == ("a", (2,))


def test_key_tuple_optional_element_with_undefined():
    """key / Tuple / optional element (with undefined)"""
    lens = optic.Id[tuple[int, ...]]().key(1)
    assert lens.get((1, 2)) == 2
    assert lens.get((1,)) is None
    assert lens.get((1, None)) is None  # pyright: ignore[reportArgumentType]
    assert lens.replace(2, (1, 2)) == (1, 2)
    assert lens.replace(2, (1,)) == (1, 2)
    assert lens.replace(None, (1, 2)) == (1, None)
    assert lens.replace(None, (1,)) == (1, None)
    assert lens.modify(increment)((1, 2)) == (1, 3)
    assert lens.modify(increment)((1,)) == (1, None)


class Mixed(TypedDict):
    a: tuple[int]


def test_key_mixed_structs_and_tuples():
    """key / Mixed structs and tuples"""
    lens = optic.Id[Mixed]().key("a").key(0)
    assert lens.get({"a": (1,)}) == 1
    assert lens.replace(2, {"a": (1,)}) == {"a": (2,)}
    assert lens.modify(add_one)({"a": (1,)}) == {"a": (2,)}


class ExactOptional(TypedDict):
    a: NotRequired[int]


def test_optional_key_struct_exact_optional_key_without_undefined():
    """optionalKey / Struct / exact optional key (without undefined)"""
    lens = optic.Id[ExactOptional]().optional_key("a")
    assert lens.get({"a": 1}) == 1
    assert lens.get({}) is None
    assert lens.replace(2, {"a": 1}) == {"a": 2}
    assert lens.replace(2, {}) == {"a": 2}
    assert lens.replace(None, {"a": 1}) == {}
    assert lens.replace(None, {}) == {}
    assert lens.modify(increment)({"a": 1}) == {"a": 2}
    assert lens.modify(increment)({}) == {}


def test_optional_key_record():
    """optionalKey / Record"""
    lens = optic.Id[dict[str, int]]().optional_key("a")
    assert lens.get({"a": 1, "b": 2}) == 1
    assert lens.get({"b": 2}) is None
    assert lens.replace(2, {"a": 1, "b": 2}) == {"a": 2, "b": 2}
    assert lens.replace(2, {"b": 2}) == {"a": 2, "b": 2}
    assert lens.replace(None, {"a": 1}) == {}
    assert lens.replace(None, {"b": 2}) == {"b": 2}
    assert lens.modify(increment)({"a": 1}) == {"a": 2}
    assert lens.modify(increment)({"b": 2}) == {"b": 2}


def test_optional_key_tuple_exact_optional_element_without_undefined():
    """optionalKey / Tuple / exact optional element (without undefined)"""
    lens = optic.Id[tuple[int, ...]]().optional_key(1)
    assert lens.get((1, 2)) == 2
    assert lens.get((1,)) is None
    assert lens.replace(3, (1, 2)) == (1, 3)
    assert lens.replace(3, (1,)) == (1, 3)
    assert lens.replace(None, (1, 2)) == (1,)
    assert lens.replace(None, (1,)) == (1,)
    assert lens.modify(increment)((1, 2)) == (1, 3)
    assert lens.modify(increment)((1,)) == (1,)


def test_optional_key_array():
    """optionalKey / Array"""
    lens = optic.Id[list[int]]().optional_key(1)
    assert lens.get([1, 2, 3]) == 2
    assert lens.get([1]) is None
    assert lens.replace(4, [1, 2, 3]) == [1, 4, 3]
    assert lens.replace(4, [1]) == [1, 4]
    assert lens.replace(None, [1, 2]) == [1]
    assert lens.replace(None, [1, 2, 3]) == [1, 3]
    assert lens.replace(None, [1]) == [1]
    assert lens.modify(increment)([1, 2]) == [1, 3]
    assert lens.modify(increment)([1, 2, 4]) == [1, 3, 4]
    assert lens.modify(increment)([1]) == [1]


def test_check_single_check():
    """check / single check"""
    prism = optic.Id[float]().check(S.is_greater_than(0))
    assert prism.get_result(1) == Ok(1)
    assert_failure_message(prism.get_result(0), "Expected a value greater than 0")
    assert prism.set(1) == 1
    assert prism.set(0) == 0
    assert prism.modify(lambda n: n + 1)(1) == 2
    assert prism.modify(lambda n: n + 1)(0) == 0


def test_check_multiple_checks():
    """check / multiple checks"""
    prism = optic.Id[float]().check(S.is_int(), S.is_greater_than(0))
    assert prism.get_result(1) == Ok(1)
    assert_failure_message(prism.get_result(0), "Expected a value greater than 0")
    assert_failure_message(prism.get_result(1.1), "Expected an integer")
    assert_failure_message(
        prism.get_result(-1.1), "Expected an integer\nExpected a value greater than 0"
    )
    assert prism.modify(lambda n: n + 1)(1) == 2
    assert prism.modify(lambda n: n + 1)(0) == 0
    assert prism.modify(lambda n: n + 1)(1.1) == 1.1
    assert prism.modify(lambda n: n + 1)(-1.1) == -1.1


def test_check_combines_checks_across_successive_calls():
    """check / combines checks across successive calls"""
    prism = optic.Id[float]().check(S.is_int()).check(S.is_greater_than(0))
    assert_failure_message(
        prism.get_result(-1.1), "Expected an integer\nExpected a value greater than 0"
    )


class TagA(TypedDict):
    _tag: Literal["a"]
    a: str


class TagB(TypedDict):
    _tag: Literal["b"]
    b: int


def _is_b(s: TagA | TagB) -> TypeIs[TagB]:
    return s["_tag"] == "b"


def test_refine():
    """refine"""
    focus = optic.Id[TagA | TagB]().refine(_is_b, expected='"b" tag').key("b")
    assert focus.get_result({"_tag": "b", "b": 1}) == Ok(1)
    assert_failure_message(focus.get_result({"_tag": "a", "a": "value"}), 'Expected "b" tag')
    assert focus.modify(add_one)({"_tag": "a", "a": "value"}) == {"_tag": "a", "a": "value"}
    assert focus.modify(add_one)({"_tag": "b", "b": 1}) == {"_tag": "b", "b": 2}


def test_tag():
    """tag"""
    focus = optic.Id[TagA | TagB]().tag("b").key("b")
    assert focus.get_result({"_tag": "b", "b": 1}) == Ok(1)
    assert_failure_message(focus.get_result({"_tag": "a", "a": "value"}), 'Expected "b" tag')
    assert focus.modify(add_one)({"_tag": "a", "a": "value"}) == {"_tag": "a", "a": "value"}
    assert focus.modify(add_one)({"_tag": "b", "b": 1}) == {"_tag": "b", "b": 2}


def test_tag_on_a_tagged_class():
    """(Python) tag reads a tagged class's ``_tag`` attribute"""

    class Circle(S.TaggedClass, tag="Circle"):
        radius: int

    class Square(S.TaggedClass, tag="Square"):
        side: int

    radius = optic.Id[Circle | Square]().tag("Circle").key("radius")
    assert radius.modify(add_one)(Circle(radius=1)) == Circle(radius=2)
    assert radius.modify(add_one)(Square(side=1)) == Square(side=1)


def test_at_record():
    """at / Record"""
    focus = optic.Id[dict[str, int]]().at("a")
    assert focus.get_result({"a": 1, "b": 2}) == Ok(1)
    assert_missing_key(focus.get_result({"b": 2}), "a")
    assert focus.replace_result(2, {"a": 1, "b": 2}) == Ok({"a": 2, "b": 2})
    assert_missing_key(focus.replace_result(2, {"b": 2}), "a")
    assert focus.replace(2, {"a": 1, "b": 2}) == {"a": 2, "b": 2}
    assert focus.replace(2, {"b": 2}) == {"b": 2}


def test_at_array():
    """at / Array"""
    focus = optic.Id[list[int]]().at(0)
    assert focus.get_result([1, 2]) == Ok(1)
    assert_missing_key(focus.get_result([]), 0)
    assert focus.replace_result(3, [1, 2]) == Ok([3, 2])
    assert_missing_key(focus.replace_result(2, []), 0)
    assert focus.replace(3, [1, 2]) == [3, 2]
    assert focus.replace(2, []) == []


def test_key_and_check():
    """key & check"""
    focus = optic.Id[A]().key("a").check(S.is_greater_than(0))
    assert focus.get_result({"a": 1}) == Ok(1)
    assert_failure_message(focus.get_result({"a": 0}), "Expected a value greater than 0")
    assert focus.replace_result(2, {"a": 1}) == Ok({"a": 2})
    assert_failure_message(focus.replace_result(2, {"a": 0}), "Expected a value greater than 0")
    assert focus.replace(2, {"a": 1}) == {"a": 2}
    assert focus.replace(2, {"a": 0}) == {"a": 0}


class ABC(TypedDict):
    a: str
    b: int
    c: bool


class OptionalAB(TypedDict):
    a: NotRequired[str]
    b: int


def test_pick_struct():
    """pick / Struct"""
    lens = optic.Id[ABC]().pick("a", "c")
    assert lens.replace({"a": "a2", "c": False}, {"a": "a", "b": 1, "c": True}) == {
        "a": "a2",
        "b": 1,
        "c": False,
    }


def test_pick_deletes_optional_fields_omitted_from_the_replacement():
    """pick / deletes optional fields omitted from the replacement"""
    lens = optic.Id[OptionalAB]().pick("a")
    assert lens.replace({}, {"a": "a", "b": 1}) == {"b": 1}


def test_omit_struct():
    """omit / Struct"""
    lens = optic.Id[ABC]().omit("b")
    assert lens.replace({"a": "a2", "c": False}, {"a": "a", "b": 1, "c": True}) == {
        "a": "a2",
        "b": 1,
        "c": False,
    }


def test_omit_deletes_optional_fields_omitted_from_the_replacement():
    """omit / deletes optional fields omitted from the replacement"""
    lens = optic.Id[OptionalAB]().omit("b")
    assert lens.replace({}, {"a": "a", "b": 1}) == {"b": 1}


class Post(TypedDict):
    title: str
    likes: int


class User(TypedDict):
    posts: list[Post]


class State(TypedDict):
    user: User


def _likes(post: optic.Iso[Post, Post]) -> optic.Optional[Post, int]:
    return post.key("likes").check(S.is_greater_than(0))


_STATE: State = {
    "user": {
        "posts": [
            {"title": "a", "likes": 0},
            {"title": "b", "likes": 1},
            {"title": "c", "likes": 0},
        ]
    }
}
_LIKED: State = {
    "user": {
        "posts": [
            {"title": "a", "likes": 0},
            {"title": "b", "likes": 2},
            {"title": "c", "likes": 0},
        ]
    }
}


def _posts() -> optic.Lens[State, list[Post]]:
    return optic.Id[State]().key("user").key("posts")


def test_for_each_array():
    """forEach / Array"""
    likes = _posts().for_each(_likes)
    add_like = likes.modify(lambda found: [n + 1 for n in found])
    assert add_like(_STATE) == _LIKED


def _positive_value(
    entry: optic.Iso[tuple[str, int], tuple[str, int]],
) -> optic.Optional[tuple[str, int], int]:
    return entry.key(1).check(S.is_greater_than(0))


def test_for_each_record():
    """forEach / Record"""
    focus = optic.Id[dict[str, int]]().compose(optic.entries()).for_each(_positive_value)
    modify = focus.modify(lambda values: tuple(v + 1 for v in values))
    assert modify({"a": 0, "b": 1, "c": 0}) == {"a": 0, "b": 2, "c": 0}


def _element(item: optic.Iso[int, int]) -> optic.Iso[int, int]:
    return item


def test_for_each_fails_when_the_replacement_count_does_not_match():
    """forEach / fails when the replacement count does not match"""
    focus = optic.Id[list[int]]().for_each(_element)
    assert_failure_message(
        focus.replace_result([2], [1, 2]), "each: replacement length mismatch: 1 !== 2"
    )


def test_for_each_fails_when_an_inner_setter_fails():
    """forEach / fails when an inner setter fails"""
    issue = InvalidValue({"message": "cannot replace"})

    def fail(_: int, __: int) -> Result[int, Issue]:
        return Err(issue)

    focus = optic.Id[list[int]]().for_each(lambda _: optic.make_optional(_ok, fail))
    failed = failure_of(focus.replace_result([2], [1]))
    assert isinstance(failed, Pointer)
    assert failed.path == (0,)
    assert failed.issue is issue


def test_modify_all_array():
    """modifyAll / Array"""
    likes = _posts().for_each(_likes)
    assert likes.modify_all(add_one)(_STATE) == _LIKED


def test_modify_all_record():
    """modifyAll / Record"""
    focus = optic.Id[dict[str, int]]().compose(optic.entries()).for_each(_positive_value)
    assert focus.modify_all(add_one)({"a": 0, "b": 1, "c": 0}) == {"a": 0, "b": 2, "c": 0}


class Values(TypedDict):
    values: NotRequired[tuple[int, ...]]


def test_modify_all_returns_the_original_source_when_the_traversal_fails():
    """modifyAll / returns the original source when the traversal fails"""
    issue = InvalidValue({"message": "missing values"})

    def get(s: Values) -> Result[tuple[int, ...], Issue]:
        return Ok(s["values"]) if "values" in s else Err(issue)

    def replace(values: tuple[int, ...], s: Values) -> Result[Values, Issue]:
        return Ok(Values(values=values)) if "values" in s else Err(issue)

    traversal = optic.make_optional(get, replace)
    source: Values = {}
    assert traversal.modify_all(add_one)(source) is source


def test_not_undefined():
    """notUndefined"""
    prism = optic.Id[int | None]().not_none()
    assert prism.get_result(1) == Ok(1)
    assert_failure_message(prism.get_result(None), "Expected a value other than `None`")
    assert prism.replace(2, None) == 2
    assert prism.replace(2, 1) == 2


class Numbers(TypedDict):
    a: list[int]


def _positive(a: optic.Iso[int, int]) -> optic.Prism[int, int]:
    return a.check(S.is_greater_than(0))


def test_get_all():
    """getAll"""
    numbers: optic.Lens[Numbers, list[int]] = optic.Id[Numbers]().key("a")
    traversal = numbers.for_each(_positive)
    assert traversal.get_all({"a": [1, 2, 3]}) == [1, 2, 3]
    assert traversal.get_all({"a": [1, -2, 3]}) == [1, 3]


def test_get_all_returns_an_empty_array_when_the_traversal_fails():
    """getAll returns an empty array when the traversal fails"""
    focus_issue = InvalidValue({"message": "cannot focus"})
    replace_issue = InvalidValue({"message": "cannot replace"})

    def get(_: int) -> Result[tuple[int, ...], Issue]:
        return Err(focus_issue)

    def replace(_: tuple[int, ...], __: int) -> Result[int, Issue]:
        return Err(replace_issue)

    assert optic.make_optional(get, replace).get_all(1) == []


def test_replace_copies_only_objects_and_arrays_along_the_focused_path():
    """replace copies only objects and arrays along the focused path"""
    s1: dict[str, Any] = {
        "user": {"id": "u1", "name": "Ada"},
        "settings": {"theme": "light"},
        "projects": [
            {"id": 1, "name": "Alpha", "tasks": [{"id": 1, "done": False, "title": "T1"}]},
            {"id": 2, "name": "Beta", "tasks": [{"id": 2, "done": False, "title": "T2"}]},
        ],
    }
    done = optic.Id[dict[str, Any]]().key("projects").key(1).key("tasks").key(0).key("done")
    s2 = done.replace(True, s1)
    assert s2 is not s1
    assert s2["user"] is s1["user"]
    assert s2["settings"] is s1["settings"]
    assert s2["projects"] is not s1["projects"]
    assert s2["projects"][0] is s1["projects"][0]
    assert s2["projects"][1] is not s1["projects"][1]
    assert s2["projects"][1]["tasks"] is not s1["projects"][1]["tasks"]
    assert s2["projects"][1]["tasks"][0] is not s1["projects"][1]["tasks"][0]
    assert s2["projects"][1]["tasks"][0]["done"] is True
    assert s1["projects"][1]["tasks"][0]["done"] is False


def test_from_checks():
    """fromChecks"""
    prism = optic.Id[float]().compose(optic.from_checks(S.is_greater_than(0), S.is_int()))
    assert prism.get_result(1) == Ok(1)
    assert_failure_message(prism.get_result(0), "Expected a value greater than 0")
    assert_failure_message(prism.get_result(1.1), "Expected an integer")
    assert isinstance(failure_of(prism.get_result(0)), Composite)


def test_option_some():
    """Option / some"""
    from pyfect.option import Option, Some

    prism = optic.Id[Option[int]]().compose(optic.some())
    assert prism.get_result(Some(1)) == Ok(1)
    assert_failure_message(prism.get_result(None), "Expected a Some value")
    assert prism.set(2) == Some(2)


def test_option_none():
    """Option / none"""
    from pyfect.option import Option, Some

    prism = optic.Id[Option[int]]().compose(optic.none())
    assert prism.get_result(None) == Ok(None)
    assert_failure_message(prism.get_result(Some(1)), "Expected a None value")
    assert prism.set(None) is None


def test_result_success():
    """Result / success"""
    prism = optic.Id[Result[int, str]]().compose(optic.success())
    assert prism.get_result(Ok(1)) == Ok(1)
    assert_failure_message(prism.get_result(Err("error")), "Expected a Result.Success value")
    assert prism.set(2) == Ok(2)


def test_result_failure():
    """Result / failure"""
    prism = optic.Id[Result[int, str]]().compose(optic.failure())
    assert prism.get_result(Err("error")) == Ok("error")
    assert_failure_message(prism.get_result(Ok(1)), "Expected a Result.Failure value")
    assert prism.set("new error") == Err("new error")
