from collections.abc import Callable, Iterable

import pyfect as fx
from pyfect.option import Option
from pyfect.pubsub import Atomic, PubSub, SlidingStrategy, Subscribers


class CountingSliding[A](SlidingStrategy[A]):
    """Slides as the built-in does, and counts the messages that did not fit."""

    def __init__(self) -> None:
        self.surplus = 0

    def handle_surplus(
        self,
        pubsub: Atomic[A],
        subscribers: Subscribers[A],
        elements: Iterable[A],
        is_shutdown: Callable[[], bool],
        ended: Callable[[], Option[A]],
    ) -> fx.Effect[bool]:
        items = list(elements)
        self.surplus += len(items)
        return super().handle_surplus(pubsub, subscribers, items, is_shutdown, ended)


strategy = CountingSliding[int]()


@fx.gen
def program():
    # The store holds two unread messages; the strategy decides what a full one does.
    pubsub = yield from PubSub.make(lambda: Atomic[int].bounded(2), lambda: strategy)
    subscription = yield from pubsub.subscribe()
    yield from pubsub.publish_all(range(5))
    return (yield from subscription.take_all())


print(fx.run_blocking(fx.scoped(program)), strategy.surplus)
