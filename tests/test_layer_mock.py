"""``layer.mock`` beyond Effect's tests: Python's protocols probe dunder
attributes, which a mock must not answer with an unimplemented member."""

import copy

import pyfect as fx
from pyfect import layer, testing


class Shape:
    one: int

    def missing(self) -> fx.Effect[int]:
        return fx.succeed(1)


class Mocked(fx.Tag[Shape], key="Mocked"): ...


@testing.effect
def test_a_mock_answers_dunder_lookups_as_a_plain_object():
    ctx = yield from layer.mock(Mocked, one=1).build()
    service = ctx.get(Mocked)
    assert not hasattr(service, "__wrapped__")
    assert copy.copy(service).one == 1
    assert isinstance(service.missing(), fx.Effect)
