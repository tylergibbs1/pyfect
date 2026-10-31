"""One build of a node: the ``AtomContext`` its atom's ``read`` gets.

A lifetime records the parents its build reads and the finalizers it
adds. When the build is replaced (or the node removed) it is disposed: the
finalizers run, newest first, and the context from then on only reads.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect, _Callback, _Succeed, _Sync
from pyfect.effect import never
from pyfect.option import Option
from pyfect.reactivity import async_result
from pyfect.reactivity._result_effect import result_effect
from pyfect.reactivity.async_result import AsyncResult, Initial
from pyfect.reactivity.atom_registry._batch import run_all

if TYPE_CHECKING:
    from pyfect.errors import Done
    from pyfect.queue import Queue
    from pyfect.reactivity.atom._types import Atom, Writable
    from pyfect.reactivity.atom_registry._node import Node
    from pyfect.reactivity.atom_registry._registry import AtomRegistryService
    from pyfect.stream import Stream


class Lifetime[A]:
    """The context of one build of ``node``."""

    __slots__ = ("disposed", "failure", "finalizers", "is_fn", "node", "reads")

    def __init__(self, node: Node[A]) -> None:
        self.node = node
        self.is_fn = False
        self.disposed = False
        self.finalizers: list[Callable[[], None]] | None = None
        # the parents read so far by the build; ``None`` once it returned
        self.reads: dict[Node[Any], None] | None = {}
        # a failure met while reading a parent that still produced its value
        self.failure: Exception | None = None

    @property
    def registry(self) -> AtomRegistryService:
        return self.node.registry

    def __call__[T](self, atom: Atom[T], /) -> T:
        if self.disposed or self.is_fn:
            return self.node.registry.get(atom)
        return self.node.read_tracked(atom, self)

    def get[T](self, atom: Atom[T], /) -> T:
        if self.disposed:
            return self.node.registry.get(atom)
        return self.node.read_tracked(atom, self)

    def once[T](self, atom: Atom[T], /) -> T:
        return self.node.registry.get(atom)

    def add_finalizer(self, f: Callable[[], None], /) -> None:
        if self.disposed:
            f()
            return
        if self.finalizers is None:
            self.finalizers = []
        self.finalizers.append(f)

    def result[T, E](
        self, atom: Atom[AsyncResult[T, E]], /, *, suspend_on_waiting: bool = False
    ) -> Effect[T, E]:
        if self.disposed or self.is_fn:
            return self.result_once(atom, suspend_on_waiting=suspend_on_waiting)
        result = self.get(atom)
        if (suspend_on_waiting and result.waiting) or isinstance(result, Initial):
            return never
        return result_effect(result)

    def result_once[T, E](
        self, atom: Atom[AsyncResult[T, E]], /, *, suspend_on_waiting: bool = False
    ) -> Effect[T, E]:
        def ready(result: AsyncResult[T, E]) -> bool:
            return not isinstance(result, Initial) and not (suspend_on_waiting and result.waiting)

        def register(resume: Callable[[Effect[T, E]], None]) -> Effect[None] | None:
            result = self.once(atom)
            if ready(result):
                resume(result_effect(result))
                return None

            def on_change(value: AsyncResult[T, E]) -> None:
                if not ready(value):
                    return
                cancel()
                resume(result_effect(value))

            cancel = self.node.registry.subscribe(atom, on_change)
            return _Sync(cancel)

        return _Callback(register)

    def set_result[T, E, W](
        self, atom: Writable[AsyncResult[T, E], W], value: W, /
    ) -> Effect[T, E]:
        if self.disposed:
            return never
        self.node.registry.set(atom, value)
        return self.result_once(atom, suspend_on_waiting=True)

    def some[T](self, atom: Atom[Option[T]], /) -> Effect[T]:
        if self.disposed or self.is_fn:
            return self.some_once(atom)
        found = self.get(atom)
        return never if found is None else _Succeed(found.value)

    def some_once[T](self, atom: Atom[Option[T]], /) -> Effect[T]:
        def register(resume: Callable[[Effect[T]], None]) -> Effect[None] | None:
            found = self.once(atom)
            if found is not None:
                resume(_Succeed(found.value))
                return None

            def on_change(value: Option[T]) -> None:
                if value is None:
                    return
                cancel()
                resume(_Succeed(value.value))

            cancel = self.node.registry.subscribe(atom, on_change)
            return _Sync(cancel)

        return _Callback(register)

    def self(self) -> Option[Any]:
        if self.disposed:
            return None
        return self.node.value_option()

    def refresh(self, atom: Atom[Any], /) -> None:
        if self.disposed:
            return
        self.node.registry.refresh(atom)

    def refresh_self(self) -> None:
        if self.disposed:
            return
        self.node.invalidate()

    def mount(self, atom: Atom[Any], /) -> None:
        if self.disposed:
            return
        self.add_finalizer(self.node.registry.mount(atom))

    def subscribe[T](
        self, atom: Atom[T], f: Callable[[T], None], /, *, immediate: bool = False
    ) -> None:
        if self.disposed:
            return
        self.add_finalizer(self.node.registry.subscribe(atom, f, immediate=immediate))

    def set_self(self, value: Any, /) -> None:
        if self.disposed:
            return
        self.node.set_value(value)

    def set[W](self, atom: Writable[Any, W], value: W, /) -> None:
        if self.disposed:
            return
        self.node.registry.set(atom, value)

    def stream[T](self, atom: Atom[T], /, *, without_initial_value: bool = False) -> Stream[T]:
        from pyfect import stream

        if self.disposed:
            return stream.empty

        def start(queue: Queue[T, Done]) -> Effect[None]:
            def offer(value: T) -> None:
                queue.offer_unsafe(value)

            return _Sync(lambda: self.subscribe(atom, offer, immediate=not without_initial_value))

        return stream.callback(start)

    def stream_result[T, E](
        self, atom: Atom[AsyncResult[T, E]], /, *, without_initial_value: bool = False
    ) -> Stream[T, E]:
        results = self.stream(atom, without_initial_value=without_initial_value)
        return results.filter(async_result.is_not_initial).map_effect(result_effect)

    def dispose(self) -> None:
        self.disposed = True
        finalizers = self.finalizers
        if finalizers is None:
            return
        self.finalizers = None
        run_all(reversed(finalizers), lambda f: f())


__all__ = ["Lifetime"]
