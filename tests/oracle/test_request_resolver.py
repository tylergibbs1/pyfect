"""Ports of Effect's ``RequestResolver.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``
prefix). ``RequestResolver.make`` is the ``RequestResolver`` constructor
(its ``run_all`` takes the entries) and ``makeGrouped`` is
``make_grouped``; ``Data.Class`` keys are frozen dataclasses and
``Effect.serviceOption`` is ``service_option``. Where Effect checks a key
with ``strictEqual``, the port checks identity (``is``)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.batching import Entry
from pyfect.tracer import Span


@dataclass(frozen=True)
class Key:
    id: int


@dataclass(frozen=True)
class GetValue(fx.Request[int]):
    key: Key


class Tenant(fx.Tag[str]): ...


@dataclass(frozen=True)
class GetTenant(fx.Request[str]):
    id: int


current_tenant = fx.service_option(Tenant).map(lambda t: "missing" if t is None else t.value)


def _tenant_of(_entry: Entry[GetTenant]) -> fx.Effect[str]:
    return current_tenant


@testing.effect
def test_from_effect_runs_each_entry_with_its_caller_context():
    """RequestResolver.fromEffect > runs each entry with its caller context"""
    resolver = fx.RequestResolver.from_effect(_tenant_of)
    values = yield from fx.all(
        fx.request(GetTenant(1), resolver).pipe(fx.provide_service(Tenant, "first")),
        fx.request(GetTenant(2), resolver).pipe(fx.provide_service(Tenant, "second")),
        concurrency="unbounded",
    )
    assert values == ("first", "second")


@testing.effect
def test_from_effect_does_not_inherit_a_service_absent_from_the_caller_context():
    """RequestResolver.fromEffect > does not inherit a service absent from the caller context"""
    resolver = fx.RequestResolver.from_effect(_tenant_of)
    values = yield from fx.all(
        fx.request(GetTenant(1), resolver).pipe(fx.provide_service(Tenant, "private-tenant")),
        fx.request(GetTenant(2), resolver),
        concurrency="unbounded",
    )
    assert values == ("private-tenant", "missing")


def _tenant_run_all(entries: Sequence[Entry[GetTenant]]) -> fx.Effect[None]:
    def complete(tenant: str) -> None:
        value = f"{tenant}:{','.join(str(e.request.id) for e in entries)}"
        for entry in entries:
            entry.complete_unsafe(fx.Success(value))

    return current_tenant.map(complete)


@pytest.mark.parametrize("constructor", ["make", "makeGrouped"])
@testing.effect
def test_uses_the_first_caller_context_whether_the_batch_reaches_its_cutoff_or_not(
    constructor: str,
):
    """RequestResolver.${constructor} > uses the first caller context whether the batch reaches its cutoff or not"""  # noqa: E501
    base = (
        fx.RequestResolver(_tenant_run_all)
        if constructor == "make"
        else fx.RequestResolver[GetTenant].make_grouped(
            key=lambda _: "shared", resolver=lambda entries, _key: _tenant_run_all(entries)
        )
    )
    resolver = base.batch_n(2)
    values = yield from fx.all(
        fx.request(GetTenant(1), resolver).pipe(fx.provide_service(Tenant, "first")),
        fx.request(GetTenant(2), resolver).pipe(fx.provide_service(Tenant, "second")),
        fx.request(GetTenant(3), resolver).pipe(fx.provide_service(Tenant, "third")),
        concurrency="unbounded",
    )
    assert values == ("first:1,2", "first:1,2", "third:3")


def _key_resolver(
    keys: list[tuple[Key, int]],
) -> fx.RequestResolver[GetValue]:
    def resolve(entries: Sequence[Entry[GetValue]], key: Key) -> fx.Effect[None]:
        def go() -> None:
            keys.append((key, len(entries)))
            for entry in entries:
                entry.complete_unsafe(fx.Success(key.id))

        return fx.sync(go)

    def key_of(entry: Entry[GetValue]) -> Key:
        return entry.request.key

    return fx.RequestResolver.make_grouped(key=key_of, resolver=resolve)


@testing.effect
def test_keeps_equal_keys_batched_across_derived_resolvers_and_releases_them_before_the_next_window():  # noqa: E501
    """RequestResolver.makeGrouped > keeps equal keys batched across derived resolvers and releases them before the next window"""  # noqa: E501
    gate = yield from fx.Deferred[None].make()
    batches: list[tuple[Key, int]] = []
    resolver = _key_resolver(batches).set_delay_effect(fx.yield_now().and_then(gate.wait()))
    first = yield from fx.request(GetValue(Key(1)), resolver).fork(start_immediately=True)
    # Running a derived resolver must not split the delayed resolver's pending batch.
    yield from fx.request(GetValue(Key(1)), resolver.batch_n(1))
    rest = yield from fx.for_each(
        [1, 2],
        lambda i: fx.request(GetValue(Key(i)), resolver).fork(start_immediately=True),
    )
    yield from gate.succeed(None)
    values = yield from fx.for_each([first, *rest], lambda f: f.join())
    assert values == [1, 1, 2]
    assert [size for _, size in batches] == [1, 2, 1]

    nxt = Key(1)
    yield from fx.request(GetValue(nxt), resolver)
    assert batches[3][0] is nxt


@testing.effect
def test_releases_the_key_when_the_last_pending_request_is_interrupted():
    """RequestResolver.makeGrouped > releases the key when the last pending request is interrupted"""  # noqa: E501
    keys: list[tuple[Key, int]] = []
    resolver = _key_resolver(keys)
    fiber = yield from fx.request(GetValue(Key(1)), resolver).fork(start_immediately=True)
    yield from fiber.interrupt()
    nxt = Key(1)
    yield from fx.request(GetValue(nxt), resolver)

    assert len(keys) == 1
    assert keys[0][0] is nxt


@dataclass(frozen=True)
class GetSpan(fx.Request[Span]):
    kind: Literal["client", "server"]


@testing.effect
def test_with_span_applies_span_options_returned_by_an_options_function():
    """RequestResolver.withSpan > applies span options returned by an options function"""

    def run_all(entries: Sequence[Entry[GetSpan]]):
        span = yield from fx.current_span().or_die()
        for entry in entries:
            entry.complete_unsafe(fx.Success(span))

    resolver = fx.RequestResolver(fx.fn(run_all)).with_span(
        "resolver", lambda entries: {"kind": entries[0].request.kind}
    )
    span = yield from fx.request(GetSpan("client"), resolver)

    assert span.kind == "client"
