"""Values Python calls equal but Effect's ``Equal.equals`` keeps apart
(``1`` and ``True``, also inside containers), and NaNs Python keeps apart
but Effect calls equal (QA schema-data F05, F06; the cause dedupe of
PARITY's "Still open").

Effect, ``node``::

    S.decodeUnknownSync(S.UniqueArray(S.Unknown))([1, true])        // accepted
    S.decodeUnknownSync(S.UniqueArray(S.Unknown))([NaN, NaN])
    // Expected an array with unique items
    S.decodeUnknownSync(S.toCodecJson(S.ReadonlySet(S.Number)))(["NaN", "NaN"])
    // one NaN
    Cause.combine(Cause.fail(1), Cause.fail(true))                  // two reasons

A Python ``frozenset`` or ``dict`` cannot hold ``1`` and ``True`` apart, so
``S.FrozenSet`` / ``S.Map`` decoding both is a ``SchemaError`` rather than a
silent merge (PARITY §4); ``S.HashSet`` / ``S.HashMap`` keep both, as Effect's.
"""

from __future__ import annotations

import ast as pyast
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import cause as C
from pyfect import schema as S
from pyfect import stream
from pyfect._equal import dedupe, equal_key, equals
from pyfect.hash_set import HashSet

# Pairs Python's ``==`` calls equal that ``Equal.equals`` keeps apart: the
# helper every Equal-keyed surface is checked against.
PYTHON_COLLAPSING_PAIRS: list[tuple[object, object]] = [
    (1, True),
    (0, False),
    ({"a": 1}, {"a": True}),
    ([1], [True]),
    ((0,), (False,)),
    (frozenset({1}), frozenset({True})),
]


def _nan_pair() -> tuple[float, float]:
    # Two NaN objects (``float("nan")`` makes a new one each time).
    return float("nan"), float("nan")


@pytest.mark.parametrize(("a", "b"), PYTHON_COLLAPSING_PAIRS)
def test_equal_keys_keep_booleans_apart_from_numbers(a: object, b: object):
    assert not equals(a, b)
    assert equal_key(a) != equal_key(b)
    assert dedupe([a, b]) == [a, b]


def test_equal_keys_call_every_nan_equal_and_keep_one_and_one_point_zero_equal():
    first, second = _nan_pair()
    assert first is not second
    assert equals(first, second)
    assert equals([first], (second,))
    assert equals(1, 1.0)
    assert len(dedupe([first, second])) == 1


@pytest.mark.parametrize(("a", "b"), PYTHON_COLLAPSING_PAIRS)
def test_unique_array_accepts_items_python_calls_equal(a: object, b: object):
    assert S.decode_unknown_sync(S.UniqueArray(S.Unknown))([a, b]) == (a, b)


def test_unique_array_rejects_two_distinct_nans():
    with pytest.raises(S.SchemaError, match="Expected an array with unique items"):
        S.decode_unknown_sync(S.UniqueArray(S.Unknown))(list(_nan_pair()))


def test_is_unique_key_keeps_true_apart_from_one():
    pairs = S.Array(S.Tuple(S.Unknown, S.String)).check(S.is_unique_key())
    assert S.decode_unknown_sync(pairs)([(1, "a"), (True, "b")]) == ((1, "a"), (True, "b"))


def test_a_json_set_keeps_one_nan():
    decoded = S.decode_unknown_sync(S.to_codec_json(S.FrozenSet(S.Number)))(["NaN", "NaN"])
    assert len(decoded) == 1


_NUMBER_OR_BOOLEAN = S.Union(S.Number, S.Boolean)
_SETS_AND_MAPS: list[tuple[str, Callable[[], Any]]] = [
    (
        "json set",
        lambda: S.decode_unknown_sync(S.to_codec_json(S.FrozenSet(_NUMBER_OR_BOOLEAN)))([1, True]),
    ),
    (
        "json map",
        lambda: S.decode_unknown_sync(S.to_codec_json(S.Map(_NUMBER_OR_BOOLEAN, S.String)))(
            [[1, "a"], [True, "b"]]
        ),
    ),
    (
        "decoded set",
        lambda: S.decode_unknown_sync(S.FrozenSet(S.Union(S.NumberFromString, S.BooleanFromBit)))(
            {"1", 1}
        ),
    ),
]


@pytest.mark.parametrize(("name", "decode"), _SETS_AND_MAPS)
def test_a_set_or_map_that_python_would_merge_is_a_schema_error(
    name: str, decode: Callable[[], Any]
):
    with pytest.raises(S.SchemaError, match="keeps apart"):
        decode()


def test_a_set_or_map_without_collisions_still_decodes():
    json_map = S.to_codec_json(S.Map(_NUMBER_OR_BOOLEAN, S.String))
    assert S.decode_unknown_sync(json_map)([[1, "a"], [1.0, "b"]]) == {1: "b"}


def test_hash_set_and_hash_map_keep_one_and_true_apart():
    """Effect: ``S.decodeUnknownSync(S.toCodecJson(S.HashSet(S.Unknown)))([1, true])``
    has size 2, as does the ``HashMap`` of ``[[1, "a"], [true, "b"]]``."""
    hash_set = S.decode_unknown_sync(S.to_codec_json(S.HashSet(_NUMBER_OR_BOOLEAN)))([1, True])
    assert len(hash_set) == 2
    assert hash_set.has(1)
    assert hash_set.has(True)
    hash_map = S.decode_unknown_sync(S.to_codec_json(S.HashMap(_NUMBER_OR_BOOLEAN, S.String)))(
        [[1, "a"], [True, "b"]]
    )
    assert hash_map.get(1) == fx.Some("a")
    assert hash_map.get(True) == fx.Some("b")
    decoded = S.decode_unknown_sync(S.HashSet(S.Union(S.NumberFromString, S.BooleanFromBit)))(
        HashSet.make("1", 1)
    )
    assert len(decoded) == 2


