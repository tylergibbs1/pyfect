"""The pool of MySQL sessions (mysql2's ``Pool``, on ``pyfect.pool``):
sessions open as needed up to ``max_connections`` and close after
``idle_timeout`` unused; a checkout waits for a free one and replaces one
that broke (cut short or disconnected)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Never

from pyfect._core import Effect, _Suspend
from pyfect._primitives import uninterruptible_mask
from pyfect.duration import Duration
from pyfect.effect import succeed
from pyfect.pool import Pool
from pyfect.scope import Scope, add_finalizer
from pyfect.sql._loop import call
from pyfect.sql.error import SqlError
from pyfect.sql.mysql._session import Session
from pyfect.sql.mysql.error import catch

_ACQUIRE = catch("Failed to acquire connection", "acquireConnection")


def _close(session: Session) -> Effect[None]:
    return call(session.close, _ACQUIRE, waits_for="work").ignore()


def _open(options: dict[str, Any]) -> Effect[Session, SqlError, Scope]:
    """A session, closed with the scope."""
    opened = call(lambda: Session.open(options), _ACQUIRE, release=Session.close, waits_for="work")
    return uninterruptible_mask(
        lambda restore: restore(opened).tap(lambda s: add_finalizer(lambda _: _close(s)))
    )


def make(
    options: dict[str, Any], *, max_connections: int, idle_timeout: Duration
) -> Effect[Effect[Session, SqlError, Scope], Never, Scope]:
    """A pool closed with the scope, as its checkout: a session until the
    checkout's scope closes."""

    def build(pool: Pool[Session, SqlError]) -> Effect[Session, SqlError, Scope]:
        def check_out() -> Effect[Session, SqlError, Scope]:
            def checked(session: Session) -> Effect[Session, SqlError, Scope]:
                if session.usable:
                    return succeed(session)
                return pool.invalidate(session).and_then(_Suspend(check_out))

            return pool.get().flat_map(checked)

        return _Suspend(check_out)

    pool: Effect[Pool[Session, SqlError], Never, Any] = Pool.make_with_ttl(
        _open(options),
        min=0,
        max=max_connections,
        time_to_live=idle_timeout,
        time_to_live_strategy="usage",
    )
    return pool.map(build)


__all__ = ["make"]
