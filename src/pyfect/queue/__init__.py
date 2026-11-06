"""``Queue[A, E]``: an async queue fibers can share.

Capacity and overflow behavior are fixed at creation:

- ``"suspend"`` (default): ``offer`` waits while the queue is full.
  Capacity 0 is a rendezvous: an offer completes when a taker takes it.
- ``"dropping"``: ``offer`` on a full queue drops the new item.
- ``"sliding"``: ``offer`` on a full queue drops the oldest item. As in
  Effect, ``sliding(0)`` keeps the newest offered item without waking a
  parked taker (the next take gets it), while ``offer_all`` to it keeps
  nothing.

A queue can be finished. After ``fail(error)`` (or ``interrupt()``), new
offers return ``False``, but takers still drain the items and the offers
that were already waiting, and then fail with ``error``. A queue that should
be endable declares it in its type, ``Queue[int, Done]``; only then do
``end()`` and ``into(eff)`` type-check, takers fail with ``Done()`` once it
drains, and ``collect`` / ``clear`` / ``await_done`` take ``Done`` out of the
error type. ``shutdown()`` drops everything at once: items are cleared,
waiting offers return ``False`` and takers are interrupted.

``Enqueue`` and ``Dequeue`` are the write-only and read-only views of a
queue, for passing it to code that only offers or only takes.

The ``unsafe_*`` methods act at once, outside an effect; call them on the
scheduler thread of the fibers that use the queue.
"""

from pyfect.errors import Done
from pyfect.queue._queue import Queue, Strategy
from pyfect.queue._views import Dequeue, Enqueue

__all__ = ["Dequeue", "Done", "Enqueue", "Queue", "Strategy"]
