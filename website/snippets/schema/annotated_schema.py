from typing import Annotated

from pyfect import schema as S

# A schema in the metadata is the field's schema, in place of the type's own.
type Positive = Annotated[int, S.Int.check(S.is_greater_than(0))]


class Order(S.Class):
    amount: Positive
    # A codec: a float in Python, its text on the wire.
    total: Annotated[float, S.FiniteFromString]
    # Checks beside a schema refine it.
    note: Annotated[str, S.String, S.is_max_length(10)] = ""


order = S.decode_unknown_sync(Order)({"amount": 2, "total": "9.5"})
assert order == Order(amount=2, total=9.5)
print(S.encode_sync(Order)(order))

for bad in [{"amount": 0, "total": "1"}, {"amount": 1, "total": "1", "note": "far too long"}]:
    try:
        S.decode_unknown_sync(Order)(bad)
    except S.SchemaError as error:
        print(error.message)

try:
    Order(amount=-1, total=1.0)
except S.SchemaError as error:
    print(error.message)
