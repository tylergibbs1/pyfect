from dataclasses import dataclass

import pyfect as fx


@dataclass
class FetchFailed(fx.TaggedError):
    url: str


def fetch(url: str) -> fx.Effect[None, FetchFailed]:
    if url.endswith("/broken"):
        return fx.fail(FetchFailed(url))
    return fx.sleep("10 millis")


@fx.gen
def program():
    # Name the fibers' success and error types: a bare `FiberSet.make()` is a
    # `FiberSet[object, object]`, so `join` would fail with `object`.
    fibers = yield from fx.FiberSet[None, FetchFailed].make()
    for url in ["https://a.com", "https://b.com/broken", "https://c.com"]:
        yield from fibers.run(fetch(url))
    # `join` fails with the first failure; the set's other fibers are
    # interrupted when its scope closes.
    yield from fibers.join()


failed = fx.scoped(program).pipe(fx.catch_tag(FetchFailed, lambda e: fx.succeed(e.url)))
print(fx.run_blocking(failed))
