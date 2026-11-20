import pyfect as fx
from pyfect import fiber_profiler


def checksum(n: int) -> int:
    return sum(i * i % 7 for i in range(n))


@fx.fn
def handle(size: int):
    total = 0
    for _ in range(3):
        total += yield from fx.sync(lambda: checksum(size))
        yield from fx.yield_now()
    return total


@fx.gen
def program():
    # Profile one part of a program that is already running as an effect.
    report, total = yield from fiber_profiler.profiled(
        fx.all(handle(200_000).with_span("report"), handle(2_000).with_span("ping"), concurrency=2)
    )
    spans = report.spans
    print("results:", len(total))
    print("turns in report:", spans["report"].turns, "in ping:", spans["ping"].turns)
    print("report used more CPU than ping:", spans["report"].cpu_ns > spans["ping"].cpu_ns)


fx.run_blocking(program)
