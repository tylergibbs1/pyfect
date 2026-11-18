from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.workflow import activity, workflow, workflow_engine


class Order(TypedDict):
    id: str
    amount: float


# Stands in for a payment provider that accepts an idempotency key, as most do: a request
# repeated with the same key returns the first charge instead of charging again.
charges: dict[str, str] = {}


def provider_charge(key: str, amount: float) -> str:
    if key not in charges:
        charges[key] = f"ch_{len(charges) + 1}"
        print(f"charged {amount} as {charges[key]}")
    return charges[key]


Pay = workflow.make(
    "Pay", payload=S.Struct(Order), success=S.String, idempotency_key=lambda o: o["id"]
)


@fx.fn
def charge_once(order: Order):
    # The same key on every run of this activity in this execution, so a rerun (after a
    # runner lost the workflow's shard) asks the provider for the charge it already made.
    key = yield from activity.idempotency_key("charge")
    return provider_charge(key, order["amount"])


@fx.fn
def pay(order: Order, _execution_id: str):
    return (yield from activity.make(name="charge", success=S.String, execute=charge_once(order)))


@fx.fn
def program():
    receipt = yield from Pay.execute({"id": "a1", "amount": 20})
    assert receipt == "ch_1" and len(charges) == 1


Payments = Pay.to_layer(pay).pipe(fx.layer.provide_merge(workflow_engine.layer_memory))
fx.run_main(program().pipe(fx.provide(Payments)))
