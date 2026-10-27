"""``Channel`` methods that handle failures: recovering with another
channel, tapping, mapping and dropping errors, and retrying.

Recovery from typed errors (``catch_all``, ``catch_if``, the
``pyfect.channel.catch_tag`` / ``catch_if`` functions) goes through the
cause's recoverable error, so a defect always wins over a typed error,
as for ``Effect``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect.channel._base import (
    ChannelBase,
    Env_co,
    InDone_contra,
    InElem_contra,
    InErr_contra,
    OutDone_co,
    OutElem_co,
    OutErr_co,
)

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.cause import Cause
    from pyfect.channel._channel import Channel
    from pyfect.logger import Severity
    from pyfect.schedule import Schedule
    from pyfect.schedule._model import SetInputType


class ErrorMethods(
    ChannelBase[
        OutElem_co, OutErr_co, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]
):
    __slots__ = ()

    def catch_cause[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        f: Callable[
            [Cause[OutErr_co]], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
    ) -> Channel[
        OutElem_co | O2,
        E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """On any failure, defects included, release this channel's
        resources and go on with ``f(cause)`` on the same upstream."""
        from pyfect.channel import _errors

        return _errors.catch_cause(self, f)

    def catch_cause_if[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        predicate: Callable[[Cause[OutErr_co]], bool],
        f: Callable[
            [Cause[OutErr_co]], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
    ) -> Channel[
        OutElem_co | O2,
        OutErr_co | E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """``catch_cause`` for the causes that pass ``predicate``."""
        from pyfect.channel import _errors

        return _errors.catch_cause_if(self, predicate, f)

    def catch_all[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        f: Callable[
            [OutErr_co], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
    ) -> Channel[
        OutElem_co | O2,
        E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Go on with ``f(error)`` after a typed failure (Effect's
        ``Channel.catch``). Defects and interruptions pass through."""
        from pyfect.channel import _errors

        return _errors.catch_all(self, f)

    @overload
    def catch_if[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        predicate: Callable[[OutErr_co], bool],
        f: Callable[
            [OutErr_co], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
    ) -> Channel[
        OutElem_co | O2,
        OutErr_co | E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]: ...
    @overload
    def catch_if[O2, O3, D2 = None, D3 = None, EE = Never, RR = Never](
        self,
        predicate: Callable[[OutErr_co], bool],
        f: Callable[
            [OutErr_co], Channel[O2, EE, D2, InElem_contra, InErr_contra, InDone_contra, RR]
        ],
        *,
        or_else: Callable[
            [OutErr_co], Channel[O3, EE, D3, InElem_contra, InErr_contra, InDone_contra, RR]
        ],
    ) -> Channel[
        OutElem_co | O2 | O3,
        EE,
        OutDone_co | D2 | D3,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | RR,
    ]: ...
    def catch_if(
        self,
        predicate: Callable[[Any], bool],
        f: Callable[[Any], Channel[Any, Any, Any, Any, Any, Any, Any]],
        *,
        or_else: Callable[[Any], Channel[Any, Any, Any, Any, Any, Any, Any]] | None = None,
    ) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
        """Go on with ``f(error)`` after a typed failure that passes
        ``predicate``; ``or_else``, if given, handles the rest. To remove the
        caught errors from ``OutErr``, use ``pipe(channel.catch_if(...))``
        with a ``TypeIs`` refinement."""
        from pyfect.channel import _errors

        return _errors.catch_if(self, predicate, f, or_else)

    def catch_defect[O2, E2 = Never, D2 = None, R2 = Never](
        self,
        f: Callable[
            [BaseException], Channel[O2, E2, D2, InElem_contra, InErr_contra, InDone_contra, R2]
        ],
    ) -> Channel[
        OutElem_co | O2,
        OutErr_co | E2,
        OutDone_co | D2,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Go on with ``f(defect)`` after a failure with a defect (the
        first). Typed errors pass through."""
        from pyfect.channel import _errors

        return _errors.catch_defect(self, f)

    def tap_cause[E2 = Never, R2 = Never](
        self, f: Callable[[Cause[OutErr_co]], Effect[object, E2, R2]]
    ) -> Channel[
        OutElem_co,
        OutErr_co | E2,
        OutDone_co,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Run ``f(cause)`` when the channel fails, then fail the same way."""
        from pyfect.channel import _errors

        return _errors.tap_cause(self, f)

    def tap_error[E2 = Never, R2 = Never](
        self, f: Callable[[OutErr_co], Effect[object, E2, R2]]
    ) -> Channel[
        OutElem_co,
        OutErr_co | E2,
        OutDone_co,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | R2,
    ]:
        """Run ``f(error)`` when the channel fails with a typed error."""
        from pyfect.channel import _errors

        return _errors.tap_error(self, f)

    def map_error[E2](
        self, f: Callable[[OutErr_co], E2]
    ) -> Channel[OutElem_co, E2, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Apply ``f`` to each typed error. Defects and interruptions stay."""
        from pyfect.channel import _errors

        return _errors.map_error(self, f)

    def or_die(
        self,
    ) -> Channel[OutElem_co, Never, OutDone_co, InElem_contra, InErr_contra, InDone_contra, Env_co]:
        """Die with the typed error instead of failing with it."""
        from pyfect.channel import _errors

        return _errors.or_die(self)

    def ignore(
        self, *, log: bool | Severity = False
    ) -> Channel[
        OutElem_co, Never, OutDone_co | None, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]:
        """End (with ``None``) instead of failing with a typed error. With
        ``log``, log the cause first, at the current log level (``True``)
        or the level given."""
        from pyfect.channel import _errors

        return _errors.ignore(self, log)

    def ignore_cause(
        self, *, log: bool | Severity = False
    ) -> Channel[
        OutElem_co, Never, OutDone_co | None, InElem_contra, InErr_contra, InDone_contra, Env_co
    ]:
        """End (with ``None``) instead of failing in any way. ``log`` as for
        ``ignore``."""
        from pyfect.channel import _errors

        return _errors.ignore_cause(self, log)

    @overload
    def retry[EE = Never, RR = Never](
        self, policy: Schedule[object, OutErr_co, EE, RR], /
    ) -> Channel[
        OutElem_co,
        OutErr_co | EE,
        OutDone_co,
        InElem_contra,
        InErr_contra,
        InDone_contra,
        Env_co | RR,
    ]: ...
    @overload
    def retry[O, E, D, I, IE, ID, R, EE = Never, RR = Never](
        self: ErrorMethods[O, E, D, I, IE, ID, R],
        builder: Callable[[SetInputType[E]], Schedule[object, E, EE, RR]],
        /,
    ) -> Channel[O, E | EE, D, I, IE, ID, R | RR]: ...
    def retry(
        self, policy: Schedule[Any, Any, Any, Any] | Callable[[Any], Any], /
    ) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
        """Run the channel again from the start after each typed failure,
        while ``policy`` recurs; then fail with the last error. Items
        already written stay written. A run that writes an item resets
        the policy."""
        from pyfect.channel import _repeat

        return _repeat.retry(self, policy)
