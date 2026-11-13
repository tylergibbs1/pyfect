"""``RpcGroupWith[M]`` is Effect's ``RpcGroup.middleware(M)``: it wraps every procedure
the group has, its own and the ones it merges (inherits), and a subclass's too, as
pyright types them. The served procedures and the wrapped ones are the same set."""

from collections.abc import Callable
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import effect, layer
from pyfect import schema as S
from pyfect.exit import Failure, Success
from pyfect.rpc import RpcGroup, RpcGroupWith, RpcMiddleware, make
from pyfect.rpc import test as rpc_test
from pyfect.rpc.middleware import ClientMiddlewareOptions, MiddlewareOptions, layer_client


class Unauthorized(S.TaggedError):
    pass


class Audited(S.TaggedError):
    pass


class Gate(RpcMiddleware[Never, Unauthorized], key="test/rpc-group-middleware/Gate"):
    error = Unauthorized


class Audit(RpcMiddleware[Never, Audited], key="test/rpc-group-middleware/Audit"):
    error = Audited


class Public(RpcGroup):
    ping = make("Public.ping", success=S.String)


class Posts(RpcGroup):
    count = make("Posts.count", success=S.String)


class Own(RpcGroupWith[Gate]):
    own = make("Own.own", success=S.String)


class Api(Public, RpcGroupWith[Gate]):
    own = make("Api.own", success=S.String)


class Admin(Api):
    drop = make("Admin.drop", success=S.String)


class Deep(Admin, Posts):
    deep = make("Deep.deep", success=S.String)


class Merged(Public, Posts):
    pass


class Nested(Merged, RpcGroupWith[Gate]):
    pass


class Twice(Api, RpcGroupWith[Gate]):
    twice = make("Twice.twice", success=S.String)


class Both(Public, RpcGroupWith[Gate | Audit]):
    both = make("Both.both", success=S.String)


GATED: list[type[RpcGroup]] = [Own, Api, Admin, Deep, Nested, Twice, Both]


def attribute_names(group: type[RpcGroup]) -> dict[str, str]:
    """Every RPC attribute a group has (its own and inherited), name -> tag."""
    return {
        name: getattr(group, name).tag
        for name in dir(group)
        if any(name in vars(klass) for klass in group.__mro__)
        and hasattr(getattr(group, name), "tag")
    }


