import pyfect as fx

log: list[str] = []


@fx.gen
def heartbeat():
    while True:
        yield from fx.sleep("10 millis")


@fx.gen
def handle_request():
    # The forked fiber is a child: it can't outlive this one.
    yield from heartbeat.on_interrupt(fx.sync(lambda: log.append("heartbeat stopped"))).fork()
    yield from fx.sleep("35 millis")
    log.append("request done")
    return 200


assert fx.run_blocking(handle_request) == 200
print(log)
