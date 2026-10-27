"""``Stream`` methods that run a stream: the ``run_*`` folds and
``to_pull``. Each runs the stream's channel; the item-by-item work is in
``pyfect.stream._run``."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Never

from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.option import Option
    from pyfect.pull import Pull
    from pyfect.scope import Scope


class RunMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    def run_collect(self) -> Effect[list[A_co], E_co, R_co]:
        """Run the stream and collect its items."""
        from pyfect.stream import _run

        return _run.run_collect(self)

    def run_drain(self) -> Effect[None, E_co, R_co]:
        """Run the stream, dropping its items."""
        return self._channel.run_drain()

    def run_count(self) -> Effect[int, E_co, R_co]:
        """Run the stream and count its items."""
        from pyfect.stream import _run

        return _run.run_count(self)

    def run_sum[N: (int, float), E, R](self: RunMethods[N, E, R]) -> Effect[N, E, R]:
        """Run a stream of numbers and add them up (``0`` when empty)."""
        from pyfect.stream import _run

        return _run.run_sum(self)

    def run_fold[Z](
        self, initial: Callable[[], Z], f: Callable[[Z, A_co], Z]
    ) -> Effect[Z, E_co, R_co]:
        """Fold the items into ``initial()`` with ``f``."""
        from pyfect.stream import _run

        return _run.run_fold(self, initial, f)

    def run_fold_effect[Z, E2 = Never, R2 = Never](
        self, initial: Callable[[], Z], f: Callable[[Z, A_co], Effect[Z, E2, R2]]
    ) -> Effect[Z, E_co | E2, R_co | R2]:
        """Fold the items into ``initial()`` with the effect ``f``, one item
        at a time."""
        from pyfect.stream import _run

        return _run.run_fold_effect(self, initial, f)

    def run_head(self) -> Effect[Option[A_co], E_co, R_co]:
        """The first item (``Some``), or ``None`` for an empty stream. Stops
        the stream after its first chunk."""
        from pyfect.stream import _run

        return _run.run_head(self)

    def run_last(self) -> Effect[Option[A_co], E_co, R_co]:
        """The last item (``Some``), or ``None`` for an empty stream."""
        from pyfect.stream import _run

        return _run.run_last(self)

    def run_for_each[E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[object, E2, R2]]
    ) -> Effect[None, E_co | E2, R_co | R2]:
        """Run ``f`` on each item, in order."""
        from pyfect.stream import _run

        return _run.run_for_each(self, f)

    def run_for_each_while[E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[bool, E2, R2]]
    ) -> Effect[None, E_co | E2, R_co | R2]:
        """Run ``f`` on each item until it succeeds with ``False``; the
        stream stops there."""
        from pyfect.stream import _run

        return _run.run_for_each_while(self, f)

    def run_for_each_array[E2 = Never, R2 = Never](
        self, f: Callable[[tuple[A_co, ...]], Effect[object, E2, R2]]
    ) -> Effect[None, E_co | E2, R_co | R2]:
        """Run ``f`` on each chunk (a non-empty tuple), in order."""
        return self._channel.run_for_each(f)

    def run_string[E, R](self: RunMethods[str, E, R]) -> Effect[str, E, R]:
        """Run a stream of strings and join them (Effect's ``mkString``)."""
        from pyfect.stream import _run

        return _run.run_string(self)

    def run_bytes[E, R](self: RunMethods[bytes, E, R]) -> Effect[bytes, E, R]:
        """Run a stream of byte strings and join them (Effect's
        ``mkUint8Array`` and ``mkArrayBuffer``)."""
        from pyfect.stream import _run

        return _run.run_bytes(self)

    def to_pull(self) -> Effect[Pull[tuple[A_co, ...], E_co], Never, R_co | Scope]:
        """Build the stream's pull in the current ``Scope``, which holds its
        resources. Each pull succeeds with the next chunk or fails with
        ``Done()`` at the end; fibers pulling at once take turns."""
        return self._channel.to_pull()
