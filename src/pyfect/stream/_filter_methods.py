"""``Stream`` methods that keep some items: filtering, taking, dropping and
dropping repeats.

Counts are ``int``s; a count below zero counts as zero. Predicates take
the item only (``enumerate`` the stream with ``zip_with_index`` for its
position). A filter is a function returning ``Ok(value)`` to keep
``value`` or ``Err(...)`` to drop the item (Effect's ``Filter``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Never, TypeIs, overload

from pyfect._equal import equals
from pyfect.result import Ok, Result
from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.stream._stream import Stream


class FilterMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    # --- filtering ------------------------------------------------------------

    @overload
    def filter[B](self, predicate: Callable[[A_co], TypeIs[B]]) -> Stream[B, E_co, R_co]: ...
    @overload
    def filter(self, predicate: Callable[[A_co], bool]) -> Stream[A_co, E_co, R_co]: ...
    def filter(self, predicate: Callable[[A_co], bool]) -> Stream[object, E_co, R_co]:
        """Keep the items that pass ``predicate``."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.filter_array(predicate))

    def filter_map[B](self, f: Callable[[A_co], Result[B, object]]) -> Stream[B, E_co, R_co]:
        """Write ``value`` for each item ``f`` maps to ``Ok(value)``; drop
        the items it maps to ``Err``."""
        from pyfect.stream import _taking

        return _taking.filter_map(self, f)

    def filter_effect[E2 = Never, R2 = Never](
        self, predicate: Callable[[A_co], Effect[bool, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Keep the items whose ``predicate`` succeeds with ``True``."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.filter_array_effect(predicate))

    def filter_map_effect[B, E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[Result[B, object], E2, R2]]
    ) -> Stream[B, E_co | E2, R_co | R2]:
        """``filter_map`` with an effectful ``f``."""
        from pyfect.stream import _taking

        return _taking.filter_map_effect(self, f)

    # --- taking ---------------------------------------------------------------

    def take(self, n: int) -> Stream[A_co, E_co, R_co]:
        """The first ``n`` items; then end without pulling again."""
        from pyfect.stream import _taking

        return _taking.take(self, n)

    def take_right(self, n: int) -> Stream[A_co, E_co, R_co]:
        """The last ``n`` items, written when the stream ends."""
        from pyfect.stream import _taking

        return _taking.take_right(self, n)

    def take_until(
        self, predicate: Callable[[A_co], bool], *, exclude_last: bool = False
    ) -> Stream[A_co, E_co, R_co]:
        """Items up to and including the first that passes ``predicate``
        (excluding it with ``exclude_last``); then end."""
        from pyfect.stream import _taking

        return _taking.take_until(self, predicate, exclude_last)

    def take_until_effect[E2 = Never, R2 = Never](
        self, predicate: Callable[[A_co], Effect[bool, E2, R2]], *, exclude_last: bool = False
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """``take_until`` with an effectful ``predicate``."""
        from pyfect.stream import _taking

        return _taking.take_until_effect(self, predicate, exclude_last)

    @overload
    def take_while[B](self, predicate: Callable[[A_co], TypeIs[B]]) -> Stream[B, E_co, R_co]: ...
    @overload
    def take_while(self, predicate: Callable[[A_co], bool]) -> Stream[A_co, E_co, R_co]: ...
    def take_while(self, predicate: Callable[[A_co], bool]) -> Stream[object, E_co, R_co]:
        """Items while they pass ``predicate``; end at the first that fails."""
        from pyfect.stream import _taking

        return _taking.take_while(self, predicate)

    def take_while_filter[B](self, f: Callable[[A_co], Result[B, object]]) -> Stream[B, E_co, R_co]:
        """Write ``value`` while ``f`` maps items to ``Ok(value)``; end at the
        first ``Err``."""
        from pyfect.stream import _taking

        return _taking.take_while_filter(self, f)

    def take_while_effect[E2 = Never, R2 = Never](
        self, predicate: Callable[[A_co], Effect[bool, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """``take_while`` with an effectful ``predicate``."""
        from pyfect.stream import _taking

        return _taking.take_until_effect(self, lambda a: predicate(a).map(_not), True)

    def limit_bytes[E, R](
        self: FilterMethods[bytes, E, R],
        limit: int,
        on_limit_reached: Callable[[], Stream[bytes, E, R]],
    ) -> Stream[bytes, E, R]:
        """Byte strings while their total length stays within ``limit``;
        the first one that would cross it is dropped and the stream goes on
        with ``on_limit_reached()`` instead."""
        from pyfect.stream import _taking

        return _taking.limit_bytes(self, limit, on_limit_reached)

    # --- dropping -------------------------------------------------------------

    def drop(self, n: int) -> Stream[A_co, E_co, R_co]:
        """All but the first ``n`` items."""
        from pyfect.stream import _taking

        return _taking.drop(self, n)

    def drop_right(self, n: int) -> Stream[A_co, E_co, R_co]:
        """All but the last ``n`` items (each written once ``n`` later ones
        have come)."""
        from pyfect.stream import _taking

        return _taking.drop_right(self, n)

    def drop_while(self, predicate: Callable[[A_co], bool]) -> Stream[A_co, E_co, R_co]:
        """Drop items while they pass ``predicate``; write the rest."""
        from pyfect.stream import _taking

        return _taking.drop_while(self, predicate)

    def drop_while_filter(
        self, f: Callable[[A_co], Result[object, object]]
    ) -> Stream[A_co, E_co, R_co]:
        """Drop items while ``f`` maps them to ``Ok``; write the rest."""
        from pyfect.stream import _taking

        return _taking.drop_while(self, lambda a: isinstance(f(a), Ok))

    def drop_while_effect[E2 = Never, R2 = Never](
        self, predicate: Callable[[A_co], Effect[bool, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """``drop_while`` with an effectful ``predicate``."""
        from pyfect.stream import _taking

        return _taking.drop_while_effect(self, predicate)

    def drop_until(self, predicate: Callable[[A_co], bool]) -> Stream[A_co, E_co, R_co]:
        """Drop items up to and including the first that passes
        ``predicate``."""
        return self.drop_while(lambda a: not predicate(a)).drop(1)

    def drop_until_effect[E2 = Never, R2 = Never](
        self, predicate: Callable[[A_co], Effect[bool, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """``drop_until`` with an effectful ``predicate``."""
        return self.drop_while_effect(lambda a: predicate(a).map(_not)).drop(1)

    # --- repeats --------------------------------------------------------------

    def changes(self) -> Stream[A_co, E_co, R_co]:
        """Drop each item ``Equal.equals`` calls equal to the one written
        before it (``True`` is not ``1``, NaN is NaN)."""
        from pyfect.stream import _taking

        return _taking.changes_with(self, equals)

    def changes_with(self, f: Callable[[A_co, A_co], bool]) -> Stream[A_co, E_co, R_co]:
        """Drop each item ``f(item, last_written)`` calls the same."""
        from pyfect.stream import _taking

        return _taking.changes_with(self, f)

    def changes_with_effect[E2 = Never, R2 = Never](
        self, f: Callable[[A_co, A_co], Effect[bool, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """``changes_with`` with an effectful ``f``."""
        from pyfect.stream import _taking

        return _taking.changes_with_effect(self, f)


def _not(value: bool) -> bool:
    return not value
