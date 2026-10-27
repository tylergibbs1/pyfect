"""``Stream`` methods that handle failures: recovering with another
stream, tapping, mapping and dropping errors, and retrying.

Recovery from typed errors goes through the cause's recoverable error, so
a defect always wins over a typed error. To remove the caught errors from
the stream's type, use ``pyfect.stream.catch_tag`` / ``catch_if`` with
``.pipe``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect.result import Err, Ok, Result
from pyfect.stream._base import A_co, E_co, R_co, StreamBase

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.cause import Cause
    from pyfect.logger import Severity
    from pyfect.schedule import Schedule
    from pyfect.schedule._model import SetInputType
    from pyfect.stream._stream import Stream


class ErrorMethods(StreamBase[A_co, E_co, R_co]):
    __slots__ = ()

    # --- recovering -----------------------------------------------------------

    def catch_cause[B, E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Stream[B, E2, R2]]
    ) -> Stream[A_co | B, E2, R_co | R2]:
        """On any failure, defects included, release this stream's resources
        and go on with ``f(cause)``."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.catch_cause(lambda cause: f(cause)._channel))

    def catch_cause_if[B, E2 = Never, R2 = Never](
        self,
        predicate: Callable[[Cause[E_co]], bool],
        f: Callable[[Cause[E_co]], Stream[B, E2, R2]],
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]:
        """``catch_cause`` for the causes that pass ``predicate``."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.catch_cause_if(predicate, lambda cause: f(cause)._channel))

    def catch_all[B, E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Stream[B, E2, R2]]
    ) -> Stream[A_co | B, E2, R_co | R2]:
        """Go on with ``f(error)`` after a typed failure (Effect's
        ``Stream.catch``). Defects and interruptions pass through."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.catch_all(lambda error: f(error)._channel))

    @overload
    def catch_if[B, E2 = Never, R2 = Never](
        self, predicate: Callable[[E_co], bool], f: Callable[[E_co], Stream[B, E2, R2]]
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]: ...
    @overload
    def catch_if[B, C, EE = Never, RR = Never](
        self,
        predicate: Callable[[E_co], bool],
        f: Callable[[E_co], Stream[B, EE, RR]],
        *,
        or_else: Callable[[E_co], Stream[C, EE, RR]],
    ) -> Stream[A_co | B | C, EE, R_co | RR]: ...
    def catch_if(
        self,
        predicate: Callable[[Any], bool],
        f: Callable[[Any], Stream[Any, Any, Any]],
        *,
        or_else: Callable[[Any], Stream[Any, Any, Any]] | None = None,
    ) -> Stream[Any, Any, Any]:
        """Go on with ``f(error)`` after a typed failure that passes
        ``predicate``; ``or_else``, if given, handles the rest. To remove the
        caught errors from the type, use ``pipe(stream.catch_if(...))`` with
        a ``TypeIs`` refinement."""
        from pyfect.stream import _catch

        return _catch.catch_if(self, predicate, f, or_else)

    @overload
    def catch_filter[EB, X, B, E2 = Never, R2 = Never](
        self, filter: Callable[[E_co], Result[EB, X]], f: Callable[[EB], Stream[B, E2, R2]]
    ) -> Stream[A_co | B, X | E2, R_co | R2]: ...
    @overload
    def catch_filter[EB, X, B, C, EE = Never, RR = Never](
        self,
        filter: Callable[[E_co], Result[EB, X]],
        f: Callable[[EB], Stream[B, EE, RR]],
        *,
        or_else: Callable[[X], Stream[C, EE, RR]],
    ) -> Stream[A_co | B | C, EE, R_co | RR]: ...
    def catch_filter(
        self,
        filter: Callable[[Any], Result[Any, Any]],
        f: Callable[[Any], Stream[Any, Any, Any]],
        *,
        or_else: Callable[[Any], Stream[Any, Any, Any]] | None = None,
    ) -> Stream[Any, Any, Any]:
        """Go on with ``f(value)`` after a typed failure ``filter`` maps to
        ``Ok(value)``. One it maps to ``Err(x)`` goes to ``or_else(x)``, or
        fails with ``x``."""
        from pyfect.stream._constructors import fail
        from pyfect.stream._stream import Stream

        def handle(error: Any) -> Any:
            match filter(error):
                case Ok(value):
                    return f(value)._channel
                case Err(rest):
                    return (fail(rest) if or_else is None else or_else(rest))._channel

        return Stream(self._channel.catch_all(handle))

    def catch_cause_filter[EB, X, B, E2 = Never, R2 = Never](
        self,
        filter: Callable[[Cause[E_co]], Result[EB, Cause[X]]],
        f: Callable[[EB, Cause[E_co]], Stream[B, E2, R2]],
    ) -> Stream[A_co | B, X | E2, R_co | R2]:
        """Go on with ``f(value, cause)`` after a failure ``filter`` maps to
        ``Ok(value)``; one it maps to ``Err(rest)`` fails with ``rest``."""
        from pyfect.stream._constructors import fail_cause
        from pyfect.stream._stream import Stream

        def handle(cause: Cause[E_co]) -> Any:
            match filter(cause):
                case Ok(value):
                    return f(value, cause)._channel
                case Err(rest):
                    return fail_cause(rest)._channel

        return Stream(self._channel.catch_cause(handle))

    def catch_defect[B, E2 = Never, R2 = Never](
        self, f: Callable[[BaseException], Stream[B, E2, R2]]
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]:
        """Go on with ``f(defect)`` after a failure with a defect. Typed
        errors pass through."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.catch_defect(lambda defect: f(defect)._channel))

    def or_else_if_empty[B, E2 = Never, R2 = Never](
        self, or_else: Callable[[], Stream[B, E2, R2]]
    ) -> Stream[A_co | B, E_co | E2, R_co | R2]:
        """Go on with ``or_else()`` if this stream ends without writing."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.or_else_if_empty(lambda _: or_else()._channel))

    def or_else_succeed[B](self, f: Callable[[E_co], B]) -> Stream[A_co | B, Never, R_co]:
        """Write ``f(error)`` and end instead of failing with a typed error."""
        from pyfect.stream._constructors import succeed

        return self.catch_all(lambda error: succeed(f(error)))

    # --- tapping --------------------------------------------------------------

    def tap_cause[E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``f(cause)`` when the stream fails, then fail the same way."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.tap_cause(f))

    def tap_error[E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[object, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``f(error)`` when the stream fails with a typed error."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.tap_error(f))

    @overload
    def tap_error_tag[T1, E2 = Never, R2 = Never](
        self, tag: type[T1], f: Callable[[T1], Effect[object, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]: ...
    @overload
    def tap_error_tag[T1, T2, E2 = Never, R2 = Never](
        self, tag: tuple[type[T1], type[T2]], f: Callable[[T1 | T2], Effect[object, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]: ...
    @overload
    def tap_error_tag[T1, T2, T3, E2 = Never, R2 = Never](
        self,
        tag: tuple[type[T1], type[T2], type[T3]],
        f: Callable[[T1 | T2 | T3], Effect[object, E2, R2]],
    ) -> Stream[A_co, E_co | E2, R_co | R2]: ...
    def tap_error_tag(
        self,
        tag: type[Any] | tuple[type[Any], ...],
        f: Callable[[Any], Effect[object, Any, Any]],
    ) -> Stream[Any, Any, Any]:
        """``tap_error`` for the errors that are instances of ``tag`` (a
        class or a tuple of classes)."""
        from pyfect.effect import void

        return self.tap_error(lambda e: f(e) if isinstance(e, tag) else void)

    def tap_defect[E2 = Never, R2 = Never](
        self, f: Callable[[BaseException], Effect[object, E2, R2]]
    ) -> Stream[A_co, E_co | E2, R_co | R2]:
        """Run ``f(defect)`` when the stream fails with a defect."""
        from pyfect.effect import void

        def tap(cause: Cause[E_co]) -> Effect[object, E2, R2]:
            defect = cause.find_defect()
            return void if defect is None else f(defect)

        return self.tap_cause(tap)

    # --- mapping and dropping errors ------------------------------------------

    def map_error[E2](self, f: Callable[[E_co], E2]) -> Stream[A_co, E2, R_co]:
        """Apply ``f`` to the typed error. Defects and interruptions stay."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.map_error(f))

    def or_die(self) -> Stream[A_co, Never, R_co]:
        """Die with the typed error instead of failing with it."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.or_die())

    def ignore(self, *, log: bool | Severity = False) -> Stream[A_co, Never, R_co]:
        """End instead of failing with a typed error. With ``log``, log the
        cause first, at the current log level (``True``) or the level
        given."""
        from pyfect.stream._stream import Stream

        ignored: Any = self._channel.ignore(log=log)
        return Stream(ignored)

    def ignore_cause(self, *, log: bool | Severity = False) -> Stream[A_co, Never, R_co]:
        """End instead of failing in any way. ``log`` as for ``ignore``."""
        from pyfect.stream._stream import Stream

        ignored: Any = self._channel.ignore_cause(log=log)
        return Stream(ignored)

    # --- retrying -------------------------------------------------------------

    @overload
    def retry[EE = Never, RR = Never](
        self, policy: Schedule[object, E_co, EE, RR], /
    ) -> Stream[A_co, E_co | EE, R_co | RR]: ...
    @overload
    def retry[A, E, R, EE = Never, RR = Never](
        self: ErrorMethods[A, E, R],
        builder: Callable[[SetInputType[E]], Schedule[object, E, EE, RR]],
        /,
    ) -> Stream[A, E | EE, R | RR]: ...
    def retry(
        self, policy: Schedule[Any, Any, Any, Any] | Callable[[Any], Any], /
    ) -> Stream[Any, Any, Any]:
        """Run the stream again from the start after each typed failure,
        while ``policy`` recurs; then fail with the last error. Items
        already written stay written. A run that writes an item resets the
        policy; each run sees its step's ``schedule.CurrentMetadata``."""
        from pyfect.stream._stream import Stream

        return Stream(self._channel.retry(policy))
