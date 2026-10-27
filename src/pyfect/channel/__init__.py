"""``Channel``: the pull-based building block under streams and sinks
(Effect v4's ``Channel``).

A ``Channel[OutElem, OutErr, OutDone, InElem, InErr, InDone, Env]`` reads
items from an upstream pull and writes its own, ending with a value or
failing. Each channel is a function from the upstream ``Pull`` and a scope
to its own pull (``from_transform``); running it builds the pulls and pulls
until the end::

    from pyfect import channel

    doubled = channel.from_iterable([1, 2, 3]).map(lambda n: n * 2)
    fx.run_sync(doubled.run_collect())  # [2, 4, 6]

Constructors are functions here; ``map``, ``concat``, ``pipe_to`` and the
``run_*`` functions are methods. Pull loops run on the fiber's own stack,
so channels of millions of items never touch Python's recursion limit.
"""

from pyfect.channel._channel import (
    Channel,
    from_pull,
    from_transform,
    to_transform,
    transform_pull,
)
from pyfect.channel._constructors import (
    DEFAULT_CHUNK_SIZE,
    acquire_release,
    acquire_use_release,
    die,
    empty,
    end,
    end_sync,
    fail,
    fail_cause,
    fail_cause_sync,
    fail_sync,
    from_effect,
    from_effect_done,
    from_effect_drain,
    from_effect_take,
    from_iterable,
    from_iterable_array,
    from_iterator,
    from_iterator_array,
    from_transform_bracket,
    identity,
    never,
    succeed,
    suspend,
    sync,
    unwrap,
)

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "Channel",
    "acquire_release",
    "acquire_use_release",
    "die",
    "empty",
    "end",
    "end_sync",
    "fail",
    "fail_cause",
    "fail_cause_sync",
    "fail_sync",
    "from_effect",
    "from_effect_done",
    "from_effect_drain",
    "from_effect_take",
    "from_iterable",
    "from_iterable_array",
    "from_iterator",
    "from_iterator_array",
    "from_pull",
    "from_transform",
    "from_transform_bracket",
    "identity",
    "never",
    "succeed",
    "suspend",
    "sync",
    "to_transform",
    "transform_pull",
    "unwrap",
]
