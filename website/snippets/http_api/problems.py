from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.http import client as http_client
from pyfect.http import router, uvicorn_server
from pyfect.http_api import HttpApi, HttpApiGroup, builder, client, endpoint, error, get_group
from pyfect.http_api import middleware as mw


# A typed RFC 9457 problem: its type, status and title are fixed, its fields are extensions.
class OutOfCredit(
    error.Problem,
    type="https://example.com/probs/out-of-credit",
    status=403,
    title="You do not have enough credit.",
):
    balance: float


class Page(TypedDict):
    page: int


class Shop(HttpApiGroup, identifier="shop"):
    purchase = endpoint.post(
        "purchase", "/purchase", query=S.Struct(Page), success=S.String, error=OutOfCredit
    )


# The ProblemDetails middleware answers schema errors with problems too.
api = HttpApi.make("shop").add(Shop).middleware(mw.ProblemDetails)

ShopLive = builder.group(
    api,
    Shop,
    lambda handlers: handlers.handle(Shop.purchase)(
        lambda _: fx.fail(OutOfCredit(balance=30, detail="Your balance is 30."))
    ),
)
ApiLive = (
    builder.layer(api)
    .pipe(layer.provide(ShopLive))
    .pipe(layer.provide(mw.layer_problem_details(include_details=True)))
)


@fx.fn
def program():
    shop = get_group((yield from client.make(api)), Shop)
    problem = yield from shop.purchase(query={"page": 1}).flip()
    print(repr(problem))
    raw = yield from shop.purchase.response_only(query={"page": 1})
    print(raw.status, raw.headers["content-type"], (yield from raw.text))
    invalid = yield from http_client.post("/purchase?page=first")
    print(invalid.status, (yield from invalid.text))


served = router.serve(ApiLive, disable_logger=True, disable_listen_log=True)
fx.run_main(program().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
