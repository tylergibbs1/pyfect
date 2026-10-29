"""``HttpClientService.with_rate_limiter`` and ``circuit_breaker_classifier``
cases Effect's own tests leave open (each kills a mutation that survived
``tests/oracle/test_http_client_resilience.py``)."""

from __future__ import annotations

import pyfect as fx
from pyfect import layer, testing
from pyfect.cause import Fail, from_reasons
from pyfect.duration import to_millis
from pyfect.exit import Failure
from pyfect.http import client as c
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http.error import HttpClientError, StatusCodeError
from pyfect.persistence import circuit_breaker as cb
from pyfect.persistence import rate_limiter as rl

_REQUEST = req.get("http://test/")


def _status_error(status: int, retry_after: str) -> HttpClientError:
    response = res.make(_REQUEST, status=status, headers={"retry-after": retry_after})
    return HttpClientError(reason=StatusCodeError(request=_REQUEST, response=response))


@testing.effect
def test_the_classifier_keeps_the_longest_retry_after_of_several_failures():
    exit = Failure(from_reasons([Fail(_status_error(503, "10")), Fail(_status_error(502, "5"))]))
    outcome = yield from c.circuit_breaker_classifier(exit)
    assert isinstance(outcome, cb.FailureOutcome)
    assert outcome.retry_after is not None
    assert to_millis(outcome.retry_after) == 10_000


def test_a_limit_inferred_from_remaining_does_not_shrink_on_later_responses() -> None:
    """The first ``remaining`` sets the limit to ``remaining + tokens``;
    later ones only raise it (Effect's ``parseRateLimitLimit``), so a
    budget running down does not throttle the limiter to one request."""
    remaining = iter(["4", "0", "0", "0"])
    attempts = [0]

    def send(request: req.HttpClientRequest, *_: object) -> fx.Effect[res.HttpClientResponse]:
        def answer() -> res.HttpClientResponse:
            attempts[0] += 1
            return res.make(request, status=200, headers={"ratelimit-remaining": next(remaining)})

        return fx.sync(answer)

    def body():
        limiter = yield from rl.RateLimiter()
        client = c.make(send).with_rate_limiter(
            limiter=limiter, key="inferred", limit=10, window=60
        )
        yield from client.get("http://test/")
        yield from client.get("http://test/")
        fiber = yield from client.get("http://test/").fork(start_immediately=True)
        assert attempts[0] == 3
        yield from fiber.join()

    testing.run_test(
        fx.scoped(fx.gen(body).or_die()).pipe(
            fx.provide(rl.layer.pipe(layer.provide(rl.layer_store_memory)))
        )
    )


def test_a_request_costs_at_least_one_token_of_its_resolved_key() -> None:
    """``key`` and ``tokens`` may be functions of the request; a cost below
    one is charged as one (Effect's ``Math.max(tokens, 1)``)."""
    attempts: list[str] = []

    def send(request: req.HttpClientRequest, *_: object) -> fx.Effect[res.HttpClientResponse]:
        return fx.sync(lambda: attempts.append(request.url)).as_(res.make(request, status=200))

    def body():
        limiter = yield from rl.RateLimiter()
        client = c.make(send).with_rate_limiter(
            limiter=limiter,
            key=lambda request: request.url,
            tokens=lambda _request: 0,
            limit=1,
            window=60,
        )
        yield from client.get("http://test/a")
        yield from client.get("http://test/b")
        fiber = yield from client.get("http://test/a").fork(start_immediately=True)
        yield from testing.adjust(59)
        assert attempts == ["http://test/a", "http://test/b"]
        yield from testing.adjust(1)
        yield from fiber.join()
        assert len(attempts) == 3

    testing.run_test(
        fx.scoped(fx.gen(body).or_die()).pipe(
            fx.provide(rl.layer.pipe(layer.provide(rl.layer_store_memory)))
        )
    )
