"""How far ``EventLog.synced`` has seen a remote (a pyfect addition).

A remote leaves a connection's own writes out of its change stream, as Effect's
does, and the journal's cursor moves across acks only when they continue straight
on from it. An ack that commits while an earlier sequence is still being replayed
is then never crossed by the cursor. The journal keeps Effect's cursor; ``synced``
steps over this log's own acknowledged sequences on top of it instead."""

from __future__ import annotations

import threading
from collections.abc import Iterable

from pyfect._core import Effect
from pyfect.effect import gen, sync
from pyfect.eventlog.event_journal import RemoteId


class OwnAcks:
    """The sequences each remote acknowledged for this log's uploads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._remotes: dict[RemoteId, tuple[int, frozenset[int]]] = {}
        self._epoch = 0

    def advance[E](
        self, remote_id: RemoteId, cursor: Effect[int, E], acked: Iterable[int] = ()
    ) -> Effect[int, E]:
        """Records ``acked`` and gives the first sequence of ``remote_id`` this log
        has neither read (below the journal's ``cursor``) nor had acknowledged,
        counting from the cursor without a gap."""
        pending = tuple(acked)

        def body():
            nonlocal pending
            while True:
                epoch = self._read_epoch()
                read = yield from cursor
                seen = self._step(remote_id, epoch, read, pending)
                if seen is not None:
                    return seen
                # The journal was destroyed meanwhile, with the acked entries.
                pending = ()

        return gen(body)

    def forgetting[A, E](self, destroy: Effect[A, E]) -> Effect[A, E]:
        """Runs ``destroy``, which empties the journal and resets its cursors, and
        forgets every ack and cursor read before it ended."""
        return sync(self._forget).and_then(destroy).tap(lambda _: sync(self._forget))

    def _read_epoch(self) -> int:
        with self._lock:
            return self._epoch

    def _forget(self) -> None:
        with self._lock:
            self._epoch += 1
            self._remotes.clear()

    def _step(
        self, remote_id: RemoteId, epoch: int, cursor: int, acked: tuple[int, ...]
    ) -> int | None:
        with self._lock:
            if epoch != self._epoch:
                return None
            next, ahead = self._remotes.get(remote_id, (0, frozenset[int]()))
            next = max(next, cursor)
            ahead = ahead.union(acked)
            while next in ahead:
                next += 1
            self._remotes[remote_id] = (next, frozenset(s for s in ahead if s > next))
            return next
