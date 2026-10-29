from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.workflow import (
    activity,
    durable_clock,
    durable_deferred,
    workflow,
    workflow_engine,
)


class Order(TypedDict):
    id: str
    amount: float


# A workflow names its payload, result and error, and how to tell executions apart.
PlaceOrder = workflow.make(
    "PlaceOrder",
    payload=S.Struct(Order),
    success=S.String,
    error=S.String,
    idempotency_key=lambda order: order["id"],
)

# A named wait point, completed from outside the workflow by its token.
Approval = durable_deferred.make("approval", success=S.Boolean)


def charge(order: Order) -> fx.Effect[str]:
    def run() -> str:
        print(f"charge {order['id']}")
        return f"ch_{order['id']}"

    return fx.sync(run)


def refund(charge_id: str) -> fx.Effect[None]:
    return fx.sync(lambda: print(f"refund {charge_id}"))


@fx.fn
def place_order(order: Order, _execution_id: str):
    # An activity's result is stored: a replay reads it back instead of charging again.
    charge_id = yield from activity.make(
        name="charge", success=S.String, execute=charge(order)
    ).pipe(PlaceOrder.with_compensation(lambda charge_id, _cause: refund(charge_id)))
    yield from durable_clock.sleep(name="cool-off", duration=0.01)
    approved = yield from Approval.wait()  # suspends until someone answers
    if not approved:
        return (yield from fx.fail("rejected"))  # runs the compensation: a refund
    return charge_id


Orders = PlaceOrder.to_layer(place_order).pipe(fx.layer.provide_merge(workflow_engine.layer_memory))


@fx.fn
def decide(order: Order, approved: bool):
    running = yield from PlaceOrder.execute(order).exit().fork()
    # The answer is stored durably, so it may arrive before the workflow waits for it.
    token = yield from Approval.token_from_payload(workflow=PlaceOrder, payload=order)
    yield from Approval.succeed(token=token, value=approved)
    print(order["id"], (yield from running.join()))


@fx.fn
def program():
    yield from decide({"id": "a1", "amount": 20}, approved=True)
    yield from decide({"id": "b2", "amount": 35}, approved=False)


fx.run_main(program().pipe(fx.provide(Orders)))
