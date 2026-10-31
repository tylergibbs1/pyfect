"""``swr``: stale-while-revalidate over an atom holding a result."""

from __future__ import annotations

from typing import Any, Literal

from pyfect.duration import Duration, to_millis, to_seconds
from pyfect.reactivity._time import now_millis
from pyfect.reactivity.async_result import AsyncResult, Failure, Initial, Success
from pyfect.reactivity.atom._combinators import transform
from pyfect.reactivity.atom._types import Atom, AtomContext


def _timestamp(result: AsyncResult[Any, Any]) -> int | None:
    if isinstance(result, Success):
        return result.timestamp
    if isinstance(result, Failure) and result.previous_success is not None:
        return result.previous_success.value.timestamp
    return None


def _should_revalidate(result: AsyncResult[Any, Any], stale_time: float) -> bool:
    if result.waiting:
        return False
    timestamp = _timestamp(result)
    if timestamp is None:
        return not isinstance(result, Initial)
    return not now_millis() - timestamp < stale_time


def swr[A, E](
    atom: Atom[AsyncResult[A, E]],
    *,
    stale_time: Duration,
    revalidate_on_mount: bool = True,
    revalidate_on_focus: bool | Literal["always"] = False,
    focus_signal: Atom[object] | None = None,
) -> Atom[AsyncResult[A, E]]:
    stale = to_millis(to_seconds(stale_time))

    def read(get: AtomContext, source: Atom[AsyncResult[A, E]]) -> AsyncResult[A, E]:
        current = get.once(source)
        get.subscribe(source, get.set_self)
        if revalidate_on_focus and focus_signal is not None:
            get.once(focus_signal)

            def on_focus(_: object) -> None:
                if revalidate_on_focus == "always" or _should_revalidate(get.once(source), stale):
                    get.refresh(source)

            get.subscribe(focus_signal, on_focus)
        first_read = get.self() is None
        if first_read and not revalidate_on_mount:
            return current
        if _should_revalidate(current, stale):
            active = [True]
            get.add_finalizer(lambda: active.__setitem__(0, False))

            def revalidate() -> None:
                if active[0] and _should_revalidate(get.once(source), stale):
                    get.refresh(source)

            get.registry.scheduler.schedule(revalidate)
        return current

    return transform(atom, read, initial_value_target=atom)


__all__ = ["swr"]
