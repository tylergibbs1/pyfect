"""Decoding and encoding an API payload with a schema, with typed errors.
Run with: uv run examples/schema.py

A request body (JSON text) is decoded into a typed ``CreateOrder``: the
schema parses the JSON and checks every field. A bad body fails with
``SchemaError``, an unknown product with ``UnknownProduct``; each error is
a type the effect says it can fail with, and the handler turns each into a
response. The response is encoded back
to JSON text with the same kind of schema."""

from dataclasses import dataclass
from typing import TypedDict

import pyfect as fx
from pyfect import schema as S

# --- the payloads -------------------------------------------------------------------


class Line(TypedDict):
    sku: str
    quantity: int


class CreateOrder(TypedDict):
    customer: str
    lines: tuple[Line, ...]


# A quantity must be a whole number from 1 to 99.
Quantity = S.Int.check(S.is_between(minimum=1, maximum=99))

Request = S.from_json_string(
    S.Struct(
        CreateOrder,
        customer=S.NonEmptyString,
        lines=S.NonEmptyArray(S.Struct(Line, quantity=Quantity)),
    )
)


class Receipt(S.Class):
    order_id: str
    total: float


Response = S.from_json_string(Receipt)


# --- the domain ---------------------------------------------------------------------

PRICES = {"apple": 0.5, "pear": 0.75}


@dataclass
class UnknownProduct(fx.TaggedError):
    sku: str


def price(line: Line) -> fx.Effect[float, UnknownProduct]:
    unit = PRICES.get(line["sku"])
    if unit is None:
        return fx.fail(UnknownProduct(line["sku"]))
    return fx.succeed(unit * line["quantity"])


def create_order(body: str) -> fx.Effect[str, S.SchemaError | UnknownProduct]:
    @fx.gen
    def program():
        order = yield from S.decode_effect(Request)(body)
        prices = yield from fx.for_each(order["lines"], price)
        receipt = Receipt(order_id=f"{order['customer']}-1", total=sum(prices))
        return (yield from S.encode_effect(Response)(receipt))

    return program


# --- the handler: every error the effect can fail with becomes a response ----------


def handle(body: str) -> fx.Effect[str]:
    return (
        create_order(body)
        .map(lambda text: f"201 {text}")
        .pipe(fx.catch_tag(UnknownProduct, lambda e: fx.succeed(f"404 unknown product {e.sku}")))
        .pipe(fx.catch_tag(S.SchemaError, lambda e: fx.succeed(f"400 {e.message!r}")))
    )


BODIES = [
    '{"customer": "ada", "lines": [{"sku": "apple", "quantity": 2}]}',
    '{"customer": "ada", "lines": [{"sku": "plum", "quantity": 1}]}',
    '{"customer": "ada", "lines": [{"sku": "apple", "quantity": 1.5}]}',
    '{"customer": "", "lines": []}',
    "not json",
]

if __name__ == "__main__":
    for body in BODIES:
        print(fx.run_blocking(handle(body)))
