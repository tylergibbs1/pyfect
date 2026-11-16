"""Keys a peer chooses cost near-linear time however their hashes collide.

CPython's ``int`` hash is not seeded: ``k * (2**61 - 1)`` all hash to 0, so a
dict or set of such ids a peer sent costs quadratic time. Every place a peer's
ints key a dict or set is fed all-colliding ints here."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, cast

import _source
import pytest
from _growth import Work, assert_near_linear

import pyfect as fx
from pyfect import schema as S
from pyfect._equal import dedupe
from pyfect._peer_keys import (
    MAX_SHARED_HASH,
    HashFlood,
    PeerKeyDict,
    PeerKeySet,
    check_spread,
    peer_key,
)
from pyfect.rpc._json_rpc import decode_json_rpc, encode_json_rpc

P = 2**61 - 1


def _colliding(n: int) -> list[int]:
    ids = [i * P for i in range(1, n + 1)]
    assert len({hash(i) for i in ids}) == 1
    return ids


def test_peer_key_keeps_equal_ids_equal_and_spreads_colliding_ones() -> None:
    assert peer_key(5) == 5
    assert peer_key("5") == "5"
    assert peer_key(3 * P) == peer_key(3 * P)
    assert peer_key(3 * P) != peer_key(4 * P)
    assert len({hash(peer_key(i)) for i in _colliding(1000)}) > 990


def test_peer_key_dict_and_set_take_colliding_ids_in_near_linear_time() -> None:
    def dict_of(n: int) -> Work:
        ids = _colliding(n)

        def work() -> None:
            d = PeerKeyDict[int, int]()
            for i in ids:
                d[i] = i
            assert all(d[i] == i for i in ids)

        return work

    def set_of(n: int) -> Work:
        ids = _colliding(n)

        def work() -> None:
            s = PeerKeySet[int]()
            for i in ids:
                s.add(i)
            assert all(i in s for i in ids)

        return work

    assert_near_linear(dict_of, 2000, 8 * 2000, bound=32, floor=0.0032)
    assert_near_linear(set_of, 2000, 8 * 2000, bound=32, floor=0.0032)


def test_peer_key_dict_behaves_as_a_dict() -> None:
    d = PeerKeyDict[object, str]()
    d[1] = "a"
    d["1"] = "b"
    d[P] = "c"
    assert d[1] == "a"
    assert d["1"] == "b"
    assert d.pop(P) == "c"
    assert P not in d
    assert sorted(map(str, d)) == ["1", "1"]
    assert d.get(2) is None
    assert d.setdefault(2, "x") == "x"
    assert len(d) == 3


def test_check_spread_refuses_many_distinct_keys_of_one_hash() -> None:
    check_spread([*_colliding(MAX_SHARED_HASH), P, P, P])
    with pytest.raises(HashFlood):
        check_spread(_colliding(MAX_SHARED_HASH + 1))
    # Floats that are not crafted share hashes too (2.0 ** 61 hashes to 1).
    check_spread([2.0 ** (61 * k) for k in range(17)] + [2.0 ** (-61 * k) for k in range(18)])


def test_dedupe_of_colliding_ints_fails_fast() -> None:
    with pytest.raises(HashFlood):
        dedupe(_colliding(1000))


def _same(ids: list[int]) -> object:
    return ids


def _pairs(ids: list[int]) -> object:
    return [[i, None] for i in ids]


def _json(text: str) -> Any:
    from pyfect._json_text import parse

    return parse(text)


@pytest.mark.parametrize(
    ("schema", "shape"),
    [
        (S.FrozenSet(S.Number), _same),
        (S.Map(S.Number, S.Null), _pairs),
        (S.Array(S.Number).check(S.is_unique()), _same),
        (S.FrozenSet(S.Unknown), _same),
    ],
    ids=["frozenset", "map", "is_unique", "unknown_set"],
)
def test_schema_sets_and_maps_of_colliding_numbers_fail_in_near_linear_time(
    schema: S.Codec[Any, Any, Any, Any], shape: Callable[[list[int]], object]
) -> None:
    decode = S.decode_unknown_exit(S.to_codec_json(schema))

    def sized(n: int) -> Work:
        value: object = _json(json.dumps(shape(_colliding(n))))
        return lambda: decode(value)

    assert isinstance(sized(1000)(), fx.Failure)
    assert_near_linear(sized, 1000, 8 * 1000, bound=32, floor=0.0032)


def test_is_unique_says_a_hash_flood_is_not_a_duplicate() -> None:
    """Like ``FrozenSet`` and ``Map``, ``is_unique`` explains refusing
    distinct items that share one hash, instead of calling them duplicates."""
    decode = S.decode_unknown_exit(S.Array(S.Number).check(S.is_unique()))
    flooded = decode(_colliding(MAX_SHARED_HASH + 1))
    assert isinstance(flooded, fx.Failure)
    assert str(flooded.cause.squash()) == (
        f"Expected an array with unique items (at most {MAX_SHARED_HASH} may share a hash)"
    )
    duplicated = decode([1, 2, 1])
    assert isinstance(duplicated, fx.Failure)
    assert str(duplicated.cause.squash()) == "Expected an array with unique items"


def test_schema_sets_of_ordinary_numbers_still_decode() -> None:
    decode = S.decode_unknown_sync(S.to_codec_json(S.FrozenSet(S.Number)))
    assert decode([1, 2, 2, P, 2 * P]) == frozenset({1, 2, P, 2 * P})


def test_json_rpc_batches_of_colliding_ids_take_near_linear_time() -> None:
    def sized(n: int) -> Work:
        batch = [{"jsonrpc": "2.0", "method": "m", "id": i} for i in _colliding(n)]

        def work() -> None:
            batches: dict[object, Any] = {}
            messages = decode_json_rpc(batch, batches)
            for message in messages:
                assert isinstance(message, dict)
                request_id = cast("dict[str, object]", message)["id"]
                exit: dict[str, object] = {"_tag": "Success", "value": None}
                response: dict[str, object] = {
                    "_tag": "Exit",
                    "requestId": request_id,
                    "exit": exit,
                }
                encode_json_rpc(response, batches)
            assert not batches

        return work

    assert_near_linear(sized, 2000, 8 * 2000, bound=32, floor=0.0032)


def test_json_rpc_skips_ids_that_are_not_request_ids_in_a_batch() -> None:
    batches: dict[object, Any] = {}
    messages = decode_json_rpc(
        [{"jsonrpc": "2.0", "method": "m", "id": {"a": 1}}, {"jsonrpc": "2.0", "method": "m"}],
        batches,
    )
    assert len(messages) == 2
    assert not batches


_PEER_MAP = re.compile(r"\b(?:dict|set|frozenset)\[RequestId\b")


def test_no_map_is_keyed_by_raw_request_ids() -> None:
    """Request ids come from peers: maps of them are ``PeerKeyDict`` /
    ``PeerKeySet``, never a plain ``dict`` or ``set``."""
    root = _source.SRC
    found = [
        f"{path.relative_to(root)}:{n}"
        for path in _source.files(root)
        for n, line in enumerate(_source.text(path).splitlines(), 1)
        if _PEER_MAP.search(line)
    ]
    assert found == []
