"""Ports of Effect's ``SchemaAST.test.ts``: ``isJson``, ``Suspend`` and the
union candidate index. Each test's docstring is the Effect test title,
prefixed by its ``describe`` block. ``getCandidateIndex(types)(input)`` is
``union.candidates(input)`` of an ``S.ast.Union``.

Python mappings: ``undefined`` has no counterpart (``None`` is ``null``);
an ``int`` is a JSON number, a ``bigint`` not being a separate type; a
JSON object is any ``Mapping`` with ``str`` keys, a JSON array a ``list``
or ``tuple``.

Omitted:
- "mapOrSame / ...", "AST updates / ...", "stores constructor defaults
  directly in the context", the "toType / ..." titles, "Union options /
  preserves the complete options object through recur and flip",
  "getIndexSignatureKeys / ...", "record / ...", "IndexSignature / ...":
  internals of Effect's AST (contexts, encodings, encoding checks) that
  pyfect's nodes do not have, or that the struct and record ports cover.
- "isJson" sparse arrays, getters, symbols, ``Date``, ``RegExp``,
  ``Uint8Array``, null-prototype and cross-realm objects: JavaScript
  values; their Python counterparts (a ``datetime``, a ``set``, an
  object) are in the "isJson" port.
- "isStringTree" sparse arrays, inherited values, ``Map``, ``Date`` and
  class instances: JavaScript values (a ``set``, a ``datetime`` and an
  ``object`` stand for them); ``null`` is ``None``, a missing leaf, so
  ``None`` is a string tree here.
- "collectSentinels / ...": internal; each case is covered through
  ``candidates`` and union decoding (``tests/oracle/test_schema_checks.py``
  and ``test_schema_composites.py``). "... / Declaration / ~sentinels" and
  "getCandidateIndex / should handle function-valued declarations with
  sentinels", "... should deduplicate repeated declaration sentinels":
  declarations carry no sentinels in pyfect.
- "getCandidateIndex / literal-only union with a unique symbol", "...
  tagged tuples with unique symbol sentinels": no symbols.
- "getCandidateIndex / constructor mode ...": pyfect's constructors
  validate one class, never a union input.
- "getCandidateIndex / should protect cached common sentinel candidates
  from external mutation", "... should reuse the candidates of a runtime
  type without literals", "... should reuse non-discriminated candidates of
  a tagged union": identity and freezing of Effect's cached arrays; each
  call returns a new list here.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal, TypedDict

from pyfect import schema as S
from pyfect.exit import Failure


def _candidates(node: S.ast.AST) -> Callable[[object], list[int]]:
    assert isinstance(node, S.ast.Union)
    return node.candidates


def _index(*members: S.Top) -> Callable[[object], list[int]]:
    return _candidates(S.Union(*members).ast)


def test_suspend_memoizes_the_thunk():
    """Suspend / memoizes the thunk"""
    calls: list[None] = []

    def thunk() -> S.ast.AST:
        calls.append(None)
        return S.ast.string

    node = S.ast.Suspend(thunk)
    assert calls == []
    assert node.target is S.ast.string
    assert node.target is S.ast.string
    assert len(calls) == 1


def test_is_json():
    """isJson"""
    for value in (None, True, False, "string", 1, 1.5, 10**30, [], [1], {}, {"a": 1}, (1, "a")):
        assert S.ast.is_json(value), value
    for value in (
        float("nan"),
        float("inf"),
        float("-inf"),
        [1, float("nan")],
        {"a": 1, "b": float("inf")},
        {1: "a"},
        {"a", "b"},
        datetime(2021, 1, 1, tzinfo=UTC),
        b"a",
        object(),
    ):
        assert not S.ast.is_json(value), value
    # nested
    assert S.ast.is_json({"a": {"b": 1}})
    assert S.ast.is_json({"a": [1, {"b": "c"}]})
    assert not S.ast.is_json({"a": {"b": object()}})
    # circular reference
    circular: dict[str, object] = {}
    circular["self"] = circular
    assert not S.ast.is_json(circular)
    # accepts DAGs
    shared = {"a": 1}
    assert S.ast.is_json({"x": shared, "y": shared})
    assert S.ast.is_json([shared, {"nested": shared}])
    assert S.ast.is_json({"parent": {"left": shared, "right": shared}})


def test_is_json_is_stack_safe():
    """isJson is stack safe"""
    valid: object = None
    invalid: object = object()
    for _ in range(25_000):
        valid = [valid]
        invalid = [invalid]
    assert S.ast.is_json(valid)
    assert not S.ast.is_json(invalid)


def test_schema_to_codec_json_rejects_non_json_objects():
    """Schema.toCodecJson rejects non-JSON objects"""
    encode = S.encode_unknown_exit(S.to_codec_json(S.Unknown))
    assert isinstance(encode({1: "a"}), Failure)
    assert isinstance(encode({"a", "b"}), Failure)


def test_is_string_tree():
    """isStringTree"""
    # ``None`` is Effect's ``undefined`` (a missing leaf).
    for value in (None, "string", [], ["a"], ["a", None], {}, {"a": "b"}, {"a": None}, ("a",)):
        assert S.ast.is_string_tree(value), value
    for value in (True, False, 1, 10**30, 1.5, ["a", 1], {"a": "b", "c": 1}, {1: "a"}, object()):
        assert not S.ast.is_string_tree(value), value
    assert not S.ast.is_string_tree(datetime(1970, 1, 1, tzinfo=UTC))
    # nested
    assert S.ast.is_string_tree({"a": {"b": "c"}})
    assert S.ast.is_string_tree({"a": ["b", {"c": "d"}]})
    assert not S.ast.is_string_tree({"a": {"b": 1}})
    # DAG
    shared = {"value": "a"}
    assert S.ast.is_string_tree({"left": shared, "right": shared})
    # circular reference
    circular: dict[str, object] = {}
    circular["self"] = circular
    assert not S.ast.is_string_tree(circular)


def test_is_string_tree_is_stack_safe():
    """isStringTree is stack safe"""
    valid: object = "value"
    invalid: object = 1
    for _ in range(25_000):
        valid = {"value": valid}
        invalid = {"value": invalid}
    assert S.ast.is_string_tree(valid)
    assert not S.ast.is_string_tree(invalid)


def test_get_candidate_index_should_exclude_never():
    """getCandidateIndex / should exclude never"""
    assert _index(S.String, S.Never)("a") == [0]


def test_get_candidate_index_should_exclude_by_type():
    """getCandidateIndex / should exclude by type"""
    index = _index(S.String, S.Null)
    assert index("a") == [0]
    assert index(None) == [1]
    assert index(1) == []


def test_get_candidate_index_should_exclude_by_literals():
    """getCandidateIndex / should exclude by literals"""
    index = _index(S.Literal("b"), S.String)
    assert index("b") == [0, 1]
    assert index("c") == [1]
    assert index(1) == []
    assert _index(S.String, S.Literal("b"))("c") == [0]


def test_get_candidate_index_literals():
    """getCandidateIndex / Literals"""
    index = _candidates(S.Literals("a", "b", "c").ast)
    assert index("a") == [0]
    assert index("b") == [1]
    assert index("c") == [2]
    assert index("d") == []
    assert index(None) == []


def test_get_candidate_index_should_preserve_duplicate_literal_candidates_in_member_order():
    """getCandidateIndex / should preserve duplicate literal candidates in member order"""
    index = _index(S.Literal("a"), S.Literal("a"), S.Never)
    assert index("a") == [0, 1]
    assert index("b") == []


def test_get_candidate_index_string_or_literals():
    """getCandidateIndex / String | Literals"""
    assert _index(S.String, S.Literals("a", "b", "c"))(None) == []


class _A(TypedDict):
    _tag: Literal["a"]
    a: str


class _B(TypedDict):
    _tag: Literal["b"]
    b: float


def test_get_candidate_index_should_handle_tagged_structs():
    """getCandidateIndex / should handle tagged structs"""
    index = _index(S.Struct(_A), S.Struct(_B), S.String)
    assert index({}) == []
    assert index({"_tag": "a"}) == [0]
    assert index({"_tag": "b"}) == [1]
    assert index({"_tag": "c"}) == []
    assert index("") == [2]
    assert index(1) == []


class _KindA(TypedDict):
    kind: Literal["a"]
    value: str


class _KindB(TypedDict):
    kind: Literal["b"]
    value: float


def test_get_candidate_index_should_preserve_duplicate_candidates_with_a_common_discriminator():
    """getCandidateIndex / should preserve duplicate candidates with a common discriminator"""
    member = S.Struct(_KindA)
    index = _index(member, S.Struct(_KindB), member, S.Never)
    assert index({"kind": "a"}) == [0, 2]
    assert index({"kind": "b"}) == [1]
    assert index({"kind": "c"}) == []
    assert index({}) == []
    assert index("a") == []


class _KindStatus(TypedDict):
    kind: Literal["a"]
    status: Literal["ready"]
    value: str


class _Status(TypedDict):
    status: Literal["ready"]
    value: str


def test_get_candidate_index_should_handle_candidates_with_different_sentinel_keys():
    """getCandidateIndex / should handle candidates with different sentinel keys"""
    index = _index(S.Struct(_KindStatus), S.Struct(_Status))
    assert index({"kind": "a", "status": "ready", "value": "value"}) == [0, 1]
    assert index({"kind": "b", "status": "ready", "value": "value"}) == [1]
    assert index({"kind": None, "status": "ready", "value": "value"}) == [1]


def test_get_candidate_index_should_handle_tagged_tuples():
    """getCandidateIndex / should handle tagged tuples"""
    index = _index(S.Tuple(S.Literal("a"), S.String), S.Tuple(S.Literal("b"), S.Number), S.String)
    assert index([]) == []
    assert index(["a"]) == [0]
    assert index(("b",)) == [1]
    assert index(["c"]) == []
    assert index("") == [2]
    assert index(1) == []


class _AX(TypedDict):
    kind: Literal["a"]
    variant: Literal["x"]


class _AY(TypedDict):
    kind: Literal["a"]
    variant: Literal["y"]


class _KindOnlyB(TypedDict):
    kind: Literal["b"]


def test_get_candidate_index_should_dispatch_a_nested_union_member_by_its_common_sentinel():
    """getCandidateIndex / should dispatch a nested union member by its common sentinel"""
    hosted = S.Union(S.Struct(_AX), S.Struct(_AY))
    index = _index(hosted, S.Struct(_KindOnlyB))
    assert index({"kind": "a"}) == [0]
    assert index({"kind": "b"}) == [1]


class _AXValue(TypedDict):
    kind: Literal["a"]
    variant: Literal["x"]
    value: str


class _AYValue(TypedDict):
    kind: Literal["a"]
    variant: Literal["y"]
    value: float


def test_get_candidate_index_should_exclude_members_whose_sentinel_the_input_contradicts():
    """getCandidateIndex / should exclude members whose sentinel the input contradicts"""
    index = _index(S.Struct(_AXValue), S.Struct(_AYValue))
    assert index({"kind": "a", "variant": "x"}) == [0]
    assert index({"kind": "a", "variant": "z"}) == []
    assert index({"kind": "a", "variant": None}) == []
    # A missing sentinel key does not exclude: the member still owes the error.
    assert index({"kind": "a"}) == [0, 1]
