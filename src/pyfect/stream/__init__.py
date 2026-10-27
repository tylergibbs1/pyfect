"""``Stream``: a pull-based stream of items written in chunks (Effect v4's
``Stream``).

A ``Stream[A, E, R]`` writes items of type ``A``, then fails with ``E``
or ends; it needs the services ``R``. It is a ``Channel`` writing
non-empty tuples of items (``stream.channel``), so a stream moves a chunk
at a time while its functions take one item at a time::

    from pyfect import stream

    fx.run_sync(stream.range(0, 5).run_collect())  # [0, 1, 2, 3, 4]

Constructors are functions here, and so are the combinators that remove
something from a stream's type (``scoped``, ``catch_tag``, ``catch_if``),
used with ``.pipe``, and the ones combining any number of streams
(``merge_all``, ``zip_latest_all``, ``race_all``); the rest (``map``,
``flat_map``, ``take``, ``zip``, ``merge``, ``catch_all``, ``debounce``,
``run_collect``, ``to_pull``, ...) are methods.
``range`` follows Python's ``range`` and leaves its end out;
``range_inclusive`` is Effect's ``range``.
"""

from pyfect.stream._catch import catch_if_refinement as catch_if
from pyfect.stream._catch import catch_tag
from pyfect.stream._constructors import (
    DEFAULT_CHUNK_SIZE,
    die,
    empty,
    fail,
    fail_cause,
    fail_cause_sync,
    fail_sync,
    from_arrays,
    from_effect,
    from_effect_drain,
    from_effect_repeat,
    from_effect_schedule,
    from_iterable,
    from_iterable_effect,
    from_iterable_effect_repeat,
    iterate,
    make,
    never,
    paginate,
    range,
    range_inclusive,
    scoped,
    service,
    service_option,
    succeed,
    suspend,
    sync,
    unfold,
    unwrap,
)
from pyfect.stream._many import merge_all, race_all, zip_latest_all
from pyfect.stream._sources import (
    callback,
    from_async_iterable,
    from_pubsub,
    from_pubsub_take,
    from_queue,
    from_schedule,
    from_subscription,
    tick,
)
from pyfect.stream._stream import (
    Stream,
    from_channel,
    from_pull,
    to_channel,
    transform_pull,
    transform_pull_bracket,
)

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "Stream",
    "callback",
    "catch_if",
    "catch_tag",
    "die",
    "empty",
    "fail",
    "fail_cause",
    "fail_cause_sync",
    "fail_sync",
    "from_arrays",
    "from_async_iterable",
    "from_channel",
    "from_effect",
    "from_effect_drain",
    "from_effect_repeat",
    "from_effect_schedule",
    "from_iterable",
    "from_iterable_effect",
    "from_iterable_effect_repeat",
    "from_pubsub",
    "from_pubsub_take",
    "from_pull",
    "from_queue",
    "from_schedule",
    "from_subscription",
    "iterate",
    "make",
    "merge_all",
    "never",
    "paginate",
    "race_all",
    "range",
    "range_inclusive",
    "scoped",
    "service",
    "service_option",
    "succeed",
    "suspend",
    "sync",
    "tick",
    "to_channel",
    "transform_pull",
    "transform_pull_bracket",
    "unfold",
    "unwrap",
    "zip_latest_all",
]
