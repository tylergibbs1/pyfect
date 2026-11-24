"""Lazily filled caches hand every caller of a key the same value, also when threads ask for it
at once without the GIL (tests/free_threaded_suites.txt runs this file on CPython 3.14t). An RPC
server on one thread and its handler layer on another each made their own handler tag for an
RPC, and the server then found no handler ("Unknown request tag")."""

import threading
import types
from collections.abc import Callable, Sequence
from typing import Any, TypedDict

from pyfect import schema as S
from pyfect._stable_cache import StableCache, stable_cache
from pyfect.ai.toolkit import _handler_tag as tool_handler_tag  # pyright: ignore[reportPrivateUsage]
from pyfect.cluster import _interruptors as interruptors
from pyfect.cluster.entity_address import make as entity_address
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.shard_id import ShardId
from pyfect.date_time import zone_named
from pyfect.http_api import middleware as http_api_middleware
from pyfect.rpc import make as make_rpc
from pyfect.rpc import middleware as rpc_middleware
from pyfect.rpc._rpc import handler_tag

THREADS = 8
ROUNDS = 60


def _rounds_split[K](keys: Sequence[K], ask: Callable[[K], object]) -> list[K]:
    """The keys of ``keys`` for which ``THREADS`` threads, released together to ``ask`` for
    the key, got more than one object back."""
    barrier = threading.Barrier(THREADS)
    seen: list[list[object]] = [[None] * THREADS for _ in keys]
    failures: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            for row, key in zip(seen, keys, strict=True):
                barrier.wait()
                row[index] = ask(key)
        except BaseException as error:
            failures.append(error)
            barrier.abort()

    threads = [threading.Thread(target=worker, args=(index,)) for index in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not failures, failures
    return [key for key, row in zip(keys, seen, strict=True) if len({id(x) for x in row}) > 1]


def test_threads_asking_for_an_rpcs_handler_tag_at_once_get_one_tag():
    rpcs = [make_rpc(f"StableCacheRace{i}", payload=S.Int) for i in range(ROUNDS)]
    assert _rounds_split(rpcs, handler_tag) == []


def test_threads_asking_for_a_tools_handler_tag_at_once_get_one_tag():
    ids = [f"StableCacheRaceTool{i}" for i in range(ROUNDS)]
    assert _rounds_split(ids, tool_handler_tag) == []


def test_threads_asking_for_an_rpc_middlewares_client_tag_at_once_get_one_tag():
    middlewares: list[Any] = [
        types.new_class(f"Rpc{i}", (rpc_middleware.RpcMiddleware,), {"key": f"StableRpc{i}"})
        for i in range(ROUNDS)
    ]
    assert _rounds_split(middlewares, rpc_middleware.client_tag) == []


def test_threads_asking_for_an_http_api_middlewares_client_tag_at_once_get_one_tag():
    middlewares: list[Any] = [
        types.new_class(
            f"Http{i}", (http_api_middleware.HttpApiMiddleware,), {"key": f"StableHttp{i}"}
        )
        for i in range(ROUNDS)
    ]
    assert _rounds_split(middlewares, http_api_middleware.client_tag) == []


def test_threads_naming_an_offset_zone_at_once_get_one_zone():
    # A fixed zone is a ZoneInfo, which equals only itself: two of them for `+05:30` would
    # not be equal.
    names = [f"+{hours:02}:{minutes:02}" for hours in range(12) for minutes in (7, 19, 41, 53)]
    assert _rounds_split(names[:ROUNDS], zone_named) == []


def test_threads_deriving_a_typed_dicts_struct_at_once_share_its_ast():
    make_typed_dict: Any = TypedDict  # pyright reads only a literal name in TypedDict(...)
    dicts = [make_typed_dict(f"Race{i}", {"a": int, "b": str}) for i in range(ROUNDS)]
    assert _rounds_split(dicts, lambda td: S.Struct(td).ast) == []


def test_entities_held_on_several_threads_at_once_are_all_released():
    types_ = [f"StableCacheRaceType{i}" for i in range(ROUNDS)]

    def hold_and_release(entity_type: str) -> object:
        for _ in range(20):
            interruptors.acquire_entity_type(entity_type)
            interruptors.release_entity_type(entity_type)
        return None

    _rounds_split(types_, hold_and_release)
    for entity_type in types_:
        address = entity_address(
            shard_id=ShardId(group="g", id=1),
            entity_type=EntityType(entity_type),
            entity_id=EntityId("e"),
        )
        assert not interruptors.is_active(address), entity_type


def test_a_stable_cache_makes_each_keys_value_once_per_winner():
    cache = StableCache[int, object]()
    keys = list(range(ROUNDS))
    assert _rounds_split(keys, lambda key: cache.get(key, object)) == []
    assert cache.get(0, object) is cache.get(0, object)


def test_a_stable_cache_function_returns_one_result_per_arguments():
    made: list[tuple[int, str]] = []

    @stable_cache
    def box(n: int, label: str) -> list[object]:
        made.append((n, label))
        return [n, label]

    assert _rounds_split(list(range(ROUNDS)), lambda n: box(n, "x")) == []
    assert box(1, "x") is box(1, "x")
    assert box(1, "y") is not box(1, "x")
