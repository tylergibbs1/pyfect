"""``with`` / ``async with`` on scopes and scoped effects, from plain Python code.

A block ends a scope as an effect ends in ``scoped``: finalizers run in
reverse order with the block's exit (a raise is a defect, Ctrl-C and asyncio
cancellation an interruption), and what is raised after is what
``fx.run_blocking(fx.scoped(...))`` raises, except that a block's own
exception always propagates, with failed finalizers as a note.
"""

import asyncio
import threading
from typing import Any

import pytest

import pyfect as fx
from pyfect import exit as fx_exit
from pyfect import layer
from pyfect.cause import Die
from pyfect.scope import CloseableScope, managed, provide


class Boom(Exception):
    pass


def recorder() -> tuple[list[tuple[str, fx.Exit[Any, Any]]], Any]:
    seen: list[tuple[str, fx.Exit[Any, Any]]] = []

    def resource(
        name: str, *, fail_release: BaseException | None = None
    ) -> fx.Effect[str, Any, Any]:
        def release(_: str, ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
            def run() -> None:
                seen.append((name, ex))
                if fail_release is not None:
                    raise fail_release

            return fx.sync(run)

        return fx.acquire_release(fx.succeed(name), release)

    return seen, resource


def test_a_scope_closes_with_success_releasing_in_reverse_order() -> None:
    seen, resource = recorder()
    with CloseableScope() as scope:
        a = fx.run_blocking(resource("a").pipe(provide(scope)))
        b = fx.run_blocking(resource("b").pipe(provide(scope)))
        assert (a, b) == ("a", "b")
        assert seen == []
    assert seen == [("b", fx.Success(None)), ("a", fx.Success(None))]
    assert scope.is_closed


def test_a_raise_in_the_block_is_the_scopes_defect_and_propagates() -> None:
    seen, resource = recorder()
    error = Boom("block")
    with pytest.raises(Boom) as raised, CloseableScope() as scope:
        fx.run_blocking(resource("a").pipe(provide(scope)))
        raise error
    assert raised.value is error
    assert seen == [("a", fx_exit.die(error))]
    assert not getattr(error, "__notes__", None)


def test_the_finalizers_see_the_exit_scoped_gives_them() -> None:
    seen_with, resource_with = recorder()
    error = Boom("block")
    with pytest.raises(Boom), CloseableScope() as scope:
        fx.run_blocking(resource_with("a").zip(resource_with("b")).pipe(provide(scope)))
        raise error

    seen_fx, resource_fx = recorder()
    program = resource_fx("a").zip(resource_fx("b")).and_then(fx.die(error))
    assert isinstance(fx.run_blocking_exit(fx.scoped(program)), fx.Failure)
    assert seen_with == seen_fx


def test_failed_finalizers_after_a_clean_block_raise_their_merged_cause() -> None:
    seen, resource = recorder()
    release_b, release_a = Boom("release b"), Boom("release a")
    both = resource("a", fail_release=release_a).zip(resource("b", fail_release=release_b))
    with pytest.raises(Boom) as raised, CloseableScope() as scope:
        fx.run_blocking(both.pipe(provide(scope)))
    # Both run, last acquired first, and what is raised is what
    # run_blocking(scoped(...)) raises: the first failure, the merged cause its note.
    assert [name for name, _ in seen] == ["b", "a"]
    assert raised.value is release_b
    note = raised.value.__notes__[-1]
    assert "release b" in note
    assert "release a" in note

    expected = fx.run_blocking_exit(fx.scoped(both))
    assert isinstance(expected, fx.Failure)
    assert expected.cause.pretty_errors() == (release_b, release_a)


def test_failed_finalizers_after_a_raise_are_the_note_on_the_raise() -> None:
    # The block's exception is what propagates, so the note holds only the failed finalizers:
    # not the block's error, which the finalizers' errors carry as their context because
    # they were raised while it was being handled.
    _, resource = recorder()
    error = Boom("the block's own error")
    release_a, release_b = ValueError("release a"), RuntimeError("release b")
    both = resource("a", fail_release=release_a).zip(resource("b", fail_release=release_b))
    with pytest.raises(Boom) as raised, managed(both):
        raise error
    assert raised.value is error
    [note] = error.__notes__
    assert "the block's own error" not in note
    assert note.startswith("Failed finalizers:\n")
    assert "RuntimeError: release b" in note
    assert "ValueError: release a" in note
    # The finalizers' errors are left as they were raised.
    assert release_b.__context__ is error
    assert not release_b.__suppress_context__


def test_ctrl_c_in_the_block_closes_the_scope_as_interrupted() -> None:
    seen, resource = recorder()
    with pytest.raises(KeyboardInterrupt), CloseableScope() as scope:
        fx.run_blocking(resource("a").pipe(provide(scope)))
        raise KeyboardInterrupt
    [(_, ex)] = seen
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts_only


def test_managed_binds_the_resource_and_releases_it_with_the_blocks_exit() -> None:
    seen, resource = recorder()
    with managed(resource("a").zip(resource("b"))) as (a, b):
        assert (a, b) == ("a", "b")
        assert seen == []
    assert seen == [("b", fx.Success(None)), ("a", fx.Success(None))]

    error = Boom("block")
    with pytest.raises(Boom), fx.managed(resource("c")):
        raise error
    assert seen[-1] == ("c", fx_exit.die(error))


def test_a_failed_acquire_releases_what_it_acquired_and_raises() -> None:
    seen, resource = recorder()
    error = Boom("acquire")
    with pytest.raises(Boom) as raised, managed(resource("a").and_then(fx.fail(error))):
        pytest.fail("the block must not run")
    assert raised.value is error
    [(name, ex)] = seen
    assert name == "a"
    assert isinstance(ex, fx.Failure)
    assert ex.cause.squash() is error


def test_a_failed_acquire_and_a_failed_release_raise_scopeds_cause() -> None:
    _, resource = recorder()
    error, release_error = Boom("acquire"), ValueError("release")
    failing = resource("a", fail_release=release_error).and_then(fx.fail(error))
    with pytest.raises(Boom) as raised, managed(failing):
        pytest.fail("the block must not run")

    expected = fx.run_blocking_exit(fx.scoped(failing))
    assert isinstance(expected, fx.Failure)
    # Defects are elected, as in Effect's combineFinalizerCause.
    assert [type(r) for r in expected.cause.reasons] == [Die, Die]
    assert expected.cause.raisable() is error
    assert raised.value is error
    assert "release" in "\n".join(error.__notes__)


def test_managed_builds_a_layer_and_releases_it() -> None:
    events: list[str] = []

    class Name(fx.Tag[str]):
        pass

    live = layer.effect(
        Name,
        fx.acquire_release(
            fx.sync(lambda: events.append("build") or "pyfect"),
            lambda _, __: fx.sync(lambda: events.append("release")),
        ),
    )
    with managed(live.build()) as services:
        assert services.get(Name) == "pyfect"
        assert events == ["build"]
    assert events == ["build", "release"]


def test_managed_takes_the_services_the_effect_needs() -> None:
    class Prefix(fx.Tag[str]):
        pass

    eff = Prefix().map(lambda p: p + "!")
    with managed(eff, context=fx.Context.make(Prefix, "hi")) as value:
        assert value == "hi!"


def test_managed_is_entered_once() -> None:
    m = managed(fx.succeed(1))
    with m:
        pass
    with pytest.raises(RuntimeError, match="entered once"), m:
        pass


def test_of_threads_entering_one_managed_at_once_exactly_one_does() -> None:
    seen, resource = recorder()
    m = managed(resource("a"))
    start = threading.Barrier(8)
    outcomes: list[str] = []
    lock = threading.Lock()

    def enter() -> None:
        start.wait(timeout=2)
        try:
            with m as value:
                outcome = value
        except RuntimeError as refused:
            outcome = str(refused)
        with lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=enter) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3)
    assert sorted(outcomes) == ["a", *["managed(...) is entered once: call managed(eff) again"] * 7]
    assert seen == [("a", fx.Success(None))]


def test_async_with_closes_on_the_loop_and_cancellation_is_an_interruption() -> None:
    seen, resource = recorder()

    async def main() -> None:
        async with managed(resource("a").zip(fx.sleep(0).as_("slept"))) as (a, slept):
            assert (a, slept) == ("a", "slept")
        async with CloseableScope() as scope:
            await fx.run_async(resource("b").pipe(provide(scope)))

        entered = asyncio.Event()

        async def block() -> None:
            async with managed(resource("c")):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(block())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(main())
    assert seen[:2] == [("a", fx.Success(None)), ("b", fx.Success(None))]
    name, ex = seen[2]
    assert name == "c"
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts_only


def test_async_managed_raises_a_failed_acquire() -> None:
    seen, resource = recorder()
    error = Boom("acquire")

    async def main() -> None:
        async with managed(resource("a").and_then(fx.fail(error))):
            pytest.fail("the block must not run")

    with pytest.raises(Boom) as raised:
        asyncio.run(main())
    assert raised.value is error
    [(_, ex)] = seen
    assert isinstance(ex, fx.Failure)
    assert ex.cause.squash() is error
