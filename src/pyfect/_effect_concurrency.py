"""``Effect`` methods that fork, race and time out. The work lives in
``pyfect._concurrency`` and ``pyfect.scope``; these are the method spellings."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Never

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect
from pyfect.duration import Duration

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect._fiber import Fiber, Uninterruptible
    from pyfect.errors import TimeoutException
    from pyfect.option import Option
    from pyfect.scope import CloseableScope, Scope


class ConcurrencyMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def fork(
        self, *, start_immediately: bool = False, uninterruptible: Uninterruptible = False
    ) -> Effect[Fiber[A_co, E_co], Never, R_co]:
        """Start this effect on a child fiber. The child is interrupted if
        it is still running when the parent fiber finishes.

        With ``start_immediately`` the child runs at once, up to its first
        wait, before the parent goes on; otherwise it starts on the next
        scheduler turn. ``uninterruptible`` starts it uninterruptible
        (``True``) or as interruptible as the parent is (``"inherit"``)."""
        return _core._Fork(
            as_effect(self),
            daemon=False,
            start_immediately=start_immediately,
            uninterruptible=uninterruptible,
        )

    def fork_daemon(
        self, *, start_immediately: bool = False, uninterruptible: Uninterruptible = False
    ) -> Effect[Fiber[A_co, E_co], Never, R_co]:
        """Start this effect on a fiber that outlives its parent. Options as
        for ``fork``."""
        return _core._Fork(
            as_effect(self),
            daemon=True,
            start_immediately=start_immediately,
            uninterruptible=uninterruptible,
        )

    def fork_scoped(
        self, *, start_immediately: bool = False, uninterruptible: Uninterruptible = False
    ) -> Effect[Fiber[A_co, E_co], Never, R_co | Scope]:
        """``fork_in`` the enclosing ``Scope``."""
        from pyfect.scope import fork_scoped

        return fork_scoped(
            as_effect(self), start_immediately=start_immediately, uninterruptible=uninterruptible
        )

    def fork_in(
        self,
        scope: CloseableScope,
        *,
        start_immediately: bool = False,
        uninterruptible: Uninterruptible = False,
    ) -> Effect[Fiber[A_co, E_co], Never, R_co]:
        """Start this effect on a fiber that outlives its parent and is
        interrupted when ``scope`` closes. Into a closed scope it gives an
        interrupted fiber that never ran. Options as for ``fork``."""
        from pyfect.scope import fork_in

        return fork_in(
            as_effect(self),
            scope,
            start_immediately=start_immediately,
            uninterruptible=uninterruptible,
        )

    def await_all_children(self) -> Effect[A_co, E_co, R_co]:
        """When this effect ends, wait for the child fibers it forked
        (not those forked before it started). The wait is interruptible
        if the fiber was interruptible when this effect started."""
        from pyfect._fiber_all import await_all_children

        return await_all_children(as_effect(self))

    def race[B, E2 = Never, R2 = Never](
        self, that: Effect[B, E2, R2]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """The first to succeed wins and the other is interrupted. Fails
        only if both fail."""
        from pyfect._concurrency import race

        return race(as_effect(self), that)

    def race_first[B, E2 = Never, R2 = Never](
        self, that: Effect[B, E2, R2]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """The first to finish wins, success or failure."""
        from pyfect._concurrency import race_first

        return race_first(as_effect(self), that)

    def timeout(self, duration: Duration) -> Effect[A_co, E_co | TimeoutException, R_co]:
        """Fail with ``TimeoutException`` if this takes longer than
        ``duration``. The effect is interrupted when time runs out."""
        from pyfect._concurrency import timeout

        return timeout(as_effect(self), duration)

    def timeout_option(self, duration: Duration) -> Effect[Option[A_co], E_co, R_co]:
        """``Some(value)``, or ``None`` if this takes longer than
        ``duration``. The effect is interrupted when time runs out."""
        from pyfect._concurrency import timeout_option

        return timeout_option(as_effect(self), duration)

    def timeout_or_else[B, E2 = Never, R2 = Never](
        self, duration: Duration, or_else: Callable[[], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """Continue with ``or_else()`` if this takes longer than
        ``duration``. ``or_else`` runs once this effect has been
        interrupted and has finished cleaning up."""
        from pyfect._concurrency import timeout_or_else

        return timeout_or_else(as_effect(self), duration, or_else)
