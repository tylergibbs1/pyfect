"""How far ``EventLog.synced`` has seen a remote (a pyfect addition).

A remote leaves a connection's own writes out of its change stream, as Effect's
does, and the journal's cursor moves across acks only when they continue straight
on from it. An ack that commits while an earlier sequence is still being replayed
is then never crossed by the cursor. The journal keeps Effect's cursor; ``synced``
steps over this log's own acknowledged sequences on top of it instead.

Once the log is destroyed nothing it saw holds: the journal is empty, its cursors
are back at 0, and the change stream does not start again (as in Effect)."""

from __future__ import annotations

import threading
from collections.abc import Iterable

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.effect import sync
from pyfect.eventlog.event_journal import RemoteId


class OwnAcks:
    """The sequences each remote acknowledged for this log's uploads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._remotes: dict[RemoteId, tuple[int, frozenset[int]]] = {}
        self._destroyed = False

    @property
    def destroyed(self) -> bool:
        """Whether the log's destroy has started."""
        return self._destroyed

    def advance(self, remote_id: RemoteId, cursor: int, acked: Iterable[int] = ()) -> int:
        """Records ``acked`` and gives the first sequence of ``remote_id`` this log
        has neither read (below the journal's ``cursor``) nor had acknowledged,
        counting from the cursor without a gap."""
        with self._lock:
            next, ahead = self._remotes.get(remote_id, (0, frozenset[int]()))
            next = max(next, cursor)
            ahead = ahead.union(acked)
            while next in ahead:
                next += 1
            self._remotes[remote_id] = (next, frozenset(s for s in ahead if s > next))
            return next

    def destroying[A, E](self, destroy: Effect[A, E]) -> Effect[A, E]:
        """Marks the log destroyed, then runs ``destroy``."""
        require_effect(destroy, "destroy")

        def mark() -> None:
            self._destroyed = True

        return sync(mark).and_then(destroy)
