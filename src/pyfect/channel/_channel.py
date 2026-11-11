"""The ``Channel`` type and the transforms every channel is made of.

A channel is a function from an upstream ``Pull`` and a ``CloseableScope``
to an effect building its own ``Pull`` (Effect v4's pull-based design).
Nothing runs until a run function or ``to_pull`` builds the pulls; the
scope collects the resources the channel opens and closes when the run
ends. ``Channel``'s methods come in groups, one module each (see
``pyfect.channel._base``).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.channel._base import (
    ChannelBase,
    Env_co,
    InDone_contra,
    InElem_contra,
    InErr_contra,
    OutDone_co,
    OutElem_co,
    OutErr_co,
    require_channel,
)
from pyfect.channel._concurrency_methods import ConcurrencyMethods
from pyfect.channel._error_methods import ErrorMethods
from pyfect.channel._lifecycle_methods import LifecycleMethods
from pyfect.channel._run_methods import RunMethods
from pyfect.channel._transform_methods import TransformMethods
from pyfect.errors import Done
from pyfect.scope import CloseableScope

if TYPE_CHECKING:
    from pyfect.pull import Pull


class Channel(
    TransformMethods[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ],
    ErrorMethods[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ],
    ConcurrencyMethods[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ],
    LifecycleMethods[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ],
    RunMethods[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ],
):
    """``Channel[OutElem, OutErr, OutDone, InElem, InErr, InDone, Env]``:
    reads ``InElem`` items from upstream until it fails with ``InErr`` or
    ends with ``InDone``; writes ``OutElem`` items, then fails with
    ``OutErr`` or ends with ``OutDone``; needs the services ``Env``.

    The defaults describe a source: no errors, ``None`` when done, any
    input (``object``), no services. A channel can run when it accepts an
    upstream that ends at once with ``None``.

    Build channels with the functions in ``pyfect.channel``; methods that
    keep or add to the type parameters are here. Combinators that remove
    something from a type (``catch_tag``, ``provide_service``, ...) are
    functions in ``pyfect.channel``, used with ``.pipe``.
    """

    __slots__ = ()


# --- building channels from transforms ---------------------------------------
#
# A transform's pull may end (``Done[L]``) or not, and may fail: each
# overload reads one shape, since pyright cannot take ``Done`` out of an error
# union. The upstream's error comes first so a pull that cannot fail is not
# read as ``InErr = Never`` too eagerly.


@overload
def from_transform[A, InElem, InErr, InDone, L = None, EE = Never, RR = Never](
    transform: Callable[
        [Effect[InElem, InErr | Done[InDone]], CloseableScope],
        Effect[Effect[A, Done[L], RR], EE, RR],
    ],
) -> Channel[A, EE, L, InElem, InErr, InDone, RR]: ...
@overload
def from_transform[A, InElem, InErr, InDone, L = None, EE = Never, RR = Never](
    transform: Callable[
        [Effect[InElem, InErr | Done[InDone]], CloseableScope],
        Effect[Effect[A, EE | Done[L], RR], EE, RR],
    ],
) -> Channel[A, EE, L, InElem, InErr, InDone, RR]: ...
@overload
def from_transform[A, InElem, InDone, L = None, EE = Never, RR = Never](
    transform: Callable[
        [Effect[InElem, Done[InDone]], CloseableScope], Effect[Effect[A, Done[L], RR], EE, RR]
    ],
) -> Channel[A, EE, L, InElem, Never, InDone, RR]: ...
@overload
def from_transform[A, InElem, InDone, L = None, EE = Never, RR = Never](
    transform: Callable[
        [Effect[InElem, Done[InDone]], CloseableScope],
        Effect[Effect[A, EE | Done[L], RR], EE, RR],
    ],
) -> Channel[A, EE, L, InElem, Never, InDone, RR]: ...
def from_transform[A, InElem, InDone, L = None, EE = Never, RR = Never](
    transform: Callable[
        [Effect[InElem, Done[InDone]], CloseableScope],
        Effect[Effect[A, EE | Done[L], RR], EE, RR],
    ],
) -> Channel[A, EE, L, InElem, Never, InDone, RR]:
    """A channel from ``transform(upstream, scope)``, an effect building
    the channel's pull from the upstream pull. The upstream pull fails with
    ``Done`` at its end (and with the upstream's error, if it has one).
    ``transform`` runs once per run of the channel, so state made in it
    belongs to that run. Resources go in ``scope``, closed when the run
    ends. If building the pull fails, the pull fails with that cause."""

    channel: Channel[Any, Any, Any, Any, Any, Any, Any] = Channel(transform)
    return channel


def to_transform[O, E, D, I, IE, ID, R](
    channel: ChannelBase[O, E, D, I, IE, ID, R],
) -> Callable[[Pull[I, IE, ID], CloseableScope], Effect[Pull[O, E, D], Never, R]]:
    """The function a channel is made of (see ``from_transform``)."""
    require_channel(channel, "channel")
    return channel._transform


@overload
def from_pull[A, EE = Never, RR = Never](
    make: Effect[Effect[A, Never, RR], EE, RR],
) -> Channel[A, EE, Never, object, object, object, RR]: ...
@overload
def from_pull[A, L = None, EE = Never, RR = Never](
    make: Effect[Effect[A, Done[L], RR], EE, RR],
) -> Channel[A, EE, L, object, object, object, RR]: ...
@overload
def from_pull[A, L = None, EE = Never, RR = Never](
    make: Effect[Effect[A, EE | Done[L], RR], EE, RR],
) -> Channel[A, EE, L, object, object, object, RR]: ...
def from_pull(make: Effect[Any, Any, Any]) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    """A source whose pull ``make`` builds each time the channel runs."""
    require_effect(make, "make")
    return Channel(lambda _upstream, _scope: make)


def transform_pull[O, E, D, I, IE, ID, R, O2, D2 = None, EE = Never, RR = Never](
    channel: ChannelBase[O, E, D, I, IE, ID, R],
    f: Callable[[Pull[O, E, D], CloseableScope], Effect[Pull[O2, EE, D2, RR], EE, RR]],
) -> Channel[O2, EE, D2, I, IE, ID, R | RR]:
    """A channel whose pull is ``f(pull, scope)`` of ``channel``'s pull."""
    require_channel(channel, "channel")
    inner = channel._transform
    transformed: Channel[O2, EE, D2, I, IE, ID, R | RR] = Channel(
        lambda upstream, scope: inner(upstream, scope).flat_map(lambda pull: f(pull, scope))
    )
    return transformed
