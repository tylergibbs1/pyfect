import pyfect as fx

events: list[str] = []

pool = fx.acquire_release(
    fx.sync(lambda: events.append("pool opened") or "pool"),
    lambda _pool, exit: fx.sync(
        lambda: events.append(f"pool closed, interrupted: {exit.has_interrupts}")
    ),
)

# Plain Python code gets the same guarantee from a with block.
try:
    with fx.managed(pool) as p:
        events.append(f"using {p}")
        raise KeyboardInterrupt  # Ctrl-C in the middle of the block
except KeyboardInterrupt:
    events.append("KeyboardInterrupt propagated")

print(events)
