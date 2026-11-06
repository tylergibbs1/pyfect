import pyfect as fx


def fetch(n: int) -> fx.Effect[int]:
    return fx.sleep(0.05).as_(n * 10)


# Up to 3 fetches at a time; results keep the input order.
program = fx.for_each(range(6), fetch, concurrency=3)

seconds, result = fx.run_blocking(program.timed())
assert result == [0, 10, 20, 30, 40, 50]
assert seconds < 0.25  # two rounds of three, not six sleeps in a row

# all runs a fixed set of effects and keeps each one's type: tuple[int, str].
pair = fx.all(fetch(1), fx.succeed("two"), concurrency="unbounded")
assert fx.run_blocking(pair) == (10, "two")
