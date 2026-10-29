import pyfect as fx
from pyfect import layer
from pyfect.persistence import (
    CircuitBreaker,
    CircuitBreakerError,
    RateLimiter,
    RateLimiterError,
    circuit_breaker,
    rate_limiter,
)


def limited(error: RateLimiterError) -> fx.Effect[str]:
    return fx.succeed(f"limited: {type(error.reason).__name__}")


@fx.fn
def rate_limits():
    limiter = yield from RateLimiter()
    for _ in range(3):
        consumed = limiter.consume(key="user:1", limit=2, window=60)
        allowed = consumed.map(lambda r: f"allowed, {r.remaining} left")
        print((yield from allowed.pipe(fx.catch_tag(RateLimiterError, limited))))

    # with_rate_limiter limits any effect: here, waiting instead of failing.
    with_rate_limiter = yield from rate_limiter.make_with_rate_limiter
    reply = yield from fx.succeed("pong").pipe(
        with_rate_limiter(key="ping", limit=10, window=1, on_exceeded="delay")
    )
    print(reply)


statuses = iter(["503", "503", "200"])


def call_api() -> fx.Effect[str, str]:
    status = next(statuses)
    return fx.succeed(status) if status == "200" else fx.fail(status)


@fx.fn
def breaker():
    api = yield from CircuitBreaker()

    def call():
        return (
            fx.suspend(call_api)
            .pipe(api.execute(key="api"))
            .pipe(fx.catch_tag(CircuitBreakerError, lambda e: fx.succeed(type(e.reason).__name__)))
            .catch_all(lambda status: fx.succeed(f"failed: {status}"))
        )

    for _ in range(3):
        print((yield from call()))
    print(type((yield from api.state("api"))).__name__)
    yield from fx.sleep(0.1)  # the open time passes: the next call is the probe
    print((yield from call()))
    print(type((yield from api.state("api"))).__name__)


# Counters and circuit states in memory; the Redis stores share them between processes.
Limits = layer.merge(
    rate_limiter.layer.pipe(layer.provide(rate_limiter.layer_store_memory)),
    circuit_breaker.layer(trip_policy=circuit_breaker.consecutive(2), open_duration=0.1).pipe(
        layer.provide(circuit_breaker.layer_store_memory())
    ),
)
fx.run_main(rate_limits().and_then(breaker()).pipe(fx.provide(Limits)))
