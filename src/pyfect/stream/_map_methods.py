"""``Stream`` methods that map items, flat-map them into streams, tap
them, and put streams one after another."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Never

from pyfect.stream._base import A_co, E_co, R_co, StreamBase, as_stream, require_stream

if TYPE_CHECKING:
    from pyfect._concurrency import Concurrency
    from pyfect._core import Effect
    from pyfect.result import Result
    from pyfect.stream._stream import Stream
    from pyfect.take import Take


class MapMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    # --- mapping ------------------------------------------------------------

    def map[B](self, f: Callable[[A_co], B]) -> Stream[B, E_co, R_co]:
        """Apply ``f`` to each item."""
        from pyfect.stream import _mapping

        return _mapping.map_(self, f)

    def as_[B](self, value: B) -> Stream[B, E_co, R_co]:
        """Replace each item with ``value``."""
        from pyfect.stream import _mapping

        return _mapping.map_array(self, lambda chunk: (value,) * len(chunk))

    def map_both[B, E2](
        self, *, on_element: Callable[[A_co], B], on_error: Callable[[E_co], E2]
    ) -> Stream[B, E2, R_co]:
        """Apply ``on_element`` to each item and ``on_error`` to the error."""
        return self.map(on_element).map_error(on_error)

    def map_array[B](self, f: Callable[[tuple[A_co, ...]], tuple[B, ...]]) -> Stream[B, E_co, R_co]:
        """Apply ``f`` to each chunk (a non-empty tuple); an empty result
        writes nothing."""
        from pyfect.stream import _mapping

        return _mapping.map_array(self, f)

    def map_effect[B, E2 = Never, R2 = Never](
        self,
        f: Callable[[A_co], Effect[B, E2, R2]],
        *,
        concurrency: Concurrency = None,
        unordered: bool = False,
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """Write what ``f(item)`` succeeds with, one item per chunk. With
        ``concurrency`` above 1, up to that many run at once; their results
        keep upstream's order unless ``unordered``."""
        from pyfect.stream import _mapping

        return _mapping.map_effect(self, f, concurrency, unordered)

    def map_array_effect[B, E2 = Never, R2 = Never](
        self, f: Callable[[tuple[A_co, ...]], Effect[tuple[B, ...], E2, R2]]
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """Write the chunk ``f(chunk)`` succeeds with, for each chunk."""
        from pyfect.stream import _mapping

        return _mapping.map_array_effect(self, f)

    def flatten_effect[B, E2 = Never, R2 = Never](
        self: MapMethods[Effect[B, E2, R2], E_co, R_co],
        *,
        concurrency: Concurrency = None,
        unordered: bool = False,
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """Run each effect the stream writes and write its value."""
        from pyfect.stream import _mapping

        return _mapping.map_effect(self, _identity, concurrency, unordered)

    def result(self) -> Stream[Result[A_co, E_co], Never, R_co]:
        """Write each item as ``Ok``, then a typed failure as one last
        ``Err`` instead of failing."""
        from pyfect.stream import _mapping

        return _mapping.result(self)

    # --- tapping --------------------------------------------------------------

    def tap[E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[object, E2, R2]], *, concurrency: Concurrency = None
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``f`` on each item, then write the item."""
        from pyfect.stream import _mapping

        return _mapping.map_effect(self, lambda a: f(a).as_(a), concurrency, False)

    def tap_both[EE = Never, RR = Never](
        self,
        *,
        on_element: Callable[[A_co], Effect[object, EE, RR]],
        on_error: Callable[[E_co], Effect[object, EE, RR]],
        concurrency: Concurrency = None,
    ) -> Stream[A_co, E_co | EE, R_co | RR]:
        """``tap`` with ``on_element`` and ``tap_error`` with ``on_error``."""
        return as_stream(self).tap_error(on_error).tap(on_element, concurrency=concurrency)

    # --- flat-mapping ---------------------------------------------------------

    def flat_map[B, E2 = Never, R2 = Never](
        self,
        f: Callable[[A_co], StreamBase[B, E2, R2]],
        *,
        concurrency: Concurrency = None,
        buffer_size: int = 16,
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """Write the items of ``f(item)`` for each item, one stream after
        another; with ``concurrency`` above 1, up to that many at once,
        their items merged through a buffer of ``buffer_size``."""
        from pyfect.stream import _mapping

        return _mapping.flat_map(self, f, concurrency, buffer_size, switch=False)

    def switch_map[B, E2 = Never, R2 = Never](
        self,
        f: Callable[[A_co], StreamBase[B, E2, R2]],
        *,
        concurrency: Concurrency = 1,
        buffer_size: int = 16,
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """``flat_map`` where each new item interrupts the oldest running
        stream once ``concurrency`` are running."""
        from pyfect.stream import _mapping

        return _mapping.flat_map(self, f, concurrency, buffer_size, switch=True)

    def flatten[B, E2 = Never, R2 = Never](
        self: MapMethods[StreamBase[B, E2, R2], E_co, R_co],
        *,
        concurrency: Concurrency = None,
        buffer_size: int = 16,
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """Write the items of each stream this stream writes."""
        from pyfect.stream import _mapping

        return _mapping.flat_map(self, _identity, concurrency, buffer_size, switch=False)

    def flatten_array[B, E, R](self: MapMethods[tuple[B, ...], E, R]) -> Stream[B, E, R]:
        """Write the items of each tuple this stream writes, a tuple per
        chunk."""
        from pyfect.stream import _mapping

        return _mapping.flatten_array(self)

    def flatten_iterable[B, E, R](self: MapMethods[Iterable[B], E, R]) -> Stream[B, E, R]:
        """Write the items of each iterable this stream writes."""
        from pyfect.stream import _constructors

        return self.flat_map(_constructors.from_iterable)

    def flatten_take[B, E2](
        self: MapMethods[Take[B, E2], E_co, R_co],
    ) -> Stream[B, E_co | E2, R_co]:
        """Replay each ``Take``: write its items, or fail or end as it says."""
        from pyfect.stream import _mapping

        return _mapping.flatten_take(self)

    def drain(self) -> Stream[Never, E_co, R_co]:
        """Run the stream for its effects, writing nothing."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.drain())

    def drain_fork[E2 = Never, R2 = Never](
        self, that: Stream[object, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``that`` for its effects alongside this stream; its failure
        fails this stream, and it stops when this stream ends."""
        require_stream(that, "that")
        return as_stream(self).merge_effect(that.run_drain())

    # --- sequencing -----------------------------------------------------------

    def concat[B, E2 = Never, R2 = Never](
        self, that: Stream[B, E2, R2]
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]:
        """Write this stream's items, then ``that``'s. Each part's resources
        are released before the next starts; a chain of thousands of
        ``concat`` calls runs as one flat sequence."""
        from pyfect.stream import _concat

        require_stream(that, "that")
        return _concat.concat(self, that)

    def prepend[B](self, values: Iterable[B]) -> Stream[A_co | B, E_co, R_co]:
        """Write ``values`` first, then this stream's items."""
        from pyfect.stream import _concat, _constructors

        return _concat.concat(_constructors.from_iterable(values), self)

    def intersperse[B](self, element: B) -> Stream[A_co | B, E_co, R_co]:
        """Write ``element`` between each two items."""
        from pyfect.stream import _mapping

        return _mapping.intersperse(self, element)

    def intersperse_affixes[B, C, D](
        self, *, start: B, middle: C, end: D
    ) -> Stream[A_co | B | C | D, E_co, R_co]:
        """Write ``start``, the items with ``middle`` between each two, then
        ``end``."""
        from pyfect.stream import _concat, _constructors

        body = _concat.concat(_constructors.succeed(start), self.intersperse(middle))
        return _concat.concat(body, _constructors.succeed(end))

    def when[E2 = Never, R2 = Never](
        self, test: Effect[bool, E2, R2]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """This stream if ``test`` succeeds with ``True``, else an empty one;
        ``test`` runs each time the stream runs."""
        from pyfect._effect_args import require_effect
        from pyfect.stream import _constructors

        require_effect(test, "test")
        me = as_stream(self)
        return _constructors.unwrap(test.map(lambda ok: me if ok else _constructors.empty))


def _identity[T](value: T) -> T:
    return value
