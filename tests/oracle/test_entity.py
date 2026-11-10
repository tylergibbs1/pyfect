"""Ports of Effect's ``test/cluster/Entity.test.ts``. Each test's docstring
is the Effect test title; the titles Effect generates in a loop over
``disableFatalDefects`` are parametrized."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import stream, testing
from pyfect.cause import Die, Fail, Interrupt
from pyfect.cluster import sharding_config
from pyfect.cluster._entity_activation import CurrentActivationScope
from pyfect.cluster.entity import CurrentAddress, Entity, Replier, Request, make_test_client
from pyfect.deferred import Deferred
from pyfect.errors import Done
from pyfect.queue import Dequeue, Queue
from pyfect.rpc import make as make_rpc
from pyfect.scope import CloseableScope, Scope, add_finalizer, scoped

from ._cluster_entities import (
    CallerId,
    ContextBleedEntity,
    TestEntity,
    User,
    context_bleed_layer,
    test_entity_layer,
)

test_sharding_config = sharding_config.layer(
    replace(
        sharding_config.DEFAULTS,
        shards_per_group=300,
        entity_mailbox_capacity=10,
        entity_termination_timeout=fx.duration.seconds(0),
        entity_message_poll_interval=fx.duration.seconds(5),
        send_retry_interval=fx.duration.seconds(0.1),
    )
)


class StreamEntity(Entity, type="StreamEntity"):
    watch = make_rpc("Watch", success=S.Int, stream=True)


class FatalDefectEntity(Entity, type="FatalDefectEntity"):
    hold = make_rpc("Hold", success=S.Int)
    bad = make_rpc("Bad", error=S.String)


def _snapshot(exit: Exit.Exit[Any, Any]) -> tuple[str, Any]:
    if isinstance(exit, Exit.Success):
        return ("Success", exit.value)
    reasons: list[tuple[str, Any]] = []
    for reason in exit.cause.reasons:
        if isinstance(reason, Die):
            reasons.append(("Die", str(reason.defect)))
        elif isinstance(reason, Fail):
            reasons.append(("Fail", reason.error))
        else:
            assert isinstance(reason, Interrupt)
            reasons.append(("Interrupt", None))
    return ("Failure", reasons)


class FixtureDefect(Exception):
    pass


def _observe_fatal_defect(
    disable_fatal_defects: bool | None, defecting: bool, separate_ids: bool = False
) -> fx.Effect[tuple[tuple[str, Any], tuple[str, Any]], Any, Scope]:
    @fx.gen
    def run():
        entered = Deferred[None, Never]()
        release = Deferred[None, Never]()

        @fx.fn
        def hold(_: Request[None]):
            yield from entered.succeed(None)
            yield from release.wait()
            return 42

        def bad(_: Request[None]) -> fx.Effect[None, str]:
            return (
                fx.die(FixtureDefect("fixture defect")) if defecting else fx.fail("typed failure")
            )

        handlers = (
            FatalDefectEntity.handlers()
            .handle(FatalDefectEntity.hold)(hold)
            .handle(FatalDefectEntity.bad)(bad)
        )
        layer = (
            FatalDefectEntity.to_layer(handlers, concurrency="unbounded")
            if disable_fatal_defects is None
            else FatalDefectEntity.to_layer(
                handlers, concurrency="unbounded", disable_fatal_defects=disable_fatal_defects
            )
        )
        client_for = yield from make_test_client(FatalDefectEntity, layer)
        hold_client = yield from client_for("one")
        bad_client = yield from client_for("two" if separate_ids else "one")
        yield from add_finalizer(lambda _: release.succeed(None))
        good = yield from hold_client.hold().fork()
        yield from entered.wait()
        bad_exit = yield from bad_client.bad().exit()
        yield from release.succeed(None)
        good_exit = yield from good.await_exit()
        return _snapshot(bad_exit), _snapshot(good_exit)

    return run.pipe(fx.provide(sharding_config.layer_defaults)).timeout("5 seconds")


# --- makeTestClient ------------------------------------------------------------------------


@testing.effect
def test_provides_an_activation_scope_per_entity_and_closes_it_with_the_client():
    """provides an activation scope per entity and closes it with the client"""

    class ActivationScope(Entity, type="ActivationScope"):
        read = make_rpc("Read", success=S.String)

    activations: list[CloseableScope] = []
    closed: list[str] = []

    @fx.gen
    def build():
        address = yield from CurrentAddress()
        activation = yield from fx.service_option(CurrentActivationScope)
        assert activation is not None, "makeTestClient must provide the entity activation scope"
        activations.append(activation.value)
        yield from activation.value.add_finalizer(
            lambda _: fx.sync(lambda: closed.append(address.entity_id))
        )
        return ActivationScope.handlers().handle(ActivationScope.read)(
            lambda _: fx.succeed(address.entity_id)
        )

    layer = ActivationScope.to_layer_effect(build)

    @fx.gen
    def scoped_body():
        make_client = yield from make_test_client(ActivationScope, layer)
        first = yield from make_client("one")
        second = yield from make_client("two")
        assert (yield from first.read()) == "one"
        assert (yield from second.read()) == "two"
        assert len(activations) == 2
        assert activations[0] is not activations[1]
        assert closed == []

    yield from scoped(scoped_body).pipe(fx.provide(test_sharding_config))
    assert sorted(closed) == ["one", "two"]


@testing.effect
def test_creates_an_in_memory_client_for_an_entity_layer():
    """creates an in-memory client for an entity layer"""

    @fx.gen
    def body():
        make_client = yield from make_test_client(TestEntity, test_entity_layer)
        client = yield from make_client("123")
        user = yield from client.get_user({"id": 1})
        assert user == User(id=1, name="User 1")

    yield from body.pipe(fx.provide(test_sharding_config))


@testing.effect
def test_does_not_freeze_the_acquiring_fibers_context_into_the_entity_server():
    """does not freeze the acquiring fiber's context into the entity server"""

    @fx.gen
    def body():
        make_client = yield from make_test_client(ContextBleedEntity, context_bleed_layer)
        client = yield from make_client("1").pipe(fx.provide_service(CallerId, "A"))
        observed = yield from client.read_caller()
        assert observed == "none"

    yield from body.pipe(fx.provide(test_sharding_config))


