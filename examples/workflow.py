"""Run a durable order workflow with retry, compensation, and approval.

Run with: ``uv run examples/workflow.py``.
"""

from typing import TypedDict

import pyfect as fx
from pyfect import schedule, schema
from pyfect.workflow import activity, durable_deferred, workflow, workflow_engine


class OrderPayload(TypedDict):
    id: str


PlaceOrder = workflow.make(
    "PlaceOrder",
    payload=schema.Struct(OrderPayload),
    success=schema.String,
    error=schema.String,
    idempotency_key=lambda order: order["id"],
)
Approval = durable_deferred.make("approval", success=schema.Boolean)

attempts = [0]


def reserve(order: OrderPayload) -> fx.Effect[str]:
    return fx.sync(lambda: print(f"reserved {order['id']}") or f"reservation-{order['id']}")


def charge(order: OrderPayload) -> fx.Effect[str]:
    def run() -> str:
        attempts[0] += 1
        if attempts[0] == 1:
            print("charge failed; retrying")
            raise RuntimeError("temporary payment failure")
        print(f"charged {order['id']}")
        return f"charge-{order['id']}"

    return fx.try_(run, str).retry(schedule=schedule.exponential("1 millis"), times=2).or_die()


def compensate(reservation_id: str, charge_id: str) -> fx.Effect[None]:
    return fx.sync(lambda: print(f"refunded {charge_id}; released {reservation_id}"))


@fx.fn
def place_order(order: OrderPayload, _execution_id: str):
    reservation_id = yield from activity.make(
        name="reserve", success=schema.String, execute=reserve(order)
    )
    charge_id = yield from activity.make(
        name="charge", success=schema.String, execute=charge(order)
    ).pipe(
        PlaceOrder.with_compensation(
            lambda charge_id, _cause: compensate(reservation_id, charge_id)
        )
    )
    yield from activity.make(name="ship", success=schema.String, execute=fx.succeed("shipment"))
    approved = yield from Approval.wait()
    if not approved:
        return (yield from fx.fail("approval rejected"))
    return charge_id


Orders = PlaceOrder.to_layer(place_order).pipe(fx.layer.provide_merge(workflow_engine.layer_memory))


@fx.fn
def program():
    order: OrderPayload = {"id": "order-1"}
    running = yield from PlaceOrder.execute(order).exit().fork()
    token = yield from Approval.token_from_payload(workflow=PlaceOrder, payload=order)
    yield from Approval.succeed(token=token, value=False)
    yield from running.join()


fx.run_main(program().pipe(fx.provide(Orders)))
