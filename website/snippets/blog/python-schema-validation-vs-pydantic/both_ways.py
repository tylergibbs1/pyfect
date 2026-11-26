from datetime import datetime
from typing import Annotated, assert_type

from pyfect import schema as S
from pyfect.schema import transformation as T

# One codec, two directions: "12.34" on the wire, 1234 cents in Python.
Cents = S.NumberFromString.pipe(
    S.decode_to(S.Int, T.transform(decode=lambda n: round(n * 100), encode=lambda c: c / 100))
)


class Order(S.Class):
    id: Annotated[int, S.is_greater_than(0)]
    customer: str = S.field(S.Trim)
    total: int = S.field(Cents)
    placed_at: datetime = S.field(S.DateTimeUtcFromString)
    tags: tuple[str, ...] = ()


wire = {"id": 7, "customer": "  Ada ", "total": "12.34", "placed_at": "2026-11-24T09:30:00Z"}

order = S.decode_unknown_sync(Order)(wire)
assert_type(order, Order)
print(order)

# Encoding runs every codec backwards, to the same wire form.
print(S.encode_sync(Order)(order))

# The class is also a constructor, and it runs the same checks.
try:
    Order(id=0, customer="Grace", total=500, placed_at=order.placed_at)
except S.SchemaError as error:
    print(error.message)
