"""Ports of the ``onErrorIf`` and ``onExitIf`` sections of Effect's
``Effect.test.ts``.

Each test's docstring is the Effect test title. The ``Filter`` titles use
``on_error_filter`` / ``on_exit_filter``, whose filter returns ``Ok`` /
``Err``; ``Cause.squash`` of a single failure is its error.
"""

from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.cause import Cause, Fail
from pyfect.exit import fail as exit_fail
from pyfect.result import Err, Ok, Result


def _error(c: Cause[str]) -> str:
    found = c.find_fail()
    assert isinstance(found, Fail)
    return found.error


def _push(finalized: list[str], item: str) -> fx.Effect[None]:
    return fx.sync(lambda: finalized.append(item))


# --- onErrorIf ------------------------------------------------------------------


@testing.effect
def test_on_error_if_predicate_match_runs_finalizer():
    """predicate match runs finalizer"""
    finalized: list[str] = []
    failing: fx.Effect[Never, str] = fx.fail("e1")
    ex = yield from failing.on_error_if(
        lambda c: c.has_fails, lambda c: _push(finalized, _error(c))
    ).exit()
    assert finalized == ["e1"]
    assert ex == exit_fail("e1")


@testing.effect
def test_on_error_if_predicate_no_match_skips_finalizer():
    """predicate no match skips finalizer"""
    finalized: list[str] = []
    ex = yield from (
        fx.fail("e1").on_error_if(lambda _: False, lambda _: _push(finalized, "finalized")).exit()
    )
    assert finalized == []
    assert ex == exit_fail("e1")


@testing.effect
def test_on_error_if_filter_match_runs_finalizer():
    """filter match runs finalizer"""
    finalized: list[str] = []
    failing: fx.Effect[Never, str] = fx.fail("e1")
    ex = yield from failing.on_error_filter(
        lambda c: c.find_error(), lambda error, _: _push(finalized, error)
    ).exit()
    assert finalized == ["e1"]
    assert ex == exit_fail("e1")


@testing.effect
def test_on_error_if_success_skips_finalizer():
    """success skips finalizer"""
    finalized: list[str] = []
    result = yield from fx.succeed(42).on_error_if(
        lambda _: True, lambda _: _push(finalized, "finalized")
    )
    assert finalized == []
    assert result == 42


# --- onExitIf -------------------------------------------------------------------


def _is_success(ex: fx.Exit[Any, Any]) -> bool:
    return isinstance(ex, fx.Success)


@testing.effect
def test_on_exit_if_predicate_match_on_success_runs_finalizer():
    """predicate match on success runs finalizer"""
    finalized: list[str] = []

    def record(ex: fx.Exit[int, Never]) -> fx.Effect[None]:
        if isinstance(ex, fx.Success):
            return _push(finalized, f"success:{ex.value}")
        return fx.void

    result = yield from fx.succeed(42).on_exit_if(_is_success, record)
    assert finalized == ["success:42"]
    assert result == 42


@testing.effect
def test_on_exit_if_predicate_no_match_on_failure_skips_finalizer():
    """predicate no match on failure skips finalizer"""
    finalized: list[str] = []
    ex = yield from (
        fx.fail("e1").on_exit_if(_is_success, lambda _: _push(finalized, "finalized")).exit()
    )
    assert finalized == []
    assert ex == exit_fail("e1")


@testing.effect
def test_on_exit_if_predicate_match_on_failure_runs_finalizer():
    """predicate match on failure runs finalizer"""
    finalized: list[str] = []
    failing: fx.Effect[Never, str] = fx.fail("e1")

    def record(ex: fx.Exit[Never, str]) -> fx.Effect[None]:
        if isinstance(ex, fx.Failure):
            return _push(finalized, f"failure:{_error(ex.cause)}")
        return fx.void

    ex = yield from failing.on_exit_if(lambda ex: isinstance(ex, fx.Failure), record).exit()
    assert finalized == ["failure:e1"]
    assert ex == exit_fail("e1")


@testing.effect
def test_on_exit_if_filter_match_receives_pass_value_and_exit():
    """filter match receives pass value and exit"""
    finalized: list[str] = []

    def passes(ex: fx.Exit[int, Never]) -> Result[str, fx.Exit[int, Never]]:
        return Ok(f"value:{ex.value}") if isinstance(ex, fx.Success) else Err(ex)

    def record(value: str, ex: fx.Exit[int, Never]) -> fx.Effect[None]:
        outcome = f"success:{ex.value}" if isinstance(ex, fx.Success) else "failure"
        return _push(finalized, f"{value}:{outcome}")

    result = yield from fx.succeed(42).on_exit_filter(passes, record)
    assert finalized == ["value:42:success:42"]
    assert result == 42
