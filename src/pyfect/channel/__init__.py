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

Constructors are functions here, and so are the combinators that remove
something from a channel's type (``catch_tag``, ``catch_if``, the
``provide*`` functions, ``scoped``), used with ``.pipe``; everything else
(``map``, ``merge``, ``catch_all``, the ``run_*`` functions, ...) is a
method. Pull loops run on the fiber's own stack,
so channels of millions of items never touch Python's recursion limit.
"""

from pyfect._public import publish
from pyfect.channel._catch import catch_if, catch_tag
from pyfect.channel._catch_reason import catch_reason, catch_reasons, unwrap_reason
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
from pyfect.channel._context import (
    provide,
    provide_context,
    provide_service,
    provide_service_effect,
    scoped,
    update_context,
)
from pyfect.channel._sources import (
    callback,
    callback_array,
    from_async_iterable,
    from_async_iterable_array,
    from_pubsub,
    from_pubsub_array,
    from_pubsub_take,
    from_queue,
    from_queue_array,
    from_schedule,
    from_subscription,
    from_subscription_array,
)
from pyfect.channel._text import (
    LineTooLongError,
    decode_text,
    encode_text,
    split_lines,
    split_lines_within,
)

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "Channel",
    "LineTooLongError",
    "acquire_release",
    "acquire_use_release",
    "callback",
    "callback_array",
    "catch_if",
    "catch_reason",
    "catch_reasons",
    "catch_tag",
    "decode_text",
    "die",
    "empty",
    "encode_text",
    "end",
    "end_sync",
    "fail",
    "fail_cause",
    "fail_cause_sync",
    "fail_sync",
    "from_async_iterable",
    "from_async_iterable_array",
    "from_effect",
    "from_effect_done",
    "from_effect_drain",
    "from_effect_take",
    "from_iterable",
    "from_iterable_array",
    "from_iterator",
    "from_iterator_array",
    "from_pubsub",
    "from_pubsub_array",
    "from_pubsub_take",
    "from_pull",
    "from_queue",
    "from_queue_array",
    "from_schedule",
    "from_subscription",
    "from_subscription_array",
    "from_transform",
    "from_transform_bracket",
    "identity",
    "never",
    "provide",
    "provide_context",
    "provide_service",
    "provide_service_effect",
    "scoped",
    "split_lines",
    "split_lines_within",
    "succeed",
    "suspend",
    "sync",
    "to_transform",
    "transform_pull",
    "unwrap",
    "unwrap_reason",
    "update_context",
]

publish(globals())
