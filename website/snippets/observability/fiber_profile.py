import pyfect as fx
from pyfect import fiber_profiler


def checksum(n: int) -> int:
    # Stands in for CPU-heavy work: parsing, hashing, pure-Python loops.
    return sum(i * i % 7 for i in range(n))


@fx.fn
def handle(size: int):
    for _ in range(3):
        yield from fx.sync(lambda: checksum(size))
        yield from fx.yield_now()  # each yield ends a turn


@fx.gen
def program():
    reports = yield from handle(200_000).with_span("report").fork()
    pings = yield from handle(2_000).with_span("ping").fork()
    yield from reports.join()
    yield from pings.join()


with fiber_profiler.profile() as report:
    fx.run_blocking(program)

spans = report.spans
print("turns in report:", spans["report"].turns, "in ping:", spans["ping"].turns)
print("report used more CPU than ping:", spans["report"].cpu_ns > spans["ping"].cpu_ns)
print("busiest span:", max((s for s in spans if s), key=lambda s: spans[s].cpu_ns))
