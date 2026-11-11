"""Exit constructors and ``map_both`` on a success keep the values they
are given."""

from pyfect import exit
from pyfect.exit import Success


def test_succeed_holds_its_value():
    assert exit.succeed(2) == Success(2)


def test_interrupt_records_the_interrupting_fiber():
    assert exit.interrupt(4).cause.interruptors == {4}


def test_map_both_on_a_success_maps_its_value():
    def unreachable(_: object) -> str:
        raise AssertionError

    assert exit.succeed(2).map_both(on_failure=unreachable, on_success=lambda n: n + 1) == Success(
        3
    )
