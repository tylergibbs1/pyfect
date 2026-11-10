"""Resources that keep their entity alive (Effect's ``EntityResource``):
acquired once per entity, held across restarts of its handlers, and
released when closed or idle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Never, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.cluster.entity import CurrentAddress, keep_alive
from pyfect.cluster.k8s_http_client import K8sHttpClient, PodStatus, make_create_pod
from pyfect.cluster.k8s_types import Pod as K8sPod
from pyfect.cluster.sharding import Sharding
from pyfect.context import Tag
from pyfect.duration import Duration
from pyfect.effect import gen, provide_service, succeed
from pyfect.exit import Exit
from pyfect.rc_ref import RcRef
from pyfect.scope import CloseableScope, Scope, add_finalizer, scoped

_VOID: Effect[None] = succeed(None)


@dataclass(frozen=True, slots=True)
class EntityResource[A, E = Never]:
    """``get`` holds the resource for the current scope; ``close``
    releases it, so the next ``get`` acquires it again."""

    get: Effect[A, E, Scope]
    close: Effect[None]


class CloseScope(Tag[CloseableScope], key="effect/cluster/EntityResource/CloseScope"):
    """The scope closed when the resource is released by ``close`` or by
    going idle, not when the entity's handlers restart or the runner shuts
    down."""


@overload
def make[A, E](
    acquire: Effect[A, E, CloseScope],
    *,
    idle_time_to_live: Duration | None = None,
    acquire_eagerly: bool = False,
) -> Effect[EntityResource[A, E], E, Scope | Sharding | CurrentAddress]: ...
@overload
def make[A, E, R](
    acquire: Effect[A, E, R | CloseScope],
    *,
    idle_time_to_live: Duration | None = None,
    acquire_eagerly: bool = False,
) -> Effect[EntityResource[A, E], E, Scope | R | Sharding | CurrentAddress]: ...
def make(
    acquire: Effect[Any, Any, Any],
    *,
    idle_time_to_live: Duration | None = None,
    acquire_eagerly: bool = False,
) -> Effect[EntityResource[Any, Any], Any, Any]:
    """A resource acquired by ``acquire`` (with its ``CloseScope``) that
    keeps the entity alive while held; it is released after
    ``idle_time_to_live`` unused (never by default)."""
    require_effect(acquire, "acquire")

    @gen
    def build():
        # Per run, as each activation of the entity has its own lifetime.
        shutting_down = [False]

        @gen
        def acquire_alive():
            yield from keep_alive(True)
            closeable = CloseableScope()

            def release(exit: Exit[Any, Any]) -> Effect[None, Never, Any]:
                if shutting_down[0]:
                    return _VOID
                return closeable.close(exit).and_then(keep_alive(False))

            yield from add_finalizer(release)
            return (yield from acquire.pipe(provide_service(CloseScope, closeable)))

        ref = yield from RcRef.make(
            acquire_alive,
            idle_time_to_live="Infinity" if idle_time_to_live is None else idle_time_to_live,
        )

        def shut_down(_: Exit[Any, Any]) -> Effect[None]:
            shutting_down[0] = True
            return _VOID

        yield from add_finalizer(shut_down)
        if acquire_eagerly:
            yield from scoped(ref.get())
        return EntityResource(ref.get(), ref.invalidate())

    return build


def make_k8s_pod(
    spec: K8sPod, *, idle_time_to_live: Duration | None = None
) -> Effect[EntityResource[PodStatus], Never, Scope | Sharding | CurrentAddress | K8sHttpClient]:
    """A Kubernetes pod created from the manifest ``spec`` (a whole ``Pod``,
    with its ``metadata`` and ``spec``) for the entity, and deleted when the
    resource is released."""

    @gen
    def build():
        create_pod = yield from make_create_pod

        @gen
        def acquire():
            scope = yield from CloseScope()
            return (yield from create_pod(spec).pipe(provide_service(Scope, scope)))

        return (yield from make(acquire, idle_time_to_live=idle_time_to_live))

    return build


__all__ = ["CloseScope", "EntityResource", "make", "make_k8s_pod"]
