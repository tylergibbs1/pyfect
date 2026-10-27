"""``all`` and ``all_dict``: run several effects and collect the results.

Both run like ``for_each`` (``concurrency`` included). ``discard=True``
keeps no values. ``mode="result"`` runs every effect to the end and
collects each outcome as ``Ok`` / ``Err``, so the combined effect has no
typed errors (defects and interruptions still propagate).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, Never, overload

from pyfect._concurrency import Concurrency, for_each
from pyfect._core import Effect, _Suspend
from pyfect.result import Result

type Mode = Literal["default", "result"]


@overload
def all[A1, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[tuple[A1], EE, RR]: ...
@overload
def all[A1, A2, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    e2: Effect[A2, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[tuple[A1, A2], EE, RR]: ...
@overload
def all[A1, A2, A3, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    e2: Effect[A2, EE, RR],
    e3: Effect[A3, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[tuple[A1, A2, A3], EE, RR]: ...
@overload
def all[A1, A2, A3, A4, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    e2: Effect[A2, EE, RR],
    e3: Effect[A3, EE, RR],
    e4: Effect[A4, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[tuple[A1, A2, A3, A4], EE, RR]: ...
@overload
def all[A1, A2, A3, A4, A5, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    e2: Effect[A2, EE, RR],
    e3: Effect[A3, EE, RR],
    e4: Effect[A4, EE, RR],
    e5: Effect[A5, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[tuple[A1, A2, A3, A4, A5], EE, RR]: ...
@overload
def all[A, EE = Never, RR = Never](
    *effects: Effect[A, EE, RR],
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[tuple[A, ...], EE, RR]: ...
@overload
def all[A1, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[tuple[Result[A1, EE]], Never, RR]: ...
@overload
def all[A1, A2, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    e2: Effect[A2, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[tuple[Result[A1, EE], Result[A2, EE]], Never, RR]: ...
@overload
def all[A1, A2, A3, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    e2: Effect[A2, EE, RR],
    e3: Effect[A3, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[tuple[Result[A1, EE], Result[A2, EE], Result[A3, EE]], Never, RR]: ...
@overload
def all[A1, A2, A3, A4, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    e2: Effect[A2, EE, RR],
    e3: Effect[A3, EE, RR],
    e4: Effect[A4, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[tuple[Result[A1, EE], Result[A2, EE], Result[A3, EE], Result[A4, EE]], Never, RR]: ...
@overload
def all[A1, A2, A3, A4, A5, EE = Never, RR = Never](
    e1: Effect[A1, EE, RR],
    e2: Effect[A2, EE, RR],
    e3: Effect[A3, EE, RR],
    e4: Effect[A4, EE, RR],
    e5: Effect[A5, EE, RR],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[
    tuple[Result[A1, EE], Result[A2, EE], Result[A3, EE], Result[A4, EE], Result[A5, EE]],
    Never,
    RR,
]: ...
@overload
def all[A, EE = Never, RR = Never](
    *effects: Effect[A, EE, RR],
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[tuple[Result[A, EE], ...], Never, RR]: ...
@overload
def all[EE = Never, RR = Never](
    *effects: Effect[object, EE, RR],
    concurrency: Concurrency = None,
    discard: Literal[True],
    mode: Literal["default"] = "default",
) -> Effect[None, EE, RR]: ...
@overload
def all[RR = Never](
    *effects: Effect[object, object, RR],
    concurrency: Concurrency = None,
    discard: Literal[True],
    mode: Literal["result"],
) -> Effect[None, Never, RR]: ...
def all(
    *effects: Effect[Any, Any, Any],
    concurrency: Concurrency = None,
    discard: bool = False,
    mode: Mode = "default",
) -> Effect[Any, Any, Any]:
    """Run effects and collect their results as a tuple, in order."""
    collected = for_each(effects, _step_for(mode), concurrency=concurrency)
    return collected.as_void() if discard else collected.map(tuple)


@overload
def all_dict[K, A, EE = Never, RR = Never](
    effects: Mapping[K, Effect[A, EE, RR]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[dict[K, A], EE, RR]: ...
@overload
def all_dict[K, A, EE = Never, RR = Never](
    effects: Mapping[K, Effect[A, EE, RR]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[dict[K, Result[A, EE]], Never, RR]: ...
@overload
def all_dict[EE = Never, RR = Never](
    effects: Mapping[Any, Effect[object, EE, RR]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
    mode: Literal["default"] = "default",
) -> Effect[None, EE, RR]: ...
@overload
def all_dict[RR = Never](
    effects: Mapping[Any, Effect[object, object, RR]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
    mode: Literal["result"],
) -> Effect[None, Never, RR]: ...
def all_dict(
    effects: Mapping[Any, Effect[Any, Any, Any]],
    *,
    concurrency: Concurrency = None,
    discard: bool = False,
    mode: Mode = "default",
) -> Effect[Any, Any, Any]:
    """Run the effects in a mapping and collect their results under the
    same keys, in the mapping's order. The mapping is read each time the
    effect runs."""
    step = _step_for(mode)

    def start() -> Effect[Any, Any, Any]:
        keys = list(effects)
        collected = for_each([effects[k] for k in keys], step, concurrency=concurrency)
        if discard:
            return collected.as_void()
        return collected.map(lambda values: dict(zip(keys, values, strict=True)))

    return _Suspend(start)


def _step_for(
    mode: Mode,
) -> Callable[[Effect[Any, Any, Any]], Effect[Any, Any, Any]]:
    return _identity if mode == "default" else _as_result


def _identity[T](x: T) -> T:
    return x


def _as_result(eff: Effect[Any, Any, Any]) -> Effect[Any, Never, Any]:
    return eff.result()
