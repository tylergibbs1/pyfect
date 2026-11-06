from typing import Literal

import pyfect as fx
from pyfect import layer

built: list[str] = []
type Model = Literal["haiku", "sonnet"]


class Greeter(fx.Tag[str]): ...


def greeter(model: Model) -> fx.Layer[Greeter]:
    return layer.effect(Greeter, fx.sync(lambda: built.append(model)).as_(f"hello from {model}"))


# A Greeter per model, built when first used and shared while in use.
class Greeters(fx.LayerMapService[Model, Greeter]): ...


@fx.gen
def program():
    first = yield from Greeter().pipe(fx.provide(Greeters.get("haiku")))
    second = yield from Greeter().pipe(fx.provide(Greeters.get("sonnet")))
    return first, second


result = fx.run_blocking(program.pipe(fx.provide(Greeters.layer(greeter))))
assert result == ("hello from haiku", "hello from sonnet")
assert built == ["haiku", "sonnet"]
