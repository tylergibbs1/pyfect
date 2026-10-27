"""The ``Channel`` type and the transforms every channel is made of.

A channel is a function from an upstream ``Pull`` and a ``CloseableScope``
to an effect building its own ``Pull`` (Effect v4's pull-based design).
Nothing runs until a run function or ``to_pull`` builds the pulls; the
scope collects the resources the channel opens and closes when the run
ends.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, Never, Self, TypeVar, overload

from pyfect._core import Effect, _FailCause, _MatchCause, _Suspend
from pyfect._effect_args import require_effect, wrong_argument
from pyfect.errors import Done
from pyfect.exit import Success
from pyfect.scope import CloseableScope

if TYPE_CHECKING:
    from pyfect.option import Option
    from pyfect.pull import Pull
    from pyfect.scope import Scope

OutElem_co = TypeVar("OutElem_co", covariant=True)
OutErr_co = TypeVar("OutErr_co", covariant=True, default=Never)
OutDone_co = TypeVar("OutDone_co", covariant=True, default=None)
InElem_contra = TypeVar("InElem_contra", contravariant=True, default=object)
InErr_contra = TypeVar("InErr_contra", contravariant=True, default=object)
InDone_contra = TypeVar("InDone_contra", contravariant=True, default=object)
Env_co = TypeVar("Env_co", covariant=True, default=Never)

type AnyPull = Effect[Any, Any, Any]
type Transform = Callable[[AnyPull, CloseableScope], Effect[AnyPull, Any, Any]]
"""What a channel is made of. It may fail or raise: ``Channel._transform``
turns that into a failing pull."""


class Channel(
    Generic[OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]
):
    """``Channel[OutElem, OutErr, OutDone, InElem, InErr, InDone, Env]``:
    reads ``InElem`` items from upstream until it fails with ``InErr`` or
    ends with ``InDone``; writes ``OutElem`` items, then fails with
    ``OutErr`` or ends with ``OutDone``; needs the services ``Env``.

    The defaults describe a source: no errors, ``None`` when done, any
    input (``object``), no services. A channel can run when it accepts an
    upstream that ends at once with ``None``.

    Build channels with the functions in ``pyfect.channel``; methods that
    keep or add to the type parameters are here.
    """

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

    # --- transforming -------------------------------------------------------

    def map[B](
        self, f: Callable[[OutElem_co], B]
    ) -> Channel[B, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Apply ``f`` to each item written."""
        return _combinators.map_(self, f)

    def map_done[D2](
        self, f: Callable[[OutDone_co], D2]
    ) -> Channel[OutElem_co, OutErr_co, D2, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Apply ``f`` to the value the channel ends with."""
        return _combinators.map_done(self, f)

    def map_done_effect[D2, E2 = Never, R2 = Never](
        self, f: Callable[[OutDone_co], Effect[D2, E2, R2]]
    ) -> Channel[
        OutElem_co, OutErr_co | E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """End with what ``f(done)`` succeeds with, or fail with its error."""
        return _combinators.map_done_effect(self, f)

    def concat_with[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        f: Callable[
            [OutDone_co], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
    ) -> Channel[
        OutElem_co | O2, OutErr_co | E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """When this channel ends, go on with ``f(done)`` on the same
        upstream. This channel's resources are released first."""
        return _combinators.concat_with(self, f)

    def concat[O2, E2 = Never, D2 = None, R2 = Never](
        self, that: Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
    ) -> Channel[
        OutElem_co | O2, OutErr_co | E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2
    ]:
        """Write this channel's items, then ``that``'s, ending as ``that``."""
        require_channel(that, "that")
        return _combinators.concat_with(self, lambda _: that)

    def pipe_to[O2, E2 = Never, D2 = None, R2 = Never](
        self, that: Channel[O2, E2, D2, OutElem_co, OutErr_co, OutDone_co, R2]
    ) -> Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, Env_co | R2]:
        """Feed this channel's output to ``that`` as its upstream."""
        require_channel(that, "that")
        return _combinators.pipe_to(self, that)

    # --- running ------------------------------------------------------------

    def run_collect[O, E, D, R](
        self: Channel[O, E, D, Never, Never, None, R],
    ) -> Effect[list[O], E, R]:
        """Run the channel and collect every item written."""
        return _run.run_collect(self)

    def run_drain[O, E, D, R](self: Channel[O, E, D, Never, Never, None, R]) -> Effect[D, E, R]:
        """Run the channel, dropping its items; succeed with its end value."""
        return _run.run_drain(self)

    def run_for_each[O, E, D, R, E2 = Never, R2 = Never](
        self: Channel[O, E, D, Never, Never, None, R], f: Callable[[O], Effect[object, E2, R2]]
    ) -> Effect[D, E | E2, R | R2]:
        """Run ``f`` on each item; succeed with the channel's end value."""
        return _run.run_for_each(self, f)

    def run_for_each_while[O, E, D, R, E2 = Never, R2 = Never](
        self: Channel[O, E, D, Never, Never, None, R], f: Callable[[O], Effect[bool, E2, R2]]
    ) -> Effect[None, E | E2, R | R2]:
        """Run ``f`` on each item until it succeeds with ``False``."""
        return _run.run_for_each_while(self, f)

    def run_fold[O, E, D, R, Z](
        self: Channel[O, E, D, Never, Never, None, R],
        initial: Callable[[], Z],
        f: Callable[[Z, O], Z],
    ) -> Effect[Z, E, R]:
        """Fold the items into ``initial()`` with ``f``."""
        return _run.run_fold(self, initial, f)

    def run_fold_effect[O, E, D, R, Z, E2 = Never, R2 = Never](
        self: Channel[O, E, D, Never, Never, None, R],
        initial: Callable[[], Z],
        f: Callable[[Z, O], Effect[Z, E2, R2]],
    ) -> Effect[Z, E | E2, R | R2]:
        """Fold the items into ``initial()`` with the effect ``f``."""
        return _run.run_fold_effect(self, initial, f)

    def run_count[O, E, D, R](self: Channel[O, E, D, Never, Never, None, R]) -> Effect[int, E, R]:
        """Run the channel and count its items."""
        return _run.run_fold(self, _zero, _increment)

    def run_head[O, E, D, R](
        self: Channel[O, E, D, Never, Never, None, R],
    ) -> Effect[Option[O], E, R]:
        """The first item (``Some``), or ``None`` when there is none. Stops
        the channel after the first item."""
        return _run.run_head(self)

    def run_last[O, E, D, R](
        self: Channel[O, E, D, Never, Never, None, R],
    ) -> Effect[Option[O], E, R]:
        """The last item (``Some``), or ``None`` when there is none."""
        return _run.run_last(self)

    def to_pull[O, E, D, R](
        self: Channel[O, E, D, Never, Never, None, R],
    ) -> Effect[Pull[O, E, D], Never, R | Scope]:
        """Build the channel's pull in the current ``Scope``, which holds
        its resources. The pull has the caller's services and takes turns:
        fibers pulling at once get one item each."""
        return _run.to_pull(self)

    def to_pull_scoped[O, E, D, R](
        self: Channel[O, E, D, Never, Never, None, R], scope: CloseableScope
    ) -> Effect[Pull[O, E, D, R], Never, R]:
        """Build the channel's pull with its resources in ``scope``."""
        return _run.to_pull_scoped(self, scope)


