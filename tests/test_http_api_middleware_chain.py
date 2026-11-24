"""Middleware wrap in the order they are added, each outside the last, and a group's
middleware wraps outside an endpoint's own: what an outer middleware provides reaches the
inner ones (pyfect's ``_apply_middleware``, Effect's ``applyMiddleware``). The group layer
needs only what nothing outside provides (Effect's ``ApplyServices``), whether its
handlers come from ``handle`` or ``handle_all``."""

from typing import Any, Never, assert_type

from oracle._http_api import api_layer, run_served

import pyfect as fx
from pyfect import effect, layer
from pyfect import schema as S
from pyfect.context import Tag
from pyfect.http import client as http_client
from pyfect.http_api import builder
from pyfect.http_api import endpoint as ep
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware, MiddlewareOptions


class Session(Tag[str], key="test/MiddlewareChain/Session"): ...


class Other(Tag[str], key="test/MiddlewareChain/Other"): ...


class CurrentUser(Tag[str], key="test/MiddlewareChain/CurrentUser"): ...


class Outer(HttpApiMiddleware[Session], key="test/MiddlewareChain/Outer"):
    """Provides Session."""


class Inner(HttpApiMiddleware[CurrentUser, Never, Session], key="test/MiddlewareChain/Inner"):
    """Needs Session, provides CurrentUser."""


class NeedsBoth(
    HttpApiMiddleware[CurrentUser, Never, Session | Other], key="test/MiddlewareChain/NeedsBoth"
):
    """Needs Session and Other, provides CurrentUser."""


def _outer(
    handler: fx.Effect[Any, Any, Any], _options: MiddlewareOptions
) -> fx.Effect[Any, Any, Any]:
    return handler.pipe(fx.provide_service(Session, "s1"))


def _inner(
    handler: fx.Effect[Any, Any, Any], _options: MiddlewareOptions
) -> fx.Effect[Any, Any, Any]:
    return Session().flat_map(lambda s: handler.pipe(fx.provide_service(CurrentUser, f"user-{s}")))


def _needs_both(
    handler: fx.Effect[Any, Any, Any], _options: MiddlewareOptions
) -> fx.Effect[Any, Any, Any]:
    def with_session(s: str) -> fx.Effect[Any, Any, Any]:
        return Other().flat_map(
            lambda o: handler.pipe(fx.provide_service(CurrentUser, f"user-{s}-{o}"))
        )

    return Session().flat_map(with_session)


def _get(path: str) -> Any:
    def program() -> Any:
        response = yield from http_client.get(path)
        return response.status, (yield from response.text)

    return effect.gen(program)


class Chain(HttpApiGroup, identifier="chain"):
    me = ep.get("me", "/me", success=S.String).middleware(Inner).middleware(Outer)


_CHAIN = HttpApi.make("chain").add(Chain)
_CHAIN_MIDDLEWARE = layer.merge(layer.succeed(Outer, _outer), layer.succeed(Inner, _inner))
_CHAIN_BY_ENTRY = builder.group(
    _CHAIN, Chain, lambda h: h.handle_all(builder.entry(Chain.me)(lambda _r: CurrentUser()))
)
_CHAIN_BY_HANDLE = builder.group(
    _CHAIN, Chain, lambda h: h.handle(Chain.me)(lambda _r: CurrentUser())
)


def test_an_outer_middleware_provides_to_the_inner_one_so_the_layer_does_not_need_it() -> None:
    assert_type(_CHAIN_BY_ENTRY, fx.Layer[Chain, Never, Outer | Inner])
    assert_type(_CHAIN_BY_HANDLE, fx.Layer[Chain, Never, Outer | Inner])
    for group in (_CHAIN_BY_ENTRY, _CHAIN_BY_HANDLE):
        app = api_layer(_CHAIN, group, _CHAIN_MIDDLEWARE)
        assert run_served(app, _get("/me")) == (200, '"user-s1"')


class Swapped(HttpApiGroup, identifier="swapped"):
    me = ep.get("me", "/me", success=S.String).middleware(Outer).middleware(Inner)


_SWAPPED = HttpApi.make("swapped").add(Swapped)
_SWAPPED_BY_ENTRY = builder.group(
    _SWAPPED, Swapped, lambda h: h.handle_all(builder.entry(Swapped.me)(lambda _r: CurrentUser()))
)


def test_added_the_other_way_round_the_inner_one_runs_outside_and_the_layer_needs_it() -> None:
    assert_type(_SWAPPED_BY_ENTRY, fx.Layer[Swapped, Never, Outer | Inner | Session])
    without_session = api_layer(_SWAPPED, _SWAPPED_BY_ENTRY, _CHAIN_MIDDLEWARE)
    assert run_served(without_session, _get("/me")) == (500, "")
    with_session = api_layer(
        _SWAPPED, _SWAPPED_BY_ENTRY, _CHAIN_MIDDLEWARE, layer.succeed(Session, "s2")
    )
    assert run_served(with_session, _get("/me")) == (200, '"user-s2"')


class Guarded(HttpApiGroup[Outer], identifier="guarded"):
    me = ep.get("me", "/me", success=S.String).middleware(NeedsBoth)


_GUARDED = HttpApi.make("guarded").add(Guarded)
_GUARDED_MIDDLEWARE = layer.merge(
    layer.succeed(Outer, _outer), layer.succeed(NeedsBoth, _needs_both)
)
_GUARDED_BY_ENTRY = builder.group(
    _GUARDED, Guarded, lambda h: h.handle_all(builder.entry(Guarded.me)(lambda _r: CurrentUser()))
)
_GUARDED_BY_HANDLE = builder.group(
    _GUARDED, Guarded, lambda h: h.handle(Guarded.me)(lambda _r: CurrentUser())
)


def test_the_group_middleware_provides_to_the_endpoint_one_with_handle_and_handle_all() -> None:
    assert_type(_GUARDED_BY_ENTRY, fx.Layer[Guarded, Never, Outer | NeedsBoth | Other])
    assert_type(_GUARDED_BY_HANDLE, fx.Layer[Guarded, Never, Outer | NeedsBoth | Other])
    for group in (_GUARDED_BY_ENTRY, _GUARDED_BY_HANDLE):
        app = api_layer(_GUARDED, group, _GUARDED_MIDDLEWARE, layer.succeed(Other, "o"))
        assert run_served(app, _get("/me")) == (200, '"user-s1-o"')


def test_what_no_middleware_provides_is_still_needed() -> None:
    app = api_layer(_GUARDED, _GUARDED_BY_HANDLE, _GUARDED_MIDDLEWARE)
    assert run_served(app, _get("/me")) == (500, "")
