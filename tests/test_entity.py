"""``Entity`` at its boundary, past Effect's ``Entity.test.ts``
(``tests/oracle/test_entity.py``): a queue-based entity whose behaviour
fails, and the checks ``to_layer`` and ``handle`` make."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import sharding_config
from pyfect.cluster.entity import Entity, Replier, Request, make_test_client
from pyfect.queue import Dequeue
from pyfect.rpc import make as make_rpc

_config = sharding_config.layer(replace(sharding_config.DEFAULTS, shards_per_group=300))


class Mailbox(Entity, type="Mailbox"):
    ask = make_rpc("Ask", success=S.Int)
    other = make_rpc("Other", success=S.Int)


class Boom(Exception):
    pass


@testing.effect
def test_a_failing_queue_behaviour_fails_the_waiting_requests():
    def behaviour(mailbox: Dequeue[Request[Any], Never], _: Replier) -> fx.Effect[Never]:
        return mailbox.take().and_then(fx.die(Boom("behaviour failed")))

    @fx.gen
    def body():
        make_client = yield from make_test_client(Mailbox, Mailbox.to_layer_queue(behaviour))
        client = yield from make_client("1")
        exit = yield from client.ask().exit()
        assert isinstance(exit, Exit.Failure)
        assert isinstance(exit.cause.squash(), Boom)

    yield from body.pipe(fx.provide(_config))


def test_to_layer_rejects_missing_handlers():
    handlers = Mailbox.handlers().handle(Mailbox.ask)(lambda _: fx.succeed(1))
    with pytest.raises(ValueError, match="no handler for Other"):
        Mailbox.to_layer(handlers)


def test_handle_rejects_an_rpc_of_another_entity():
    foreign = make_rpc("Foreign")
    with pytest.raises(ValueError, match="not an RPC of the entity Mailbox"):
        Mailbox.handlers().handle(foreign)


def _both_handlers():
    return (
        Mailbox.handlers()
        .handle(Mailbox.ask)(lambda _: fx.succeed(1))
        .handle(Mailbox.other)(lambda _: fx.succeed(2))
    )


@pytest.mark.parametrize("concurrency", [0, -1])
@testing.effect
def test_a_concurrency_below_one_never_runs_a_request(concurrency: int):
    """Effect's ``RpcServer`` makes a semaphore of that many permits, so a
    request waits for one. Printed by Effect under Node."""

    @fx.gen
    def body():
        make_client = yield from make_test_client(
            Mailbox, Mailbox.to_layer(_both_handlers(), concurrency=concurrency)
        )
        client = yield from make_client("1")
        fiber = yield from client.ask().fork()
        yield from testing.adjust("1 second")
        assert fiber.poll_unsafe() is None

    yield from body.pipe(fx.provide(_config))


@pytest.mark.parametrize("capacity", [0, -1])
@testing.effect
def test_the_test_client_runs_a_request_at_any_mailbox_capacity(capacity: int):
    """Printed by Effect under Node: only the sharding reads the limit."""

    @fx.gen
    def body():
        make_client = yield from make_test_client(
            Mailbox, Mailbox.to_layer(_both_handlers(), mailbox_capacity=capacity)
        )
        client = yield from make_client("1")
        assert (yield from client.ask()) == 1

    yield from body.pipe(fx.provide(_config))
