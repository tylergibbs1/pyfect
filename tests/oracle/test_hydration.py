"""Ports of Effect's ``test/reactivity/Hydration.test.ts``, every title.

The tests run on ``FakeTimers``: ``flush()`` is ``await
Effect.runPromise(Effect.yieldNow)``. Effect's ``resultPromise`` is
``result_deferred``; ``encodeInitialAs: "promise"`` is
``encode_initial_as="deferred"``; ``Promise.withResolvers`` is a
``Deferred`` settled with ``done_unsafe``. pyfect's ``Success`` equality
leaves out the timestamp, so timestamps are compared on their own.
Awaiting a settled ``resultPromise`` is a check that the deferred is done:
the hydration it drives ran when it settled (a flush would also run the
registry's pending node removals, which Effect's microtask does not).
"""

import json
from typing import Any, Literal, cast

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.deferred import Deferred
from pyfect.exit import Success as ExitSuccess
from pyfect.reactivity import async_result, atom, hydration
from pyfect.reactivity.async_result import AsyncResult, Success
from pyfect.reactivity.hydration import DehydratedAtom

from ._atom_timers import FakeTimers, timers

__all__ = ["timers"]


def _result_atom[A](_: type[A]) -> atom.Writable[AsyncResult[A], AsyncResult[A]]:
    """``Atom.make<AsyncResult<A>>(AsyncResult.initial())``."""
    return atom.make(cast("AsyncResult[A]", async_result.initial()))


def _count_schema(success: Any = S.Number) -> Any:
    return async_result.Schema(success=success)


def test_runs_a_plain_hydrated_effect_atom_on_mount_and_tracks_factory_dependencies(
    timers: FakeTimers,
) -> None:
    """runs a plain hydrated effect atom on mount and tracks factory dependencies"""
    dependency = atom.make(1)
    runs = [0]

    def create(get: atom.AtomContext) -> fx.Effect[int]:
        value = get(dependency)

        def run() -> int:
            runs[0] += 1
            return value

        return fx.sync(run)

    count = atom.make(create).serializable(key="count", schema=_count_schema())
    server = timers.registry()
    client = timers.registry()
    try:
        seed: AsyncResult[int] = async_result.success(10)
        server_atom = atom.make(seed).serializable(key="count", schema=_count_schema())
        server.mount(server_atom)
        hydration.hydrate(client, hydration.dehydrate(server))
        client.mount(count)
        assert runs[0] == 1

        client.set(dependency, 2)
        result = client.get(count)
        assert isinstance(result, Success)
        assert result.value == 2
        assert runs[0] == 2
    finally:
        server.dispose()
        client.dispose()


def test_skip_initial_run_keeps_a_hydrated_effect_seed_until_a_factory_dependency_changes(
    timers: FakeTimers,
) -> None:
    """skipInitialRun keeps a hydrated effect seed until a factory dependency changes"""
    dependency = atom.make(1)
    runs = [0]

    def create(get: atom.AtomContext) -> fx.Effect[int]:
        value = get(dependency)

        def run() -> int:
            runs[0] += 1
            return value

        return fx.sync(run)

    count = atom.make(create).serializable(
        key="count", schema=_count_schema(), skip_initial_run=True
    )
    server = timers.registry()
    client = timers.registry()
    try:
        seed: AsyncResult[int] = async_result.success(10)
        server_atom = atom.make(seed).serializable(key="count", schema=_count_schema())
        server.mount(server_atom)
        hydration.hydrate(client, hydration.dehydrate(server))
        client.mount(count)

        result = client.get(count)
        assert isinstance(result, Success)
        assert result.value == 10
        assert runs[0] == 0

        client.set(dependency, 2)
        result = client.get(count)
        assert isinstance(result, Success)
        assert result.value == 2
        assert runs[0] == 1
    finally:
        server.dispose()
        client.dispose()


def test_notifies_subscribers_of_an_atom_the_registry_already_holds(timers: FakeTimers) -> None:
    """notifies subscribers of an atom the registry already holds"""
    count = atom.make(0).serializable(key="existing-count", schema=S.Int)
    doubled = count.map(lambda n: n * 2)
    registry = timers.registry()
    try:
        registry.mount(doubled)
        heard: list[int] = []
        registry.subscribe(count, heard.append)
        hydration.hydrate(registry, [DehydratedAtom("existing-count", 5, 0)])
        assert heard == [5]
        assert registry.get(doubled) == 10
    finally:
        registry.dispose()


