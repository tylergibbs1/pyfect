import pyfect as fx

log: list[str] = []


def fetch(permits: fx.PartitionedSemaphore[str], host: str, path: str) -> fx.Effect[None]:
    request = fx.sync(lambda: log.append(f"{host}{path}")).and_then(fx.sleep(0.01))
    # Each request waits in its host's line for a permit.
    return permits.with_permits(host, request)


@fx.gen
def program():
    # Two permits shared by every host. Freed permits go round-robin across
    # hosts, so the four requests to a.com can't make b.com wait for all of them.
    permits = yield from fx.PartitionedSemaphore[str].make(2)
    requests = [("a.com", f"/{n}") for n in range(4)] + [("b.com", "/0")]
    yield from fx.for_each(requests, lambda r: fetch(permits, *r), concurrency="unbounded")


fx.run_sync(program)
print(log)
