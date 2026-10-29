"""Lua scripts run with ``EVALSHA`` (Effect's ``Redis.script``)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, overload

from pyfect._js import js_number

type RedisReply = str | int | list[RedisReply] | None
"""What a command answers, as the client decodes it: a bulk or status
reply is a ``str``, an integer an ``int``, nil ``None``, an array a
``list``."""


@dataclass(frozen=True, eq=False, slots=True)
class Script[**P, A]:
    """A Lua script called with ``P``: ``params(*args)`` gives its keys
    then its arguments, ``number_of_keys(*args)`` how many of them are
    keys, and ``decode`` reads its reply. Scripts are cached by identity,
    so make each one once."""

    lua: str
    params: Callable[P, Sequence[str | float]]
    number_of_keys: Callable[P, int]
    decode: Callable[[RedisReply], A]

    def arguments(self, *args: P.args, **kwargs: P.kwargs) -> list[str]:
        """``EVALSHA``'s arguments after the hash: the key count, the keys
        and the arguments, numbers written as JavaScript's ``String``."""
        params = [_argument(param) for param in self.params(*args, **kwargs)]
        return [str(self.number_of_keys(*args, **kwargs)), *params]


def _argument(param: str | float) -> str:
    return param if isinstance(param, str) else js_number(param)


def _raw(reply: RedisReply) -> RedisReply:
    return reply


@overload
def script[**P](
    params: Callable[P, Sequence[str | float]],
    *,
    lua: str,
    number_of_keys: int | Callable[P, int],
) -> Script[P, RedisReply]: ...
@overload
def script[**P, A](
    params: Callable[P, Sequence[str | float]],
    *,
    lua: str,
    number_of_keys: int | Callable[P, int],
    decode: Callable[[RedisReply], A],
) -> Script[P, A]: ...
def script[**P](
    params: Callable[P, Sequence[str | float]],
    *,
    lua: str,
    number_of_keys: int | Callable[P, int],
    decode: Callable[[RedisReply], Any] = _raw,
) -> Script[P, Any]:
    """A script whose keys and arguments ``params`` gives from its call's
    arguments; the first ``number_of_keys`` of them (a count, or a function
    of the arguments) are keys. ``decode`` reads the reply into the
    script's result (Effect's ``withReturnType``); a raise there is a
    defect."""
    if isinstance(number_of_keys, int):
        count = number_of_keys

        def keys(*_args: P.args, **_kwargs: P.kwargs) -> int:
            return count

        return Script(lua, params, keys, decode)
    return Script(lua, params, number_of_keys, decode)
