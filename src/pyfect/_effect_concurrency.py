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
    from pyfect._fiber import Fiber
    from pyfect.errors import TimeoutException
    from pyfect.option import Option
    from pyfect.scope import Scope


class ConcurrencyMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def fork(self) -> Effect[Fiber[A_co, E_co], Never, R_co]:
        """Start this effect on a child fiber. The child is interrupted if
        it is still running when the parent fiber finishes."""
        return _core._Fork(as_effect(self), daemon=False)

    def fork_daemon(self) -> Effect[Fiber[A_co, E_co], Never, R_co]:
        """Start this effect on a fiber that outlives its parent."""
        return _core._Fork(as_effect(self), daemon=True)

    def fork_scoped(self) -> Effect[Fiber[A_co, E_co], Never, R_co | Scope]:
        """Start this effect on a fiber that is interrupted when the
        enclosing ``Scope`` closes."""
        from pyfect.scope import fork_scoped

        return fork_scoped(as_effect(self))

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
