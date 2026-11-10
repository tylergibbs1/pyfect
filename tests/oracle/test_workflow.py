"""Ports of Effect's ``test/workflow/Workflow.test.ts``.

Each test's docstring is the Effect test title. Effect's test pauses the
fiber with a custom ``Scheduler.shouldYield`` once the activity is
registered, then interrupts it. The port
sweeps ``MaxOpsBeforeYield`` budgets, interrupting the paused fiber each
time, and checks that some budget lands the pause between the acquisition
and the body.
"""

from __future__ import annotations

import functools
from typing import TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.crypto import web_crypto
from pyfect.workflow import activity, workflow
from pyfect.workflow.workflow_engine import WorkflowInstance, WorkflowInstanceService

BUDGETS = range(1, 40)


class Empty(TypedDict):
    pass


_order = workflow.make("Order", payload=S.Struct(Empty), idempotency_key=lambda _: "42")


@testing.effect
def test_keep_their_sha_256_derived_values():
    """persisted ids / keep their SHA-256 derived values"""
    execution_id = yield from _order.execution_id({})
    assert execution_id == "0f62355133496e612090fb5d4307a4d2"
    instance = WorkflowInstanceService.initial(_order, execution_id)
    key = activity.idempotency_key("charge").pipe(fx.provide_service(WorkflowInstance, instance))
    assert (yield from key) == "c250939b26740218d8122b4cf6a3d2e1"
    with_attempt = (
        activity.idempotency_key("charge", include_attempt=True)
        .pipe(fx.provide_service(WorkflowInstance, instance))
        .pipe(fx.provide_service(activity.CurrentAttempt, 3))
    )
    assert (yield from with_attempt) == "26241ff2cf66bbddd1be618b7ccdf48f"


class _FixedSubtle:
    def digest(self, algorithm: web_crypto.AlgorithmIdentifier, data: bytes) -> bytes:
        assert algorithm == "SHA-256"
        return bytes(range(32))


class _FixedCrypto:
    subtle = _FixedSubtle()

    def get_random_values(self, array: memoryview, /) -> memoryview:
        return array


@testing.effect
def test_persisted_ids_hash_on_the_web_crypto_reference():
    """Not an Effect title: as in Effect 4.1.2's ``internal/crypto.ts``, execution ids and
    idempotency keys digest on the ``WebCrypto`` reference."""
    execution_id = yield from _order.execution_id({}).pipe(
        fx.provide_service(web_crypto.WebCrypto, cast("web_crypto.Crypto", _FixedCrypto()))
    )
    assert execution_id == bytes(range(16)).hex()


@testing.effect
def test_releases_acquisition_interrupted_before_the_body_starts():
    """Workflow.wrapActivityResult / releases acquisition interrupted before the body starts"""
    wf = workflow.make(
        "ActivityInterruption",
        payload=S.Struct(Empty),
        idempotency_key=lambda _: "activity-interruption",
    )
    interrupted_before_body = 0
    for budget in BUDGETS:
        instance = WorkflowInstanceService.initial(wf, "acquisition")
        entered: list[bool] = []
        fiber = (
            yield from workflow.wrap_activity_result(
                fx.sync(functools.partial(entered.append, True)), lambda _: False
            )
            .pipe(fx.provide_service(WorkflowInstance, instance))
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            .fork(start_immediately=True)
        )
        paused_registered = instance.activity_state.count == 1
        yield from fiber.interrupt()
        ex = yield from fiber.await_exit()
        if paused_registered and not entered:
            interrupted_before_body += 1
            assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
            # The acquisition was released: the latch it closed is open again.
            yield from instance.activity_state.latch.wait()
        assert instance.activity_state.count == 0
    assert interrupted_before_body > 0, "no budget paused between acquisition and body"
