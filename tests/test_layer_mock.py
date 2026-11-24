"""``layer.mock`` beyond Effect's tests: Python's protocols probe dunder
attributes, which a mock must not answer with an unimplemented member."""

import copy

import pyfect as fx
from pyfect import layer, testing


class Shape:
    one: int

    def missing(self) -> fx.Effect[int]:
        return fx.succeed(1)


class Mocked(fx.Tag[Shape], key="LayerMock/Mocked"): ...


@testing.effect
def test_a_mock_answers_dunder_lookups_as_a_plain_object():
    ctx = yield from layer.mock(Mocked, one=1).build()
    service = ctx.get(Mocked)
    assert not hasattr(service, "__wrapped__")
    assert copy.copy(service).one == 1
    assert isinstance(service.missing(), fx.Effect)


class Checker:
    def check(self, name: str) -> fx.Effect[bool]: ...
    def count(self) -> fx.Effect[int]: ...


class Checks(fx.Tag[Checker], key="Checks"): ...


def _yes(_name: str) -> fx.Effect[bool]:
    return fx.succeed(True)


@testing.effect
def test_an_unmocked_member_names_a_mocked_one_it_may_be_a_typo_of():
    ctx = yield from layer.mock(Checks, chek=_yes).build()
    exit = yield from ctx.get(Checks).check("a").exit()
    assert isinstance(exit, fx.Failure)
    assert str(exit.cause.defects[0]) == (
        'Checks: Unimplemented method "check"; layer.mock was given "chek": a typo?'
    )


@testing.effect
def test_an_unmocked_member_with_no_close_match_keeps_effect_s_message():
    ctx = yield from layer.mock(Checks, chek=_yes).build()
    exit = yield from ctx.get(Checks).count().exit()
    assert isinstance(exit, fx.Failure)
    assert str(exit.cause.defects[0]) == 'Checks: Unimplemented method "count"'
