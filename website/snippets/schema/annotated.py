from typing import Annotated, TypedDict

from pyfect import schema as S

# A check in an annotation's metadata runs when decoding, and when constructing a class.
type Quantity = Annotated[int, S.is_between(minimum=1, maximum=99)]


class Line(TypedDict):
    sku: Annotated[str, S.is_min_length(1)]
    quantity: Quantity


class Stock(S.Class):
    sku: str
    on_hand: Annotated[int, S.is_greater_than_or_equal_to(0)]
    reorder_at: list[Quantity]


decode = S.decode_unknown_sync(S.Struct(Line))
assert decode({"sku": "apple", "quantity": 2}) == {"sku": "apple", "quantity": 2}

for bad in [{"sku": "", "quantity": 2}, {"sku": "apple", "quantity": 100}]:
    try:
        decode(bad)
    except S.SchemaError as error:
        print(error.message)

try:
    Stock(sku="apple", on_hand=-1, reorder_at=[5])
except S.SchemaError as error:
    print(error.message)
