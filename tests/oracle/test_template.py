"""Ports of Effect's ``http/Template.test.ts``. Each test's docstring is
the Effect test title. Templates are given as their strings and values
(the t-string form needs Python 3.14)."""

import pyfect as fx
from pyfect import effect, testing
from pyfect.deferred import Deferred
from pyfect.http import template


def test_preserves_template_segment_order() -> None:
    """preserves template segment order"""
    slow = effect.succeed("slow").delay("1 second")
    fast = "fast"

    @fx.fn
    def program():
        fiber = yield from template.stream(["a", "b", "c"], slow, fast).run_collect().fork()
        yield from effect.yield_now()
        yield from testing.adjust("1 second")
        chunks = yield from fiber.join()
        return "".join(chunks)

    assert testing.run_test(program()) == "aslowbfastc"


def test_evaluates_effect_interpolations_concurrently() -> None:
    """evaluates effect interpolations concurrently"""

    @fx.fn
    def program():
        first_started = yield from Deferred[None].make()
        second_started = yield from Deferred[None].make()
        release_first = yield from Deferred[None].make()
        first = first_started.succeed(None).and_then(release_first.wait()).as_("first")
        second = second_started.succeed(None).as_("second")
        fiber = yield from template.stream(["", "", ""], first, second).run_collect().fork()
        yield from first_started.wait()
        yield from effect.yield_now()
        assert (yield from second_started.is_done())
        yield from release_first.succeed(None)
        return (yield from fiber.join())

    assert testing.run_test(program()) == ["first", "second"]
