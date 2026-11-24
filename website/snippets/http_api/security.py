from collections.abc import Mapping
from typing import Never

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
    MiddlewareOptions,
    SecurityOptions,
    layer_client,
)
from pyfect.redacted import Redacted


class Caller(fx.Tag[str], key="example/Caller"):
    """Who sent the request."""


class Tokens(fx.Tag[Mapping[str, str]], key="example/Tokens"):
    """The known bearer tokens and whose they are."""


class Unauthorized(S.TaggedError, annotations={"http_api_status": 401}):
    message: str


class Forbidden(S.TaggedError, annotations={"http_api_status": 403}):
    message: str


# Provides a Caller, may fail with Unauthorized, needs Tokens, reads a bearer token.
class Authorization(
    HttpApiMiddleware[Caller, Unauthorized, Tokens],
    key="example/Authorization",
    security={"bearer": security.bearer},
):
    error = Unauthorized


# Provides nothing, may fail with Forbidden, needs the Caller.
class AdminOnly(HttpApiMiddleware[Never, Forbidden, Caller], key="example/AdminOnly"):
    error = Forbidden


# HttpApiGroup[Authorization] puts every endpoint behind it; .middleware(AdminOnly) one.
# A group's middleware runs outside an endpoint's own, so AdminOnly gets its Caller.
class Account(HttpApiGroup[Authorization], identifier="account"):
    whoami = endpoint.get("whoami", "/whoami", success=S.String)
    admin = endpoint.get("admin", "/admin", success=S.String).middleware(AdminOnly)


api = HttpApi.make("example").add(Account)

# The layer needs Authorization, AdminOnly and Tokens; the Caller comes from Authorization.
AccountLive = builder.group(
    api,
    Account,
    lambda handlers: handlers.handle_all(
        builder.entry(Account.whoami)(lambda _: Caller()),
        builder.entry(Account.admin)(lambda _: Caller().map(lambda name: f"welcome, {name}")),
    ),
)


# One function per security name: it gets the handler's effect and the decoded credential.
def bearer(
    handler: fx.Effect[HttpServerResponse, Unhandled, Caller], options: SecurityOptions
) -> fx.Effect[HttpServerResponse, Unhandled | Unauthorized, Tokens]:
    credential = options.credential

    def check(tokens: Mapping[str, str]) -> fx.Effect[HttpServerResponse, Unhandled | Unauthorized]:
        name = tokens.get(redacted.value(credential)) if isinstance(credential, Redacted) else None
        if name is None:
            return fx.fail(Unauthorized(message="a valid bearer token is needed"))
        return handler.pipe(fx.provide_service(Caller, name))

    return Tokens().flat_map(check)


def admin_only(
    handler: fx.Effect[HttpServerResponse, Unhandled], _: MiddlewareOptions
) -> fx.Effect[HttpServerResponse, Unhandled | Forbidden, Caller]:
    def check(name: str) -> fx.Effect[HttpServerResponse, Unhandled | Forbidden]:
        return handler if name == "ada" else fx.fail(Forbidden(message=f"{name} is no admin"))

    return Caller().flat_map(check)


AuthorizationLive = layer.succeed(Authorization, {"bearer": bearer})
AdminOnlyLive = layer.succeed(AdminOnly, admin_only)
TokensLive = layer.succeed(Tokens, {"ada-token": "ada", "bob-token": "bob"})
# What a middleware function needs comes from the group's layer, as a handler's does:
# Tokens is provided to AccountLive, not to AuthorizationLive.
ApiLive = builder.layer(api).pipe(
    layer.provide(
        AccountLive.pipe(layer.provide_merge(layer.merge(AuthorizationLive, AdminOnlyLive))).pipe(
            layer.provide(TokensLive)
        )
    )
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
    ada = yield from client.make(api).pipe(fx.provide(with_token("ada-token")))
    print("ada:", (yield from get_group(ada, Account).whoami()))
    print("ada, admin:", (yield from get_group(ada, Account).admin()))
    bob = yield from client.make(api).pipe(fx.provide(with_token("bob-token")))
    print("bob, admin:", repr((yield from get_group(bob, Account).admin().flip())))


served = router.serve(ApiLive, disable_logger=True, disable_listen_log=True)
fx.run_main(program().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
