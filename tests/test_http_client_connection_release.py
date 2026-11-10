"""A response releases its connection when the program drops it, whatever
wraps the request: every client combinator and the effect combinators that
sit between a request and its use, with the body read and unread, leave no
socket open (DOGFOOD beacon #14: ``http.get(url).timeout(10).map(status)``
kept one socket per call)."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from _connection_release import Send, open_after

import pyfect as fx
from pyfect import byte_size
from pyfect.http import client as c
from pyfect.http import cookies
from pyfect.http import response as res
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.persistence import circuit_breaker as cb
from pyfect.persistence import rate_limiter as rl
from pyfect.ref import Ref
from pyfect.schedule import recurs

type Client = HttpClientService[HttpClientError]
type Sending = fx.Effect[HttpClientResponse, Any, Any]


def _limited(client: Client, url: str) -> Sending:
    return rl.RateLimiter().flat_map(
        lambda limiter: client.with_rate_limiter(
            limiter=limiter, window="1 minute", limit=1000, key="k"
        ).get(f"{url}/")
    )


def _breaker(client: Client, url: str) -> Sending:
    return cb.make(trip_policy=cb.consecutive(1000), open_duration="1 minute").flat_map(
        lambda breaker: client.with_circuit_breaker(breaker=breaker).get(f"{url}/")
    )


def _cookies(client: Client, url: str) -> Sending:
    return (
        Ref[tuple[cookies.Cookie, ...]]
        .make(())
        .flat_map(lambda ref: client.with_cookies_ref(ref).get(f"{url}/"))
    )


def _ok(r: HttpClientResponse) -> fx.Effect[HttpClientResponse]:
    return fx.succeed(r)


_CLIENT_CASES: dict[str, Send] = {
    "transform": lambda client, url: client.transform(lambda s, _r: s.timeout("10 seconds")).get(
        f"{url}/"
    ),
    "timeout": lambda client, url: client.timeout("10 seconds").get(f"{url}/"),
    "transform_response": lambda client, url: client.pipe(
        c.transform_response(lambda s: s.timeout("10 seconds"))
    ).get(f"{url}/"),
    "filter_or_else": lambda client, url: client.filter_or_else(lambda r: r.status == 200, _ok).get(
        f"{url}/error"
    ),
    "filter_or_fail": lambda client, url: client.filter_or_fail(
        lambda r: r.status == 200, lambda r: r.status
    ).get(f"{url}/error"),
    "filter_status": lambda client, url: client.filter_status(lambda s: s == 200).get(
        f"{url}/error"
    ),
    "filter_status_ok": lambda client, url: client.filter_status_ok().get(f"{url}/error"),
    "map_request": lambda client, url: client.map_request(lambda r: r).get(f"{url}/"),
    "map_request_effect": lambda client, url: client.map_request_effect(fx.succeed).get(f"{url}/"),
    "map_request_input": lambda client, url: client.map_request_input(lambda r: r).get(f"{url}/"),
    "map_request_input_effect": lambda client, url: client.map_request_input_effect(fx.succeed).get(
        f"{url}/"
    ),
    "tap_request": lambda client, url: client.tap_request(fx.succeed).get(f"{url}/"),
    "tap": lambda client, url: client.tap(fx.succeed).get(f"{url}/"),
    "tap_error": lambda client, url: (
        client.filter_status_ok().tap_error(fx.succeed).get(f"{url}/error")
    ),
    "catch_all": lambda client, url: (
        client.filter_status_ok()
        .catch_all(lambda e: fx.succeed(e.response) if e.response else fx.fail(e))
        .get(f"{url}/error")
    ),
    "catch_tag": lambda client, url: (
        client.filter_status_ok()
        .pipe(
            c.catch_tag(
                HttpClientError, lambda e: fx.succeed(e.response) if e.response else fx.fail(e)
            )
        )
        .get(f"{url}/error")
    ),
    "retry": lambda client, url: client.filter_status_ok().retry(times=2).get(f"{url}/error"),
    "retry_transient": lambda client, url: (
        client.filter_status_ok().retry_transient(times=2).get(f"{url}/error")
    ),
    "with_rate_limiter": _limited,
    "with_circuit_breaker": _breaker,
    "with_cookies_ref": _cookies,
    "with_scope": lambda client, url: fx.scoped(client.with_scope().get(f"{url}/")),
    "follow_redirects": lambda client, url: client.follow_redirects().get(f"{url}/redirect"),
}
"""Each client combinator, keyed by its name."""

_EFFECT_CASES: dict[str, Send] = {
    "plain": lambda client, url: client.get(f"{url}/"),
    "timeout": lambda client, url: client.get(f"{url}/").timeout("10 seconds"),
    "timeout_option": lambda client, url: (
        client.get(f"{url}/")
        .timeout_option("10 seconds")
        .flat_map(lambda o: fx.never if o is None else fx.succeed(o.value))
    ),
    "timeout_or_else": lambda client, url: client.get(f"{url}/").timeout_or_else(
        "10 seconds", lambda: fx.never
    ),
    "race": lambda client, url: client.get(f"{url}/").race(fx.never),
    "race_first": lambda client, url: client.get(f"{url}/").race_first(fx.never),
    "race_all": lambda client, url: fx.race_all(client.get(f"{url}/"), client.get(f"{url}/")),
    "fork_join": lambda client, url: client.get(f"{url}/").fork().flat_map(lambda f: f.join()),
    "retry": lambda client, url: client.get(f"{url}/").retry(recurs(2)),
    "all_concurrent": lambda client, url: fx.all(
        client.get(f"{url}/"), client.get(f"{url}/"), concurrency="unbounded"
    ).map(lambda rs: rs[0]),
    "interruptible": lambda client, url: client.get(f"{url}/").interruptible(),
    "uninterruptible": lambda client, url: client.get(f"{url}/").uninterruptible(),
    "ensuring": lambda client, url: client.get(f"{url}/").ensuring(fx.void),
    "result": lambda client, url: client.get(f"{url}/").result(),
    "body_limit": lambda client, url: client.get(f"{url}/").map(
        lambda r: res.with_body_limit(r, byte_size.bytes(1024))
    ),
}
"""Effect combinators wrapping the request effect before its use."""


def _unread(send: Send) -> Send:
    return lambda client, url: send(client, url).map(lambda _: None)


def _read(send: Send) -> Send:
    def read(value: object) -> fx.Effect[object, Any]:
        if isinstance(value, HttpClientResponse):
            return value.text
        return fx.succeed(value)

    return lambda client, url: send(client, url).flat_map(read)


_CASES = [
    pytest.param(send, id=f"{kind}-{name}")
    for kind, cases in (("client", _CLIENT_CASES), ("effect", _EFFECT_CASES))
    for name, send in cases.items()
]


@pytest.mark.parametrize("send", _CASES)
def test_an_unread_response_releases_its_connection(send: Send) -> None:
    assert open_after(_unread(send)) == 0


@pytest.mark.parametrize("send", _CASES)
def test_a_read_response_releases_its_connection(send: Send) -> None:
    assert open_after(_read(send)) == 0


def test_beacon_probe_does_not_run_out_of_connections() -> None:
    """beacon's probe, past httpx's pool of 100 connections."""
    assert (
        open_after(
            lambda client, url: client.get(f"{url}/").timeout("10 seconds").map(lambda r: r.status),
            times=120,
        )
        == 0
    )


_NOT_CLIENT_COMBINATORS = frozenset(
    {"make", "make_with", "layer_test", "execute", "is_transient_error", "is_transient_response"}
    | {"with_retry_after", "circuit_breaker_classifier"}
    | {"get", "post", "put", "patch", "delete", "head", "options", "query"}
)
"""The functions of ``pyfect.http.client`` that do not wrap a client."""

_NOT_COMBINATORS = frozenset(
    {"pipe", "execute", "preprocess", "postprocess"}
    | {"get", "post", "put", "patch", "delete", "head", "options", "query"}
)


def test_every_client_combinator_is_checked() -> None:
    """A new combinator on ``HttpClientService``, or a new function in
    ``pyfect.http.client``, has to be classified here: a client combinator
    needs a case in ``_CLIENT_CASES``."""
    methods = {
        name
        for name, member in vars(HttpClientService).items()
        if not name.startswith("_") and (callable(member) or isinstance(member, property))
    }
    functions = {name for name in c.__all__ if inspect.isfunction(getattr(c, name))}
    assert functions - _NOT_CLIENT_COMBINATORS == {"transform_response", "catch_tag"}
    assert (methods | {"transform_response", "catch_tag"}) - _NOT_COMBINATORS == set(_CLIENT_CASES)
