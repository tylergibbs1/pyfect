import pyfect as fx

# An effect is a description of a program. Building one runs nothing.
one = fx.succeed(1)
now = fx.sync(lambda: 41)  # runs the function each time the effect runs

answer = now.map(lambda n: n + 1)
both = one.flat_map(lambda a: answer.map(lambda b: a + b))

assert fx.run_blocking(answer) == 42
assert fx.run_blocking(both) == 43
