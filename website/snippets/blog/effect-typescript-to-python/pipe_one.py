import pyfect as fx


def double(eff: fx.Effect[int]) -> fx.Effect[int]:
    return eff.map(lambda n: n * 2)


def describe(eff: fx.Effect[int]) -> fx.Effect[str]:
    return eff.map(lambda n: f"got {n}")


# Effect's eff.pipe(double, describe) is two calls here: one function per .pipe.
assert fx.run_blocking(fx.succeed(21).pipe(double).pipe(describe)) == "got 42"

# Two functions in one .pipe are a pyright error, and a TypeError if run anyway.
try:
    fx.succeed(21).pipe(double, describe)  # pyright: ignore[reportArgumentType]
except TypeError as error:
    print(error)
