"""``Sink``: a consumer of a stream's items (Effect v4's ``Sink``).

A ``Sink[A, In, L, E, R]`` reads ``In`` items until it has what it needs,
then succeeds with ``A`` and leaves over the ``L`` items it read but did
not use; or fails with ``E``. Run one with ``Stream.run``::

    from pyfect import sink, stream

    fx.run_blocking(stream.range(0, 4).run(sink.sum()))  # 10

The functions here build sinks; methods (``map``, ``flat_map``,
``map_input``, ``catch_all``, ...) refine them, and the functions that
remove services (``provide_service``, ``provide_context``) are curried for
``.pipe``. Generic sinks that take no arguments are functions
(``collect()``, ``head()``, ``sum()``) so their item type can be
inferred; the others are values (``drain``, ``count``, ``never``,
``timed``).
"""

from pyfect.sink._constructors import (
    die,
    drain,
    fail,
    fail_cause,
    fail_cause_sync,
    fail_sync,
    from_channel,
    from_effect,
    from_effect_end,
    from_pubsub,
    from_queue,
    from_transform,
    make,
    never,
    succeed,
    suspend,
    sync,
    timed,
    to_channel,
)
from pyfect.sink._context import provide_context, provide_service, unwrap
from pyfect.sink._folds import (
    collect,
    count,
    every,
    find,
    find_effect,
    fold,
    fold_array,
    fold_until,
    head,
    last,
    reduce,
    reduce_array,
    reduce_effect,
    reduce_while,
    reduce_while_array,
    reduce_while_array_effect,
    reduce_while_effect,
    some,
)
from pyfect.sink._folds import sum_ as sum
from pyfect.sink._for_each import for_each, for_each_array, for_each_while, for_each_while_array
from pyfect.sink._sink import End, Sink, Upstream
from pyfect.sink._taking import (
    take,
    take_until,
    take_until_effect,
    take_while,
    take_while_effect,
    take_while_filter,
    take_while_filter_effect,
)

__all__ = [
    "End",
    "Sink",
    "Upstream",
    "collect",
    "count",
    "die",
    "drain",
    "every",
    "fail",
    "fail_cause",
    "fail_cause_sync",
    "fail_sync",
    "find",
    "find_effect",
    "fold",
    "fold_array",
    "fold_until",
    "for_each",
    "for_each_array",
    "for_each_while",
    "for_each_while_array",
    "from_channel",
    "from_effect",
    "from_effect_end",
    "from_pubsub",
    "from_queue",
    "from_transform",
    "head",
    "last",
    "make",
    "never",
    "provide_context",
    "provide_service",
    "reduce",
    "reduce_array",
    "reduce_effect",
    "reduce_while",
    "reduce_while_array",
    "reduce_while_array_effect",
    "reduce_while_effect",
    "some",
    "succeed",
    "sum",
    "suspend",
    "sync",
    "take",
    "take_until",
    "take_until_effect",
    "take_while",
    "take_while_effect",
    "take_while_filter",
    "take_while_filter_effect",
    "timed",
    "to_channel",
    "unwrap",
]
