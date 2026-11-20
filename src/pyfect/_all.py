"""``all`` and ``all_dict``: run several effects and collect the results.

Both run like ``for_each`` (``concurrency`` included). ``discard=True``
keeps no values. ``mode="result"`` runs every effect to the end and
collects each outcome as ``Ok`` / ``Err``, so the combined effect has no
typed errors (defects and interruptions still propagate).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal, Never, cast, overload

from pyfect._concurrency import Concurrency, _as_is, for_each_into
from pyfect._core import Effect, _Suspend
from pyfect._effect_args import require_effects
from pyfect._effect_base import EffectBase
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
@overload
def all[K, A, EE = Never, RR = Never](
    effects: Mapping[K, Effect[A, EE, RR]],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[dict[K, A], EE, RR]: ...
@overload
def all[K, A, EE = Never, RR = Never](
    effects: Mapping[K, Effect[A, EE, RR]],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[dict[K, Result[A, EE]], Never, RR]: ...
@overload
def all[EE = Never, RR = Never](
    effects: Mapping[Any, Effect[object, EE, RR]],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
    mode: Literal["default"] = "default",
) -> Effect[None, EE, RR]: ...
@overload
def all[RR = Never](
    effects: Mapping[Any, Effect[object, object, RR]],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
    mode: Literal["result"],
) -> Effect[None, Never, RR]: ...
@overload
def all[A, EE = Never, RR = Never](
    effects: Iterable[Effect[A, EE, RR]],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["default"] = "default",
) -> Effect[list[A], EE, RR]: ...
@overload
def all[A, EE = Never, RR = Never](
    effects: Iterable[Effect[A, EE, RR]],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
    mode: Literal["result"],
) -> Effect[list[Result[A, EE]], Never, RR]: ...
@overload
def all[EE = Never, RR = Never](
    effects: Iterable[Effect[object, EE, RR]],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
    mode: Literal["default"] = "default",
) -> Effect[None, EE, RR]: ...
@overload
def all[RR = Never](
    effects: Iterable[Effect[object, object, RR]],
    /,
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
    mode: Literal["result"],
) -> Effect[None, Never, RR]: ...
def all(
    *effects: Effect[Any, Any, Any] | Iterable[Effect[Any, Any, Any]] | Mapping[Any, Any],
    concurrency: Concurrency = None,
    discard: bool = False,
    mode: Mode = "default",
) -> Effect[Any, Any, Any]:
    """Run effects and collect their results as a tuple, in order. As Effect's
    ``Effect.all``, the effects may also come as one iterable (a list of the
    results, as Effect's array gives an array) or one mapping (a dict of them under
    the same keys, as ``all_dict``)."""
    items: tuple[object, ...] = effects
    collect: Callable[[list[Any]], Any] = tuple
    if len(effects) == 1 and not isinstance(effects[0], EffectBase):
        (only,) = effects
        if isinstance(only, Mapping):
            shape = cast("Mapping[Any, Effect[Any, Any, Any]]", only)
            return all_dict(shape, concurrency=concurrency, discard=discard, mode=mode)
        if not isinstance(only, (str, bytes)):
            items = tuple(only)
            collect = _as_is  # the results list itself, as Effect gives an array
    elif len(effects) > 1:
        _reject_a_collection_among(effects)
    require_effects(items, "effects")
    checked = cast("tuple[Effect[Any, Any, Any], ...]", items)
    return for_each_into(checked, _step_for(mode), concurrency, None if discard else collect)


def _reject_a_collection_among(effects: tuple[object, ...]) -> None:
    for i, value in enumerate(effects):
        if isinstance(value, (list, tuple, Mapping)):
            kind = type(cast("object", value)).__name__
            raise TypeError(
                f"effects[{i}] must be an Effect, got {kind}: {value!r} "
                "(pass the effects as arguments, fx.all(a, b), or as one list, fx.all([a, b]))"
            )


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

    # As Effect's ``all`` of a record: the values, discarded, or each value
    # paired with its key inside its own effect.
    if discard:
        return for_each_into(effects.values(), step, concurrency, None)

    def keyed(entry: tuple[Any, Effect[Any, Any, Any]]) -> Effect[Any, Any, Any]:
        key, eff = entry
        return step(eff).map(lambda value: (key, value))

    return _Suspend(lambda: for_each_into(effects.items(), keyed, concurrency, _as_is).map(dict))


def _step_for(
    mode: Mode,
) -> Callable[[Effect[Any, Any, Any]], Effect[Any, Any, Any]]:
    return _identity if mode == "default" else _as_result


def _identity[T](x: T) -> T:
    return x


def _as_result(eff: Effect[Any, Any, Any]) -> Effect[Any, Never, Any]:
    return eff.result()