def test_hash_set_and_hash_map_keep_one_nan():
    """Effect: ``S.toCodecJson(S.HashSet(S.Number))`` decodes ``["NaN", "NaN"]``
    to one item; ``[["NaN", 1], ["NaN", 2]]`` to the map of ``NaN`` to ``2``."""
    hash_set = S.decode_unknown_sync(S.to_codec_json(S.HashSet(S.Number)))(["NaN", "NaN"])
    assert len(hash_set) == 1
    hash_map = S.decode_unknown_sync(S.to_codec_json(S.HashMap(S.Number, S.Number)))(
        [["NaN", 1], ["NaN", 2]]
    )
    assert len(hash_map) == 1
    assert hash_map.get(math.nan) == fx.Some(2)


def test_cause_combine_keeps_fail_one_apart_from_fail_true():
    combined = C.fail(1) + C.fail(True)
    assert equals([r.error for r in combined.reasons if isinstance(r, C.Fail)], [1, True])
    assert len((C.fail(1) + C.fail(1)).reasons) == 1


def test_cause_combine_keeps_a_new_reason_python_calls_equal_to_a_repeated_one():
    """Effect: ``combine(fromReasons([fail(1), fail(1)]), fail(true))`` holds
    ``fail(1)`` and ``fail(true)`` (it returns ``self`` only when the result
    ``Equal.equals`` it)."""
    repeated = C.from_reasons((C.Fail(1), C.Fail(1)))
    combined = repeated + C.fail(True)
    assert equals([r.error for r in combined.reasons if isinstance(r, C.Fail)], [1, True])


def test_cause_combine_dedupes_nan_failures():
    first, second = _nan_pair()
    assert len((C.fail(first) + C.fail(second)).reasons) == 1


def test_to_equivalence_of_unknown_follows_equal():
    equivalent = S.to_equivalence(S.Unknown)
    assert not equivalent({"a": 1}, {"a": True})
    assert equivalent([math.nan], [float("nan")])


@pytest.mark.parametrize(("a", "b"), PYTHON_COLLAPSING_PAIRS)
def test_stream_changes_keeps_items_python_calls_equal(a: object, b: object):
    """``Stream.changes`` is ``changesWith(Equal.equals)``: Effect writes
    ``[1, true, 1, NaN, {a:1}, {a:true}, [0], [false]]`` for
    ``make(1, true, 1, 1.0, NaN, NaN, {a:1}, {a:1}, {a:true}, [0], [false])``."""
    out = fx.run_blocking(stream.make(a, b, a).changes().run_collect())
    assert equals(out, [a, b, a])


def test_stream_changes_drops_a_repeated_nan_and_one_point_zero():
    first, second = _nan_pair()
    out = fx.run_blocking(stream.make(1, 1.0, first, second).changes().run_collect())
    assert out[0] == 1
    assert len(out) == 2
    assert math.isnan(out[1])


_SRC = Path(__file__).resolve().parents[2] / "src" / "pyfect"
_PYTHON_KEYED = frozenset({"set", "frozenset", "dict"})


def _is_bare_equality(node: pyast.AST) -> bool:
    """``def f(a, b): return a == b`` or ``lambda a, b: a == b``: Python's
    ``==`` standing in for ``Equal.equals``."""
    match node:
        case pyast.Lambda(args=pyast.arguments(args=[_, _]), body=body):
            pass
        case pyast.FunctionDef(args=pyast.arguments(args=[_, _]), body=[pyast.Return(value)]):
            body = value
        case _:
            return False
    return (
        isinstance(body, pyast.Compare)
        and len(body.ops) == 1
        and isinstance(body.ops[0], pyast.Eq)
        and isinstance(body.left, pyast.Name)
        and isinstance(body.comparators[0], pyast.Name)
    )


def test_no_code_keys_or_compares_values_with_python_equality():
    """The guard: ``set`` / ``frozenset`` / ``dict`` as a codec's ``decode``,
    ``len(set(...))`` uniqueness and a bare ``a == b`` equality function
    merge ``1`` with ``True``; code builds those through ``pyfect._equal``
    (``equals`` / ``equal_key`` / ``dedupe``) instead."""
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        if path.name == "_equal.py":
            continue
        tree = pyast.parse(path.read_text(), str(path))
        for node in pyast.walk(tree):
            if _is_bare_equality(node):
                offenders.append(f"{path.name}:{node.lineno} a == b")  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
            if not isinstance(node, pyast.Call):
                continue
            decode = [k.value for k in node.keywords if k.arg == "decode"]
            if any(isinstance(v, pyast.Name) and v.id in _PYTHON_KEYED for v in decode):
                offenders.append(f"{path.name}:{node.lineno} decode=")
            if (
                isinstance(node.func, pyast.Name)
                and node.func.id == "len"
                and node.args
                and isinstance(call := node.args[0], pyast.Call)
                and isinstance(call.func, pyast.Name)
                and call.func.id in _PYTHON_KEYED
            ):
                offenders.append(f"{path.name}:{node.lineno} len(set(...))")
    assert offenders == [], "use pyfect._equal (equals / equal_key / dedupe)"
