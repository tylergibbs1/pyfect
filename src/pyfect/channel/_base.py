"""What every channel shares: the type parameters, the transform it is
made of, and the base of ``Channel``'s method groups.

``Channel`` (``pyfect.channel._channel``) is assembled from method groups,
each a subclass of ``ChannelBase`` in a module of its own, as ``Effect``
is. A group's methods give their work to the implementation modules,
imported when called (they build ``Channel`` values, so they load after
it).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, Never, Self, TypeIs, TypeVar, cast

from pyfect._core import Effect, _FailCause, _MatchCause, _Suspend
from pyfect._effect_args import wrong_argument
from pyfect.cause import fail as fail_cause
from pyfect.errors import Done
from pyfect.exit import Success
from pyfect.scope import CloseableScope

if TYPE_CHECKING:
    from pyfect.channel._channel import Channel

OutElem_co = TypeVar("OutElem_co", covariant=True)
OutErr_co = TypeVar("OutErr_co", covariant=True, default=Never)
OutDone_co = TypeVar("OutDone_co", covariant=True, default=None)
InElem_contra = TypeVar("InElem_contra", contravariant=True, default=object)
InErr_contra = TypeVar("InErr_contra", contravariant=True, default=object)
InDone_contra = TypeVar("InDone_contra", contravariant=True, default=object)
Env_co = TypeVar("Env_co", covariant=True, default=Never)

type AnyPull = Effect[Any, Any, Any]
type Transform = Callable[[AnyPull, CloseableScope], Effect[AnyPull, Any, Any]]
"""What a channel is made of. It may fail or raise: ``ChannelBase._transform``
turns that into a failing pull."""


class ChannelBase(
    Generic[OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]
):
    """The base of each group of ``Channel`` methods. Every instance is a
    ``Channel``: only ``Channel`` combines the groups."""

    __slots__ = ("_build",)

    def __init__(self, transform: Transform) -> None:
        self._build = transform

    def _transform(self, upstream: AnyPull, scope: CloseableScope) -> Effect[AnyPull, Never, Any]:
        """The effect building this channel's pull. It never fails: a build
        that fails or raises gives a pull failing with that cause. Building
        waits until the effect runs, so channels nested thousands deep build
        on the fiber's stack, not Python's."""
        build = self._build
        return _MatchCause(_Suspend(lambda: build(upstream, scope)), _pull_failing, None)

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        """Apply ``f`` to this channel (one step; see ``Effect.pipe``)."""
        return f(self)


type AnyChannel = ChannelBase[Any, Any, Any, Any, Any, Any, Any]


def as_channel[O, E, D, I, IE, ID, R](
    channel: ChannelBase[O, E, D, I, IE, ID, R],
) -> Channel[O, E, D, I, IE, ID, R]:
    """A method group's ``self`` as the ``Channel`` it is."""
    return cast("Channel[O, E, D, I, IE, ID, R]", channel)


def end_with(leftover: object) -> Effect[Never, Done[Any]]:
    """A pull that ends with ``Done(leftover)``."""
    return _FailCause(fail_cause(Done(leftover)))


def is_done(error: object) -> TypeIs[Done[Any]]:
    """Whether a pull's error is its end rather than a failure."""
    return isinstance(error, Done)


def require_channel(value: object, name: str) -> None:
    """Raise ``TypeError`` naming ``name`` unless ``value`` is a ``Channel``."""
    if not isinstance(value, ChannelBase):
        raise TypeError(wrong_argument(value, name, "a Channel", "build one with pyfect.channel"))


def _pull_failing(cause: Any) -> Success[AnyPull]:
    return Success(_FailCause(cause))
