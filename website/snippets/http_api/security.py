import pyfect as fx
from pyfect import layer, redacted
from pyfect import schema as S
from pyfect.http import router, uvicorn_server
from pyfect.http.router import Unhandled
from pyfect.http.server_response import HttpServerResponse
from pyfect.http_api import (
    HttpApi,
    HttpApiGroup,
    builder,
    client,
    endpoint,
    get_group,
    security,
)
from pyfect.http_api.middleware import (
    ClientMiddlewareOptions,
    HttpApiMiddleware,
    SecurityOptions,
    layer_client,
)
from pyfect.redacted import Redacted


class Caller(fx.Tag[str], key="example/Caller"):
    """Who sent the request."""


class Unauthorized(S.TaggedError, annotations={"http_api_status": 401}):
    message: str


# Provides a Caller to the handlers, may fail with Unauthorized, reads a bearer token.
class Authorization(
    HttpApiMiddleware[Caller, Unauthorized],
    key="example/Authorization",
    security={"bearer": security.bearer},
):
    error = Unauthorized


# HttpApiGroup[Authorization]: every endpoint of the group goes through it.
class Account(HttpApiGroup[Authorization], identifier="account"):
    whoami = endpoint.get("whoami", "/whoami", success=S.String)


api = HttpApi.make("example").add(Account)

AccountLive = builder.group(
    api, Account, lambda handlers: handlers.handle(Account.whoami)(lambda _: Caller())
)

tokens = {"secret-token": "ada"}


# One function per security name: it gets the handler's effect and the decoded credential.
def bearer(
    handler: fx.Effect[HttpServerResponse, Unhandled, Caller], options: SecurityOptions
) -> fx.Effect[HttpServerResponse, Unhandled | Unauthorized]:
    credential = options.credential
    name = tokens.get(redacted.value(credential)) if isinstance(credential, Redacted) else None
    if name is None:
        return fx.fail(Unauthorized(message="a valid bearer token is needed"))
    return handler.pipe(fx.provide_service(Caller, name))


AuthorizationLive = layer.succeed(Authorization, {"bearer": bearer})
ApiLive = builder.layer(api).pipe(
    layer.provide(AccountLive.pipe(layer.provide_merge(AuthorizationLive)))
)


# The client side: a client middleware adds the token to every request of the group.
def with_token(token: str):
    def send(options: ClientMiddlewareOptions):
        return options.next(options.request.bearer_token(token))

    return layer_client(Authorization, send)


@fx.fn
def program():
    anonymous = yield from client.make(api)
    refused = yield from get_group(anonymous, Account).whoami().flip()
    print("without a token:", repr(refused))
    authed = yield from client.make(api).pipe(fx.provide(with_token("secret-token")))
    print("with a token:", (yield from get_group(authed, Account).whoami()))


served = router.serve(ApiLive, disable_logger=True, disable_listen_log=True)
fx.run_main(program().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
