"""Request batching: ``Request``, ``RequestResolver`` and ``request``.

A request describes one piece of data to fetch; a resolver fetches many
at once. Requests made through the same resolver in the same scheduler
tick are collected into one batch, so N concurrent lookups become one
call (the N+1 query problem)::

    @dataclass(frozen=True)
    class GetUser(fx.Request[User, NotFound]):
        id: int

    def fetch_users(entries: Sequence[Entry[GetUser]]) -> fx.Effect[None]:
        def complete() -> None:
            rows = db.users_by_id([e.request.id for e in entries])
            for e in entries:
                e.complete_unsafe(fx.Success(rows[e.request.id]))

        return fx.sync(complete)

    users = fx.RequestResolver(fetch_users)
    names = yield from fx.for_each(
        ids, lambda i: fx.request(GetUser(i), users), concurrency="unbounded"
    )

- ``Entry``: one request in a batch, with the services of the fiber that
  made it; complete it with ``complete_unsafe`` (or the effects
  ``complete``, ``complete_effect``, ``succeed``, ``fail``, ``fail_cause``).
- ``RequestResolver(run_all, ...)``: Effect's ``make`` / ``makeWith``;
  ``make_grouped``, ``from_function``, ``from_function_batched``,
  ``from_effect``, ``from_effect_tagged`` and ``never`` build others.
  Methods derive new resolvers: ``batch_n``, ``grouped``, ``set_delay``,
  ``set_delay_effect``, ``around``, ``race`` and ``with_cache``.
- ``request(req, resolver)``: make a request from an effect;
  ``request_unsafe`` makes one from plain code with a callback.

Interrupting a caller takes its request out of its batch; a batch nobody
waits for does not run.
"""

from pyfect.batching._api import request, request_unsafe
from pyfect.batching._engine import UncompletedRequestError
from pyfect.batching._request import Entry, Request, TypedRequest
from pyfect.batching._resolver import CacheStrategy, RequestResolver, RunAll

__all__ = [
    "CacheStrategy",
    "Entry",
    "Request",
    "RequestResolver",
    "RunAll",
    "TypedRequest",
    "UncompletedRequestError",
    "request",
    "request_unsafe",
]
