"""``TxQueue[A, E]``: a queue read and written in transactions (Effect's
``TxQueue``).

Capacity and overflow behavior are fixed at creation: ``bounded`` (``offer``
waits while full), ``unbounded``, ``dropping`` (a full queue drops the new
item) and ``sliding`` (a full queue drops its oldest item). Waiting is
``tx_retry``: inside a larger transaction, a full ``offer`` or an empty
``take`` reruns the whole transaction once the queue changes.

A queue can be finished. ``fail_cause(cause)``, ``interrupt()`` and
``end()`` close it: new offers return ``False``, takers drain what is left
and then fail with the cause. ``fail(error)`` and ``shutdown()`` drop the
items and finish it at once. A queue that should be endable declares it in
its type, ``TxQueue[int, Done]``; only then does ``end()`` type-check, and
``clear`` takes ``Done`` out of the error type. ``await_completion`` waits
for a finished queue however it finished.

``TxEnqueue`` and ``TxDequeue`` are the write-only and read-only views;
``isinstance(x, TxQueue)`` is Effect's ``isTxQueue`` (and ``isTxEnqueue`` /
``isTxDequeue``, since every view is a ``TxQueue``).
"""

from pyfect.errors import Done
from pyfect.tx_queue._queue import Strategy, TxQueue
from pyfect.tx_queue._views import TxDequeue, TxEnqueue

__all__ = ["Done", "Strategy", "TxDequeue", "TxEnqueue", "TxQueue"]
