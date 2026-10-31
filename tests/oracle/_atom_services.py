"""The services Effect's ``Atom.test.ts`` builds runtimes from."""

from dataclasses import dataclass

import pyfect as fx
from pyfect import layer
from pyfect.reactivity import atom
from pyfect.reactivity.atom_registry import AtomRegistry


@dataclass
class CounterService:
    get: fx.Effect[int]
    inc: fx.Effect[None]


class BuildCounter(fx.Tag[CounterService], key="BuildCounter"):
    pass


class Counter(fx.Tag[CounterService], key="Counter"):
    pass


def _counter(start: int) -> CounterService:
    count = [start]

    def inc() -> None:
        count[0] += 1

    return CounterService(fx.sync(lambda: count[0]), fx.sync(inc))


BuildCounterLayer = layer.sync(BuildCounter, lambda: _counter(0))


def _counter_layer(start: int) -> fx.Layer[Counter]:
    @fx.gen
    def make():
        build_counter = yield from BuildCounter()
        yield from build_counter.inc
        return _counter(start)

    return layer.provide(BuildCounterLayer)(layer.effect(Counter, make))


CounterLayer = _counter_layer(1)
CounterTest = _counter_layer(10)


@dataclass
class MultiplierService:
    counter: CounterService

    def times(self, n: int) -> fx.Effect[int]:
        return self.counter.get.map(lambda value: value * n)


class Multiplier(fx.Tag[MultiplierService], key="Multiplier"):
    pass


@fx.gen
def _make_multiplier():
    counter = yield from Counter()
    yield from AtomRegistry()
    return MultiplierService(counter)


MultiplierLayer = layer.provide_merge(CounterLayer)(layer.effect(Multiplier, _make_multiplier))

build_counter_runtime = atom.runtime(BuildCounterLayer)
counter_runtime = atom.runtime(CounterLayer)
multiplier_runtime = atom.runtime(MultiplierLayer)
