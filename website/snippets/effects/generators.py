import pyfect as fx


@fx.gen
def program():
    a = yield from fx.succeed(20)
    b = yield from fx.sync(lambda: 22)
    yield from fx.sleep("10 millis")  # suspends this fiber, not the thread
    return a + b


# program is an Effect[int]: the type of the return value is inferred.
assert fx.run_blocking(program) == 42


@fx.fn
def add(a: int, b: int):
    total = yield from fx.succeed(a + b)
    return total


# A function returning an effect; add(1, 2) is an Effect[int].
assert fx.run_blocking(add(1, 2)) == 3