def test_falls_back_on_the_first_read_of_invalid_immediate_hydration(timers: FakeTimers) -> None:
    """falls back on the first read of invalid immediate hydration"""
    count = atom.make(0).serializable(key="count", schema=S.Int)
    registry = timers.registry()
    try:
        hydration.hydrate(registry, [DehydratedAtom("count", "invalid", 0)])
        assert registry.get(count) == 0
    finally:
        registry.dispose()


@pytest.mark.parametrize("kind", ["invalid", "skipped"])
def test_releases_streamed_hydration(
    timers: FakeTimers, kind: Literal["invalid", "skipped"]
) -> None:
    """releases %s streamed hydration"""
    resolved: Deferred[float] = Deferred()
    server_atom = atom.make(resolved.wait()).serializable(
        key="count", schema=_count_schema(S.Number if kind == "invalid" else S.Int)
    )
    source = atom.make(fx.succeed(0))
    derived: atom.Atom[AsyncResult[int, Any]] = (
        source.map_result(lambda n: n + 1) if kind == "invalid" else source.with_refresh("1 hour")
    )
    client_atom = derived.serializable(key="count", schema=_count_schema(S.Int))
    server = timers.registry()
    client = timers.registry()
    try:
        server.mount(server_atom)
        state = hydration.to_values(hydration.dehydrate(server, encode_initial_as="deferred"))
        hydration.hydrate(client, state)
        client.mount(client_atom)
        assert client.get(client_atom) == async_result.initial(waiting=True)

        resolved.done_unsafe(ExitSuccess(0.5))
        deferred = state[0].result_deferred
        assert deferred is not None and deferred.is_done_unsafe()
        timers.flush()

        result = client.get(client_atom)
        assert isinstance(result, Success)
        assert result.value == (1 if kind == "invalid" else 0)
        assert result.waiting is False
    finally:
        server.dispose()
        client.dispose()


def test_preserves_client_state_when_a_superseded_stream_cannot_be_encoded(
    timers: FakeTimers,
) -> None:
    """preserves client state when a superseded stream cannot be encoded"""
    count = _result_atom(float).serializable(key="count", schema=_count_schema(S.Int))
    server = timers.registry()
    client = timers.registry()
    try:
        server.mount(count)
        state = hydration.dehydrate(server, encode_initial_as="deferred")
        hydration.hydrate(client, state)
        result = async_result.success(42)
        client.set(count, result)

        server.set(count, async_result.success(0.5))
        deferred = hydration.to_values(state)[0].result_deferred
        assert deferred is not None and deferred.is_done_unsafe()

        assert client.get(count) is result
    finally:
        server.dispose()
        client.dispose()


_PROFILE = _result_atom(str).serializable(
    key="profile", schema=async_result.Schema(success=S.String)
)


@pytest.mark.parametrize(
    ("server_timestamp", "expected", "expected_timestamp"),
    [(1000, "client", 2000), (3000, "server", 3000)],
)
def test_compares_result_freshness_on_the_next_read(
    timers: FakeTimers, server_timestamp: int, expected: str, expected_timestamp: int
) -> None:
    """compares result freshness on the next read (server timestamp: $serverTimestamp)"""
    server = timers.registry()
    client = timers.registry()
    try:
        server.set(_PROFILE, async_result.success("server", timestamp=server_timestamp))
        sent = json.dumps([entry.to_json() for entry in hydration.dehydrate(server)])
        state = [DehydratedAtom.from_json(entry) for entry in json.loads(sent)]
        client.set(_PROFILE, async_result.success("client", timestamp=2000))

        hydration.hydrate(client, state)

        result = client.get(_PROFILE)
        assert result == async_result.success(expected)
        assert isinstance(result, Success)
        assert result.timestamp == expected_timestamp
    finally:
        server.dispose()
        client.dispose()


def test_ignores_a_streamed_result_older_than_the_client_value_at_resolution(
    timers: FakeTimers,
) -> None:
    """ignores a streamed result older than the client value at resolution"""
    server = timers.registry()
    client = timers.registry()
    try:
        server.mount(_PROFILE)
        state = hydration.dehydrate(server, encode_initial_as="deferred")
        hydration.hydrate(client, state)

        # The client finishes after hydration starts but before the server result arrives.
        client.set(_PROFILE, async_result.success("client", timestamp=2000))
        server.set(_PROFILE, async_result.success("server", timestamp=1000))
        deferred = hydration.to_values(state)[0].result_deferred
        assert deferred is not None and deferred.is_done_unsafe()

        result = client.get(_PROFILE)
        assert result == async_result.success("client")
        assert isinstance(result, Success)
        assert result.timestamp == 2000
    finally:
        server.dispose()
        client.dispose()
