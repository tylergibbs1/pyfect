from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.testing import explore
from pyfect.workflow import activity, workflow, workflow_engine


class Order(TypedDict):
    id: str
    amount: int


class Payments:
    """A payment provider that, like most, dedupes requests by an idempotency key."""

    def __init__(self) -> None:
        self.charged: list[int] = []
        self.keys: set[str] = set()

    def charge(self, amount: int, key: str | None) -> None:
        if key is not None and key in self.keys:
            return
        if key is not None:
            self.keys.add(key)
        self.charged.append(amount)


class PaymentsService(fx.Tag[Payments]): ...


Checkout = workflow.make(
    "Checkout", payload=S.Struct(Order), success=S.String, idempotency_key=lambda o: o["id"]
)


def checkout(*, with_key: bool):
    def run(order: Order, _execution_id: str) -> fx.Effect[str, Any, Any]:
        @fx.gen
        def charge():
            payments = yield from PaymentsService()
            key = yield from activity.idempotency_key("charge")
            payments.charge(order["amount"], key if with_key else None)

        @fx.gen
        def body():
            yield from activity.make(name="charge", execute=charge)
            yield from activity.make(name="ship", execute=fx.void)
            return f"order {order['id']} done"

        return body

    # Built afresh for every crash point: a new engine and a new provider.
    return (
        Checkout.to_layer(run)
        .pipe(fx.layer.provide_merge(workflow_engine.layer_memory))
        .pipe(fx.layer.provide_merge(fx.layer.sync(PaymentsService, Payments)))
    )


def paid_once(_: fx.Exit[str, Any]) -> fx.Effect[str | None, Any, PaymentsService]:
    def judge(payments: Payments) -> str | None:
        return None if payments.charged == [30] else f"charged {payments.charged}"

    return PaymentsService().map(judge)


@testing.effect
def test_a_charge_without_a_key_runs_twice_after_a_crash():
    order: Order = {"id": "o-1", "amount": 30}
    crashes = explore.activity_crashes(
        Checkout, order, layer=checkout(with_key=False), check=paid_once
    )
    failure = yield from crashes.flip()
    # The run stopped after the charge ran but before its result was stored,
    # so the resumed run charged again.
    assert failure.point == explore.CrashPoint(1, "charge", stored=False)
    assert failure.problem == "charged [30, 30]"


@testing.effect
def test_the_idempotency_key_survives_every_crash():
    order: Order = {"id": "o-1", "amount": 30}
    report = yield from explore.activity_crashes(
        Checkout, order, layer=checkout(with_key=True), check=paid_once
    )
    assert len(report.points) == 4  # charge and ship, each before and after it was stored
