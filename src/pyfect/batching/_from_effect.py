"""``RequestResolver.from_effect`` and ``from_effect_tagged``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from pyfect._concurrency import for_each
from pyfect._core import Effect, _Callback, _Locally, _Succeed, _WithFiber
from pyfect._fiber import Fiber
from pyfect.batching._request import Entry
from pyfect.batching._resolver import RequestResolver
from pyfect.cause import Cause
from pyfect.exit import Exit, Failure, Success


def from_effect[Q, E](f: Callable[[Entry[Q]], Effect[object, E]]) -> RequestResolver[Q, E]:
    def run_all(entries: Sequence[Entry[Q]]) -> Effect[None, E]:
        def body(parent: Fiber[Any, Any]) -> Effect[None, E]:
            def register(resume: Callable[[Effect[None]], None]) -> None:
                remaining = len(entries)
                for entry in entries:
                    # Children of the batch's fiber, so interrupting the
                    # batch interrupts them.
                    child = parent._fork(
                        _Locally(f(entry), _replace_with(entry)),
                        daemon=False,
                        start_immediately=True,
                    )

                    def observe(ex: Exit[Any, Any], entry: Entry[Any] = entry) -> None:
                        nonlocal remaining
                        entry._complete(ex)
                        remaining -= 1
                        if remaining == 0:
                            resume(_Succeed(None))

                    child.add_observer_unsafe(observe)

            return _Callback(register)

        return _WithFiber(body)

    return RequestResolver(run_all)


def _replace_with(entry: Entry[Any]) -> Callable[[Any], Any]:
    """Run with exactly the services of the fiber that made the request."""
    return lambda _current: entry.context


def from_effect_tagged[Q, E](
    handlers: Mapping[type[Q], Callable[[Sequence[Entry[Any]]], Effect[Iterable[object], E]]],
) -> RequestResolver[Q, E]:
    def run_all(entries: Sequence[Entry[Q]]) -> Effect[None]:
        groups: dict[type[Any], list[Entry[Any]]] = {}
        for entry in entries:
            groups.setdefault(type(entry.request), []).append(entry)

        def run_group(group: tuple[type[Any], list[Entry[Any]]]) -> Effect[None]:
            cls, members = group

            def failed(cause: Cause[Any]) -> None:
                for entry in members:
                    entry._complete(Failure(cause))

            def succeeded(values: Iterable[object]) -> None:
                for entry, value in zip(members, values, strict=False):
                    entry._complete(Success(value))

            return handlers[cls](members).match_cause(on_failure=failed, on_success=succeeded)

        return for_each(groups.items(), run_group, concurrency="unbounded").as_void()

    return RequestResolver(run_all)
