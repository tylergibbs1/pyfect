import pyfect as fx

released: list[str] = []


def replica(name: str, delay: float) -> fx.Effect[str]:
    return fx.sleep(delay).as_(name).on_interrupt(fx.sync(lambda: released.append(name)))


# The first to succeed wins; the loser is interrupted, and race waits for it.
fastest = replica("eu", 0.01).race(replica("us", 1))
assert fx.run_sync(fastest) == "eu"
assert released == ["us"]

# timeout fails with TimeoutException, also interrupting the slow effect.
slow = replica("ap", 1).timeout(0.01)
assert isinstance(fx.run_sync_exit(slow), fx.Failure)