def serve_all(
    group: type[RpcGroup],
    server: Callable[[Any, MiddlewareOptions], Any] | None = None,
    client: Callable[[ClientMiddlewareOptions], Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Calls every RPC attribute of ``group`` through a test client; the exits by
    attribute and the tags whose handler ran."""
    ran: list[str] = []
    handlers: Any = group.handlers()
    for tag, rpc in group.rpcs.items():

        def handler(_request: Any, tag: str = tag) -> Any:
            return fx.sync(lambda: ran.append(tag)).as_("ok")

        handlers = handlers.handle(rpc)(handler)

    def deny_all(_handler: Any, _options: MiddlewareOptions) -> Any:
        return fx.fail(Unauthorized())

    deny = server or deny_all
    served = group.to_layer(handlers).pipe(
        layer.provide(layer.merge(layer.succeed(Gate, deny), layer.succeed(Audit, deny)))
    )

    def body() -> Any:
        made: Any = yield from rpc_test.make_client(group, layer=served)
        exits: dict[str, Any] = {}
        for name in attribute_names(group):
            exits[name] = yield from getattr(made, name)(None).exit()
        return exits

    run: Any = fx.scoped(effect.gen(body))
    if client is not None:
        run = run.pipe(
            fx.provide(layer.merge(layer_client(Gate, client), layer_client(Audit, client)))
        )
    return fx.run_blocking(run), ran


@pytest.mark.parametrize("group", GATED, ids=lambda g: g.__name__)
def test_a_deny_all_group_middleware_denies_every_procedure(group: type[RpcGroup]) -> None:
    exits, ran = serve_all(group)
    assert ran == []
    assert exits
    for name, exit in exits.items():
        assert isinstance(exit, Failure), name


def test_a_merged_procedure_is_denied_through_the_merging_group_only() -> None:
    exits, ran = serve_all(Public)
    assert isinstance(exits["ping"], Success)
    assert ran == ["Public.ping"]


@pytest.mark.parametrize("group", GATED, ids=lambda g: g.__name__)
def test_the_server_middleware_runs_for_every_procedure(group: type[RpcGroup]) -> None:
    seen: list[str] = []

    def record(handler: Any, options: MiddlewareOptions) -> Any:
        seen.append(options.rpc.tag)
        return handler

    exits, ran = serve_all(group, server=record)
    tags = set(attribute_names(group).values())
    assert set(seen) >= tags
    assert set(ran) == tags
    assert all(isinstance(exit, Success) for exit in exits.values())


@pytest.mark.parametrize("group", GATED, ids=lambda g: g.__name__)
def test_the_client_middleware_runs_for_every_procedure(group: type[RpcGroup]) -> None:
    seen: list[str] = []

    def record(options: ClientMiddlewareOptions) -> Any:
        seen.append(options.rpc.tag)
        return options.next(options.request)

    serve_all(group, server=lambda handler, _options: handler, client=record)
    assert set(seen) == set(attribute_names(group).values())


def test_a_union_is_each_middleware_in_order() -> None:
    # RpcGroup.middleware(Gate).middleware(Audit)
    assert Both.rpcs["Public.ping"].middlewares == (Gate, Audit)
    assert Both.rpcs["Both.both"].middlewares == (Gate, Audit)


def test_a_group_middleware_comes_after_the_procedure_s_own() -> None:
    class Guarded(RpcGroup):
        guarded = make("Guarded.guarded", success=S.String).middleware(Audit)

    class Wrapped(Guarded, RpcGroupWith[Gate]):
        pass

    assert Wrapped.rpcs["Guarded.guarded"].middlewares == (Audit, Gate)
    assert Guarded.rpcs["Guarded.guarded"].middlewares == (Audit,)


def test_a_procedure_added_after_the_middleware_is_not_wrapped() -> None:
    # RpcGroup.make(own).middleware(Gate).add(extra): re-export the wrapped RPC in a
    # group without the middleware.
    class Extended(RpcGroup):
        own = Api.own
        extra = make("Extended.extra", success=S.String)

    assert Extended.rpcs["Api.own"].middlewares == (Gate,)
    assert Extended.rpcs["Extended.extra"].middlewares == ()
    exits, ran = serve_all(Extended)
    assert isinstance(exits["own"], Failure)
    assert isinstance(exits["extra"], Success)
    assert ran == ["Extended.extra"]


def test_two_different_group_middlewares_are_refused() -> None:
    # Pyright rejects the bases too (RpcGroupWith[Gate] and RpcGroupWith[Audit]).
    with pytest.raises(TypeError, match="RpcGroupWith"):

        class Mixed(Api, RpcGroupWith[Audit]):  # pyright: ignore[reportGeneralTypeIssues]
            pass

        del Mixed


def test_a_group_middleware_must_be_a_middleware_class() -> None:
    with pytest.raises(TypeError, match="RpcGroupWith"):

        class NotOne(RpcGroupWith[int]):
            pass

        del NotOne


@pytest.mark.parametrize("group", [Public, Posts, Merged, *GATED], ids=lambda g: g.__name__)
def test_every_rpc_attribute_is_the_procedure_served(group: type[RpcGroup]) -> None:
    # The guard: for every shape of group, an RPC attribute (what pyright types,
    # what handlers are given for) is the served procedure, middleware and all.
    names = attribute_names(group)
    assert set(names.values()) == set(group.rpcs)
    for name, tag in names.items():
        assert getattr(group, name) is group.rpcs[tag], name
