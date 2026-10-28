import pyfect as fx
from pyfect import schema as S


class Order(S.Class):
    sku: str
    quantity: int


# A schema error class is a TaggedError (catch_tag, yield it) that can also cross
# the wire: it encodes with its "_tag" like any tagged class.
class OutOfStock(S.TaggedError):
    sku: str


STOCK = {"apple": 3}
OrderJson = S.from_json_string(Order)


@fx.fn
def place(body: str):
    # decode_effect fails with SchemaError instead of raising, so it is in the type.
    order = yield from S.decode_effect(OrderJson)(body)
    if STOCK.get(order.sku, 0) < order.quantity:
        return (yield from OutOfStock(sku=order.sku))
    return f"placed {order.quantity} x {order.sku}"


# place(body) is an Effect[str, SchemaError | OutOfStock]; handling both leaves no error.
def handle(body: str) -> fx.Effect[str]:
    return (
        place(body)
        .pipe(fx.catch_tag(OutOfStock, lambda e: fx.succeed(f"409 {e.sku} is out of stock")))
        .pipe(fx.catch_tag(S.SchemaError, lambda e: fx.succeed(f"400 {e.message}")))
    )


for body in ['{"sku": "apple", "quantity": 2}', '{"sku": "apple", "quantity": 9}', "{}"]:
    print(fx.run_sync(handle(body)))

print(S.encode_sync(S.from_json_string(OutOfStock))(OutOfStock(sku="pear")))
