"""The server's own timers (keep-alive, headers, close grace, shutdown)
run on the system clock, as Node's socket timers do: a ``TestClock`` the
program provides never moves them, so it must not stop them either."""

from pyfect._core import Effect
from pyfect.clock import Clock, LiveClock
from pyfect.duration import Duration
from pyfect.effect import provide_service
from pyfect.option import Option

_LIVE = LiveClock()


def timeout_option[A, E, R](eff: Effect[A, E, R], seconds: Duration) -> Effect[Option[A], E, R]:
    """``eff`` with ``timeout_option``, timed by the system clock; ``eff``
    is the server's own I/O, which reads no clock."""
    return eff.timeout_option(seconds).pipe(provide_service(Clock, _LIVE))


__all__ = ["timeout_option"]
