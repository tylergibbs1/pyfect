"""``request`` and ``request_unsafe``: making requests."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, overload

from pyfect._core import Effect
from pyfect._effect_args import wrong_argument
from pyfect._root import ambient_run
from pyfect.batching._engine import Origin, add_entry, remove_entry, request_with
from pyfect.batching._request import TypedRequest
from pyfect.batching._resolver import RequestResolver
from pyfect.context import Context
from pyfect.exit import Exit
from pyfect.scheduler import Scheduler


@overload
def request[A, EE, RR, Q](
    req: TypedRequest[A, EE, RR, Q], resolver: RequestResolver[Q, EE], /
) -> Effect[A, EE, RR]: ...
@overload
def request[A, EE, RR, Q](
    req: TypedRequest[A, EE, RR, Q], resolver: Effect[RequestResolver[Q, EE], EE, RR], /
) -> Effect[A, EE, RR]: ...
def request(
    req: TypedRequest[Any, Any, Any, Any],
    resolver: RequestResolver[Any, Any] | Effect[RequestResolver[Any, Any], Any, Any],
    /,
) -> Effect[Any, Any, Any]:
    """Make ``req`` through ``resolver`` (or the resolver an effect builds)
    and wait for its outcome. Requests made in the same scheduler tick are
    batched::

        name = yield from fx.request(GetName(user_id), names)

    Interrupting the caller takes its request out of the batch; a batch
    nobody waits for any more does not run."""
    if isinstance(resolver, RequestResolver):
        return request_with(req, resolver)
    _require_resolver_effect(resolver)
    return resolver.flat_map(lambda r: request_with(req, r))


def _require_resolver_effect(value: object) -> None:
    if not isinstance(value, Effect):
        raise TypeError(
            wrong_argument(
                value, "resolver", "an Effect or a RequestResolver", "pass the resolver itself"
            )
        )


def request_unsafe[A, E, Q](
    req: TypedRequest[A, E, Any, Q],
    *,
    resolver: RequestResolver[Q, E],
    on_exit: Callable[[Exit[A, E]], None],
    context: Context,
    scheduler: Scheduler | None = None,
) -> Callable[[], None]:
    """Make ``req`` outside an effect: ``on_exit`` gets its outcome. The
    batch runs on the current fiber's run, the running asyncio loop, or
    ``scheduler`` (as ``run_fork``). Returns a function that withdraws the
    request; ``on_exit`` is then never called."""
    run, now = ambient_run(scheduler)
    origin = Origin(context, run, None, now=now)
    entry = add_entry(resolver, req, on_exit, origin)
    return lambda: remove_entry(resolver, entry, origin)
