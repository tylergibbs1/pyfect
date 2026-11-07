from dataclasses import dataclass

import pyfect as fx
from pyfect import layer, stream
from pyfect.reactivity import atom, atom_registry
from pyfect.reactivity.atom import FnContext

# An effect atom holds an AsyncResult: Initial while it runs, then Success or Failure.
user = atom.make(fx.sleep("50 millis").as_("Ada"))

# A stream atom holds a result of the latest item.
latest = atom.make(stream.make(1, 2, 3))


# A function atom runs its effect each time an argument is written to it.
def greet(name: str, get: FnContext) -> fx.Effect[str]:
    return fx.succeed(f"hello, {name}")


greeting = atom.fn(greet)


# A runtime atom builds a layer; its atoms' effects can use the layer's services.
@dataclass
class Prices:
    table: dict[str, int]


class PriceTable(fx.Tag[Prices]): ...


prices = atom.runtime(layer.succeed(PriceTable, Prices({"tea": 3})))
tea = prices.atom(PriceTable().map(lambda p: p.table["tea"]))


@fx.gen
def program():
    registry = yield from atom_registry.AtomRegistry()
    print(registry.get(user))
    print("user:", (yield from atom.get_result(user)))
    print("latest:", (yield from atom.get_result(latest)))

    yield from atom.set(greeting, "Grace")
    print((yield from atom.get_result(greeting, suspend_on_waiting=True)))
    print("tea:", (yield from atom.get_result(tea)))


fx.run_main(program.pipe(fx.provide(atom_registry.layer)))
