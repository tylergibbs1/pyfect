"""A stand-in for ``Stream.provideService``, built on the stream's channel
until the Stream context functions are added. Curried for ``.pipe``, as
Effect's is."""

from collections.abc import Callable
from typing import Any

from pyfect import channel, stream

type _Stream = stream.Stream[Any, Any, Any]


def provide_service(tag: Any, service: object) -> Callable[[_Stream], _Stream]:
    """``Stream.provideService(tag, service)``."""
    return lambda source: stream.from_channel(
        source.channel.pipe(channel.provide_service(tag, service))
    )
