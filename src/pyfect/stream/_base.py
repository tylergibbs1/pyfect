"""What every stream shares: the type parameters, the channel it is made
of, and the base of ``Stream``'s method groups.

``Stream`` (``pyfect.stream._stream``) is assembled from method groups,
each a subclass of ``StreamBase`` in a module of its own, as ``Channel``
is. A group's methods give their work to implementation modules imported
when called (they build ``Stream`` values, so they load after it).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Generic, Never, Self, TypeVar, cast

from pyfect._effect_args import wrong_argument

if TYPE_CHECKING:
    from pyfect.channel import Channel
    from pyfect.stream._stream import Stream

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)

type StreamChannel[A, E = Never, R = Never] = Channel[
    tuple[A, ...], E, None, object, object, object, R
]
"""The channel under a ``Stream[A, E, R]``: it writes non-empty tuples of
``A``, needs no input and ends with ``None``."""


class StreamBase(Generic[A_co, E_co, R_co]):
    """The base of each group of ``Stream`` methods. Every instance is a
    ``Stream``: only ``Stream`` combines the groups."""

    __slots__ = ("_channel",)

    def __init__(self, channel: StreamChannel[A_co, E_co, R_co]) -> None:
        self._channel = channel

    @property
    def channel(self) -> StreamChannel[A_co, E_co, R_co]:
        """The channel this stream is made of (Effect's ``stream.channel``)."""
        return self._channel

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        """Apply ``f`` to this stream (one step; see ``Effect.pipe``)."""
        return f(self)


type AnyStream = StreamBase[Any, Any, Any]


def as_stream[A, E, R](stream: StreamBase[A, E, R]) -> Stream[A, E, R]:
    """A method group's ``self`` as the ``Stream`` it is."""
    return cast("Stream[A, E, R]", stream)


def require_stream(value: object, name: str) -> None:
    """Raise ``TypeError`` naming ``name`` unless ``value`` is a ``Stream``."""
    if not isinstance(value, StreamBase):
        raise TypeError(wrong_argument(value, name, "a Stream", "build one with pyfect.stream"))


def require_streams(values: Iterable[object], name: str) -> None:
    """``require_stream`` for each of a ``*args`` parameter's values,
    naming the bad one ``name[i]``."""
    for i, value in enumerate(values):
        require_stream(value, f"{name}[{i}]")