_FLAGS = pytest.mark.parametrize("flag", [True, False, None], ids=["true", "false", "omitted"])


@_FLAGS
@testing.live
def test_isolates_defects_when_disable_fatal_defects_is(flag: bool | None):
    """isolates defects when disableFatalDefects is ${label}"""
    bad, good = yield from _observe_fatal_defect(flag, True)
    defect = ("Failure", [("Die", "fixture defect")])
    assert bad == defect, "Bad preserves the original defect"
    assert good == (("Success", 42) if flag is True else defect), (
        "Hold isolation follows the registered flag"
    )


@_FLAGS
@testing.live
def test_keeps_typed_failures_request_local_when_disable_fatal_defects_is(flag: bool | None):
    """keeps typed failures request-local when disableFatalDefects is ${label}"""
    bad, good = yield from _observe_fatal_defect(flag, False)
    assert bad == ("Failure", [("Fail", "typed failure")])
    assert good == ("Success", 42)


@testing.live
def test_does_not_send_fatal_defects_across_entity_ids():
    """does not send fatal defects across entity IDs"""
    bad, good = yield from _observe_fatal_defect(False, True, True)
    assert bad == ("Failure", [("Die", "fixture defect")])
    assert good == ("Success", 42)


# --- toLayerQueue --------------------------------------------------------------------------


def _take_three(client: StreamEntity) -> fx.Effect[list[int], Any]:
    results: list[int] = []
    return (
        client.watch()
        .take(3)
        .run_for_each(lambda n: fx.sync(lambda: results.append(n)))
        .as_(results)
    )


@testing.effect
def test_replies_to_a_streaming_rpc_with_a_stream():
    """replies to a streaming RPC with a Stream"""

    def behaviour(mailbox: Dequeue[Request[Any], Never], replier: Replier) -> fx.Effect[Never]:
        @fx.gen
        def loop():
            while True:
                request = yield from mailbox.take()
                yield from replier.succeed(request, stream.make(1, 2, 3))

        return loop

    @fx.gen
    def body():
        layer = StreamEntity.to_layer_queue(behaviour)
        make_client = yield from make_test_client(StreamEntity, layer)
        client = yield from make_client("entity-1")
        assert (yield from _take_three(client)) == [1, 2, 3]

    yield from body.pipe(fx.provide(test_sharding_config))


@testing.effect
def test_replies_to_a_streaming_rpc_with_a_dequeue():
    """replies to a streaming RPC with a Dequeue"""

    def behaviour(mailbox: Dequeue[Request[Any], Never], replier: Replier) -> fx.Effect[Never]:
        @fx.gen
        def loop():
            while True:
                request = yield from mailbox.take()
                queue = yield from Queue[int, Done].unbounded()
                yield from replier.succeed(request, queue)
                yield from queue.offer(1)
                yield from queue.offer(2)
                yield from queue.offer(3)
                yield from queue.end()

        return loop

    @fx.gen
    def body():
        layer = StreamEntity.to_layer_queue(behaviour)
        make_client = yield from make_test_client(StreamEntity, layer)
        client = yield from make_client("entity-1")
        assert (yield from _take_three(client)) == [1, 2, 3]

    yield from body.pipe(fx.provide(test_sharding_config))
