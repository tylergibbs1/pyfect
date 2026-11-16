"""Using an effect the way a method chain would gives a message that says what to write
instead, in public names.

- An effect is not awaitable (`inspect.isawaitable` is false), so libraries that await
  whatever is awaitable pass it through.
- The combinators that remove something from a type are functions for `.pipe`, never methods
  (pyright binds `self` first and erases the wrong thing). `eff.catch_tag(...)` raises an
  `AttributeError` showing the `.pipe(fx.catch_tag(...))` form. pyright still reports the
  attribute as unknown (`tests/type_checks.py`).
"""

import asyncio
import inspect
import re
import traceback
from pathlib import Path

import pytest

import pyfect as fx
from pyfect._effect_misuse import PIPE_ONLY


def test_an_effect_is_not_awaitable():
    # An __await__, even one raising a clearer TypeError, would make libraries that await
    # anything awaitable (GraphQL resolvers, pytest-asyncio, callback frameworks) raise on
    # effects they pass through today.
    assert inspect.isawaitable(fx.succeed(1)) is False
    assert not hasattr(fx.Effect, "__await__")


@pytest.mark.parametrize("name", sorted(PIPE_ONLY))
def test_a_pipe_only_combinator_used_as_a_method_shows_the_pipe_form(name: str):
    with pytest.raises(AttributeError) as raised:
        getattr(fx.fail("boom"), name)
    message = str(raised.value)
    assert message.startswith(f"Effect has no method {name}")
    assert f".pipe(fx.{name}" in message
    assert "_FailCause" not in message
    # Python's "Did you mean" would suggest a method that is not the fix.
    assert "Did you mean" not in "".join(traceback.format_exception(raised.value))
    assert not hasattr(fx.succeed(1), name)


def test_other_missing_attributes_keep_python_s_message():
    with pytest.raises(AttributeError, match="has no attribute 'no_such_method'"):
        fx.succeed(1).no_such_method  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]  # noqa: B018


def _pipe_only_in_docstrings() -> set[str]:
    """Public functions of `pyfect` that are not methods and whose docstring shows them
    used with `.pipe(`: the combinators a user might call as a method."""
    found: set[str] = set()
    for name in fx.__all__:
        value = getattr(fx, name)
        if not inspect.isfunction(value) or hasattr(fx.Effect, name):
            continue
        if re.search(rf"\.pipe\((?:fx\.)?{name}\b", value.__doc__ or ""):
            found.add(name)
    return found


def test_every_pipe_only_combinator_is_listed():
    # A new curried combinator documented with `.pipe(name(...))` gets the message too.
    assert _pipe_only_in_docstrings() <= PIPE_ONLY
    assert all(callable(getattr(fx, name)) for name in PIPE_ONLY)


@pytest.mark.parametrize(
    "effect",
    [fx.succeed(1), fx.fail("boom"), fx.sleep("1 second"), fx.never],
    ids=["succeed", "fail", "sleep", "never"],
)
def test_an_effect_s_repr_says_it_has_not_run_and_how_to_run_it(effect: fx.Effect[object, object]):
    # print(greet("ada")) used to show "<pyfect._primitives._Locally object at 0x...>".
    text = repr(effect)
    assert text == str(effect)
    assert "not run" in text
    assert "fx.run_blocking(" in text
    assert "yield from" in text
    assert "_primitives" not in text


def test_an_effect_is_not_callable():
    # A __call__, even one raising a clearer TypeError, would make callable(effect) true, and
    # code that calls a callable but uses an effect as it is (cli's `layer(value) if
    # callable(layer) else layer`) would call it. pyright reports the call (type_checks.py).
    assert not callable(fx.succeed(1))


def test_an_effect_method_on_yield_now_says_to_call_it():
    # Effect's yieldNow is a value; pyfect's yield_now is a function until 0.7.0.
    with pytest.raises(AttributeError, match=r"fx\.yield_now\(\)\.fork\(") as raised:
        fx.yield_now.fork()  # pyright: ignore[reportFunctionMemberAccess]
    assert "Did you mean" not in "".join(traceback.format_exception(raised.value))
    assert fx.run_blocking(fx.yield_now().as_("ran")) == "ran"
    assert fx.yield_now.__name__ == "yield_now"
    assert inspect.signature(fx.yield_now).return_annotation == "Effect[None]"


def test_yield_from_an_uncalled_yield_now_says_to_call_it():
    @fx.gen
    def body():
        yield from fx.yield_now  # pyright: ignore[reportGeneralTypeIssues]

    with pytest.raises(TypeError, match=r"yield from fx\.yield_now\(\)"):
        fx.run_blocking(body)  # pyright: ignore[reportUnknownArgumentType]


_EFFECTS_PAGE = Path(__file__).parent.parent / "website" / "content" / "docs" / "effects.mdx"


def _body() -> fx.Gen[int]:
    return (yield from fx.succeed(1))


_traced_call = fx.fn(_body)


# What a newcomer calls or awaits: the effects that the common constructors and combinators
# return. Python names the internal class in its TypeError, which no `__call__` or `__await__`
# may replace (above), so the Effects page lists each exact message for a search to find.
_EFFECTS: dict[str, fx.Effect[object, object]] = {
    "succeed": fx.succeed(1),
    "fail": fx.fail("boom"),
    "sync": fx.sync(lambda: 1),
    "suspend": fx.suspend(lambda: fx.succeed(1)),
    "gen": fx.gen(_body),
    "fn": _traced_call(),
    "map": fx.succeed(1).map(str),
    "flat_map": fx.succeed(1).as_(2),
    "catch_all": fx.succeed(1).catch_all(fx.succeed),
    "ensuring": fx.succeed(1).ensuring(fx.void),
    "sleep": fx.sleep("1 second"),
    "never": fx.never,
    "fork": fx.succeed(1).fork(),
}


def _messages(name: str) -> list[str]:
    return [
        f"'{name}' object is not callable",
        f"'{name}' object can't be awaited",  # Python 3.14
        f"object {name} can't be used in 'await' expression",  # Python 3.13
    ]


@pytest.mark.parametrize("effect", list(_EFFECTS.values()), ids=list(_EFFECTS))
def test_the_effects_page_quotes_python_s_message_for_calling_or_awaiting_it(
    effect: fx.Effect[object, object],
):
    name = type(effect).__name__
    page = _EFFECTS_PAGE.read_text()
    missing = [message for message in _messages(name) if message not in page]
    assert missing == []
    with pytest.raises(TypeError) as called:
        effect()  # pyright: ignore[reportCallIssue]
    assert str(called.value) in _messages(name)

    async def wait() -> None:
        await effect  # pyright: ignore[reportGeneralTypeIssues]

    with pytest.raises(TypeError) as awaited:
        asyncio.run(wait())
    assert str(awaited.value) in _messages(name)