def _zero() -> int:
    return 0


def _increment(n: int, _: object) -> int:
    return n + 1


def require_channel(value: object, name: str) -> None:
    """Raise ``TypeError`` naming ``name`` unless ``value`` is a ``Channel``."""
    if not isinstance(value, Channel):
        raise TypeError(wrong_argument(value, name, "a Channel", "build one with pyfect.channel"))


def _pull_failing(cause: Any) -> Success[AnyPull]:
    return Success(_FailCause(cause))


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
def from_transform(transform: Callable[[Any, CloseableScope], Effect[Any, Any, Any]]) -> Any:
    """A channel from ``transform(upstream, scope)``, an effect building
    the channel's pull from the upstream pull. Resources go in ``scope``,
    closed when the run ends. If building the pull fails, the pull fails
    with that cause."""

    channel: Channel[Any, Any, Any, Any, Any, Any, Any] = Channel(transform)
    return channel


def to_transform[O, E, D, I, IE, ID, R](
    channel: Channel[O, E, D, I, IE, ID, R],
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
    channel: Channel[O, E, D, I, IE, ID, R],
    f: Callable[[Pull[O, E, D], CloseableScope], Effect[Pull[O2, EE, D2, RR], EE, RR]],
) -> Channel[O2, EE, D2, I, IE, ID, R | RR]:
    """A channel whose pull is ``f(pull, scope)`` of ``channel``'s pull."""
    require_channel(channel, "channel")
    inner = channel._transform
    transformed: Channel[O2, EE, D2, I, IE, ID, R | RR] = Channel(
        lambda upstream, scope: inner(upstream, scope).flat_map(lambda pull: f(pull, scope))
    )
    return transformed


# Loaded last: they build ``Channel``s.
from pyfect.channel import _combinators, _run  # noqa: E402
