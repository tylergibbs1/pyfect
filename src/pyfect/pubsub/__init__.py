"""``PubSub[A]``: a hub that delivers every published message to every
subscriber.

A subscriber reads the messages published after it subscribed (plus up to
``replay`` earlier ones), in order, through a ``Subscription`` that lasts
until its scope closes. A message is stored once and dropped when every
subscriber that owed it has read it. What happens when ``capacity``
messages are unread is fixed at creation:

- ``bounded``: publishers wait until the slowest subscriber reads.
- ``dropping``: the new message is dropped and the publish returns ``False``.
- ``sliding``: the oldest unread message is dropped for everyone.
- ``unbounded``: the hub is never full.

A message published while nobody is subscribed goes only to the replay
buffer. ``end(value)`` stops publishing: subscribers read what is left, and
then every ``take`` succeeds with ``value``. ``shutdown()`` unsubscribes
everyone, interrupting their takes; later publishes return ``False``.

Takes waiting on one subscription are served in the order they started.

What a full hub does is a ``Strategy`` object (Effect's ``PubSub.Strategy``):
``BackPressureStrategy``, ``DroppingStrategy`` and ``SlidingStrategy`` are
the built-ins, and ``PubSub.make(atomic, strategy)`` takes any, including
one written by the user. ``"suspend"``, ``"dropping"`` and ``"sliding"``
name the built-ins.

``Atomic`` is the store under a hub, with no waiting, for building a hub
with ``PubSub.make``. The ``unsafe_*`` methods act at once, outside an
effect; call them on the scheduler thread of the hub's fibers.
"""

from pyfect.pubsub._atomic import Atomic, BackingSubscription
from pyfect.pubsub._pubsub import PubSub
from pyfect.pubsub._replay import ReplayWindow
from pyfect.pubsub._strategies import (
    BackPressureStrategy,
    DroppingStrategy,
    SlidingStrategy,
    StrategyName,
)
from pyfect.pubsub._strategy import Poller, Pollers, Strategy, Subscribers
from pyfect.pubsub._subscription import Subscription

__all__ = [
    "Atomic",
    "BackPressureStrategy",
    "BackingSubscription",
    "DroppingStrategy",
    "Poller",
    "Pollers",
    "PubSub",
    "ReplayWindow",
    "SlidingStrategy",
    "Strategy",
    "StrategyName",
    "Subscribers",
    "Subscription",
]
