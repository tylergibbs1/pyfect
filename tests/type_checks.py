"""Type-level regression tests, checked by pyright (not run by pytest).

``assert_type`` pins an inferred type. A line ending in
``# pyright: ignore[...]`` must produce that error: the project enables
``reportUnnecessaryTypeIgnoreComment``, so if the line stops erroring,
pyright fails.
"""

import asyncio
from collections.abc import Callable, Generator, Hashable, Mapping, Sequence, Sized
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from types import CoroutineType
from typing import Any, Literal, Never, NotRequired, Protocol, TypedDict, TypeIs, assert_type

from _pytest.fixtures import FixtureFunctionDefinition
from opentelemetry.trace import Span as OtelApiSpan
from opentelemetry.trace import SpanContext

import pyfect as fx
from pyfect import (
    big_decimal,
    channel,
    crypto,
    execution_plan,
    graphql,
    layer,
    logger,
    otel,
    reactivity,
    rpc,
    schedule,
    semver,
    semver_range,
    stream,
)
from pyfect import schema as S
from pyfect import socket as socket_module
from pyfect._json_value import JsonValue
from pyfect.ai import ai_error as ai_error_module
from pyfect.ai import chat as ai_chat
from pyfect.ai import decision as ai_decision
from pyfect.ai import decision_model as ai_dm
from pyfect.ai import embedding_model as ai_embedding_model
from pyfect.ai import language_model as lm
from pyfect.ai import mcp_client as mcp_client_module
from pyfect.ai import mcp_schema as mcp_schema_module
from pyfect.ai import model as ai_model
from pyfect.ai import response as ai_response
from pyfect.ai import tool as ai_tool
from pyfect.ai import toolkit as ai_toolkit
from pyfect.ai.ai_error import AiError
from pyfect.ai.anthropic import client as anthropic_client
from pyfect.ai.anthropic import language_model as anthropic_lm
from pyfect.ai.anthropic_structured_output import StructuredOutputCodec, to_codec_anthropic
from pyfect.ai.cloudflare import client as cloudflare_client
from pyfect.ai.cloudflare import decision_model as cloudflare_dm
from pyfect.ai.openai import client as openai_client
from pyfect.ai.openai import client_generated as openai_client_generated
from pyfect.ai.openai import decision_model as openai_dm
from pyfect.ai.openai import embedding_model as openai_em
from pyfect.ai.openai import language_model as openai_lm
from pyfect.ai.openai import tool as openai_tool
from pyfect.ai.openai.generated import client as openai_generated
from pyfect.ai.openai.generated import types as openai_generated_types
from pyfect.ai.openai_compat import client as compat_client
from pyfect.ai.openai_compat import embedding_model as compat_em
from pyfect.ai.openai_compat import language_model as compat_lm
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.ai.openrouter import client as openrouter_client
from pyfect.ai.openrouter import decision_model as openrouter_dm
from pyfect.ai.openrouter import language_model as openrouter_lm
from pyfect.ai.openrouter.generated import client as openrouter_generated
from pyfect.ai.response_id_tracker import ResponseIdTracker
from pyfect.ai.typesafe import client as typesafe_client
from pyfect.ai.typesafe import decision_model as typesafe_dm
from pyfect.batching import Entry
from pyfect.cause import Die, Fail, Interrupt
from pyfect.cli import (
    Argument,
    CliError,
    Command,
    CommandContext,
    Config,
    Flag,
    Setting,
    command,
    group,
    nested,
)
from pyfect.cli._environment import Environment as CliEnvironment
from pyfect.cli.global_flag import LogLevel
from pyfect.context import Tag, TagEffect
from pyfect.duration import Seconds, to_seconds
from pyfect.encoding import EncodingError, Json, base64, json_array, ndjson, schema_binary, sse
from pyfect.errors import TaggedError
from pyfect.fiber_handle import FiberHandleRuntime
from pyfect.fiber_map import FiberMapAsyncRuntime, FiberMapRuntime
from pyfect.fiber_set import FiberSetRuntime
from pyfect.hash_map import HashMap
from pyfect.hash_set import HashSet
from pyfect.http import middleware as http_middleware
from pyfect.http import prometheus as http_prometheus
from pyfect.http import router as http_router
from pyfect.http import server as http_server
from pyfect.http import server_response as http_server_response
from pyfect.http.body import File as HttpFile
from pyfect.http.client import HttpClient
from pyfect.http.error import HttpClientError
from pyfect.http.platform import HttpPlatform
from pyfect.http.response import HttpClientResponse as HttpResponse
from pyfect.http.router import GlobalRaises, GlobalRequires, HttpRouter, Raises, Requires
from pyfect.http.server import HttpServer
from pyfect.http.server_error import HttpServerError
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http_api import (
    Handlers,
    HttpApi,
    HttpApiEndpoint,
    HttpApiGroup,
    HttpApiMiddleware,
    HttpApiRequest,
)
from pyfect.http_api import endpoint as api_endpoint
from pyfect.http_api import error as api_error
from pyfect.net import address_resolver, dns, net_address
from pyfect.option import Option
from pyfect.persistence import (
    PersistenceError,
    persistable,
    persisted_cache,
    redis_py,
    user_directories,
)
from pyfect.persistence import circuit_breaker as cb
from pyfect.persistence import key_value_store as kvs
from pyfect.persistence import persisted_queue as pq
from pyfect.persistence import persistence as persistence_module
from pyfect.persistence import rate_limiter as rl
from pyfect.persistence import redis as redis_module
from pyfect.pool._state import Strategy
from pyfect.pubsub import Atomic, Subscription
from pyfect.queue import Dequeue
from pyfect.redacted import make as redact
from pyfect.rpc import client as rpc_client
from pyfect.rpc import server as rpc_server
from pyfect.rpc import test as rpc_test
from pyfect.rpc.serialization import RpcSerialization
from pyfect.scheduler import Scheduler, SyncScheduler
from pyfect.schema import SchemaError
from pyfect.schema import model as Model
from pyfect.schema import variant_schema as VS
from pyfect.scope import Scope
from pyfect.socket import WebSocketConstructor
from pyfect.socket import datagram as dg
from pyfect.sql import clickhouse as sql_clickhouse
from pyfect.sql import client as sql_client
from pyfect.sql import d1 as sql_d1
from pyfect.sql import error as sql_error
from pyfect.sql import libsql as sql_libsql
from pyfect.sql import migrator as sql_migrator
from pyfect.sql import model as sql_model
from pyfect.sql import mssql as sql_mssql
from pyfect.sql import mysql as sql_mysql
from pyfect.sql import pg as sql_pg
from pyfect.sql import resolver as sql_resolver
from pyfect.sql import result as sql_result
from pyfect.sql import schema as sql_schema
from pyfect.sql import sqlite as sql_sqlite
from pyfect.sql.client import SqlClient
from pyfect.sql.connection import Row, ValueRow
from pyfect.sql.error import ResultLengthMismatch, SqlError
from pyfect.sql.statement import Fragment, Statement
from pyfect.sql.statement import Literal as SqlLiteral
from pyfect.stream import Stream
from pyfect.trie import Trie
from pyfect.workers import python_worker, python_worker_runner
from pyfect.workers.python_worker import ThreadWorker
from pyfect.workers.worker import Spawner, Worker, WorkerPlatform
from pyfect.workers.worker_error import WorkerError
from pyfect.workers.worker_runner import WorkerRunner, WorkerRunnerPlatform
from pyfect.workflow import (
    Activity,
    Complete,
    DurableDeferred,
    Suspended,
    Workflow,
    WorkflowEngine,
    WorkflowInstance,
    WorkflowInstanceService,
    activity,
    durable_clock,
    durable_deferred,
    durable_queue,
    workflow,
    workflow_engine,
)


class Db(Protocol):
    def get(self, key: str) -> str | None: ...


class GoodDb:
    def get(self, key: str) -> str | None:
        return None


class Primary(fx.Tag[Db]): ...


class Replica(fx.Tag[Db]): ...


class Port(fx.Tag[int]): ...


class Level(fx.Reference[int]):
    @classmethod
    def default(cls) -> int:
        return 0


@dataclass
class NotFound(fx.TaggedError):
    key: str


@dataclass
class Invalid(fx.TaggedError):
    reason: str


primary_live = layer.succeed(Primary, GoodDb())
port_live = layer.succeed(Port, 8080)
merged_live = layer.merge(primary_live, port_live)


# --- generators infer A, E and R --------------------------------------------------


@fx.fn
def lookup(key: str):
    db = yield from Primary()
    port = yield from Port()
    level = yield from Level()
    value = db.get(key)
    if value is None:
        return (yield from NotFound(key))
    if port < level:
        return (yield from Invalid("port"))
    return value


def check_generators() -> None:
    assert_type(lookup("k"), fx.Effect[str, NotFound | Invalid, Primary | Port])
    assert_type(Primary(), TagEffect[Db, Primary, Primary])


# A generic body annotates its return as fx.Gen[A, E, R]: inferred, pyright drops R (one
# other requirement) or collapses it into the other (two), and fn raises TypeError for an
# unannotated generic body (research/typing/fn_1_generic.py).


@fx.fn
def generic_alone[R](eff: fx.Effect[int, Never, R]) -> fx.Gen[int, Never, R]:
    return (yield from eff)


@fx.fn
def generic_scoped[R](eff: fx.Effect[int, Never, R]) -> fx.Gen[int, Never, R | Scope]:
    fiber = yield from eff.fork_scoped()
    return (yield from fiber.join())


@fx.fn
def generic_three[R, E](
    eff: fx.Effect[int, E, R], port: fx.Effect[int, Never, Port]
) -> fx.Gen[int, E, R | Port | Scope]:
    fiber = yield from eff.fork_scoped()
    yield from port
    return (yield from fiber.join())


@fx.fn("generic_named")
def generic_named[R](eff: fx.Effect[int, Never, R]) -> fx.Gen[int, Never, R | Scope]:
    fiber = yield from eff.fork_scoped()
    return (yield from fiber.join())


def generic_wrong[R](eff: fx.Effect[int, Never, R]) -> fx.Gen[int, Never, R]:
    yield from fx.Scope()  # pyright: ignore[reportReturnType]
    return (yield from eff)


def check_generic_bodies(needs_primary: fx.Effect[int, Never, Primary]) -> None:
    assert_type(generic_alone(needs_primary), fx.Effect[int, Never, Primary])
    assert_type(generic_scoped(needs_primary), fx.Effect[int, Never, Primary | Scope])
    assert_type(generic_named(needs_primary), fx.Effect[int, Never, Primary | Scope])
    with_error = needs_primary.flat_map(lambda n: fx.fail(NotFound("k")) if n else fx.succeed(n))
    assert_type(generic_three(with_error, Port()), fx.Effect[int, NotFound, Primary | Port | Scope])


# --- catch_tag removes exactly one error class ------------------------------------


def check_catch_tag() -> None:
    one = lookup("k").pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(e.key)))
    assert_type(one, fx.Effect[str, Invalid, Primary | Port])
    both = one.pipe(fx.catch_tag(Invalid, lambda e: fx.succeed(len(e.reason))))
    assert_type(both, fx.Effect[str | int, Never, Primary | Port])
    caught_all = lookup("k").catch_all(lambda e: fx.succeed(None))
    assert_type(caught_all, fx.Effect[str | None, Never, Primary | Port])


class HttpProblem(fx.TaggedError): ...


class Missing(HttpProblem): ...


class Denied(HttpProblem): ...


def check_catch_tag_parent(only_http: fx.Effect[str, Missing | Denied]) -> None:
    # A parent class removes its subclasses when they are all of E. Mixed with
    # other errors, pyright keeps one subclass (QA types 7, PARITY "Still open"):
    # name the subclasses to remove each.
    assert_type(
        only_http.pipe(fx.catch_tag(HttpProblem, lambda e: fx.succeed("x"))),
        fx.Effect[str, Never, Never],
    )
    mixed: fx.Effect[str, Missing | Denied | Invalid] = fx.fail(Invalid("x"))
    assert_type(
        mixed.pipe(fx.catch_tag((Missing, Denied), lambda e: fx.succeed("x"))),
        fx.Effect[str, Invalid, Never],
    )


# --- error combinators: the type-removing ones remove exactly what they catch -------


@dataclass
class Gone(fx.TaggedError):
    pass


def is_not_found(e: object) -> TypeIs[NotFound]:
    return isinstance(e, NotFound)


def handle_rest(e: Invalid) -> fx.Effect[int]:
    return fx.succeed(len(e.reason))


def handle_too_little(e: Gone) -> fx.Effect[int]:
    return fx.succeed(0)


def handle_any(e: NotFound | Invalid) -> fx.Effect[int]:
    return fx.succeed(0)


def check_error_removal(three: fx.Effect[str, NotFound | Invalid | Gone]) -> None:
    assert_type(
        three.pipe(fx.catch_tag((NotFound, Invalid), lambda e: fx.succeed(type(e).__name__))),
        fx.Effect[str, Gone, Never],
    )
    assert_type(
        three.pipe(fx.catch_tag((NotFound, Invalid, Gone), lambda e: fx.succeed(None))),
        fx.Effect[str | None, Never, Never],
    )
    assert_type(
        three.pipe(fx.catch_if(is_not_found, lambda e: fx.succeed(e.key))),
        fx.Effect[str, Invalid | Gone, Never],
    )
    two = lookup("k").pipe(fx.provide(merged_live))
    # or_else must cover every error catch_tag / catch_if leave.
    assert_type(
        two.pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(e.key), or_else=handle_rest)),
        fx.Effect[str | int, Never, Never],
    )
    assert_type(
        two.pipe(fx.catch_if(is_not_found, lambda e: fx.succeed(1), or_else=handle_rest)),
        fx.Effect[str | int, Never, Never],
    )
    two.pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(1), or_else=handle_too_little))  # pyright: ignore[reportArgumentType]
    # catch_all for .pipe (DOGFOOD B7): the handler must cover every error.
    assert_type(two.pipe(fx.catch_all(handle_any)), fx.Effect[str | int, Never, Never])
    two.pipe(fx.catch_all(handle_rest))  # pyright: ignore[reportArgumentType]
    maybe = fx.from_optional(1 if two else None).flat_map(lambda n: fx.fail(Invalid(str(n))))
    assert_type(maybe.pipe(fx.catch_no_such_element), fx.Effect[fx.Option[Never], Invalid, Never])
    assert_type(
        fx.from_optional(1 if two else None).pipe(fx.catch_no_such_element),
        fx.Effect[fx.Option[int], Never, Never],
    )


# --- reason errors: catch_reason keeps the parent unless or_else covers the rest -------


@dataclass
class RateLimited(fx.TaggedError):
    retry_after: int


@dataclass
class QuotaExceeded(fx.TaggedError):
    limit: int


@dataclass
class AiFailure(fx.TaggedError):
    reason: RateLimited | QuotaExceeded


def on_quota(reason: QuotaExceeded, error: AiFailure) -> fx.Effect[str]:
    return fx.succeed(str(reason.limit))


def on_rate_only(reason: RateLimited, error: AiFailure) -> fx.Effect[str]:
    return fx.succeed("")


def on_quota_stream(reason: QuotaExceeded, error: AiFailure) -> Stream[str]:
    return stream.succeed("")


def on_quota_channel(reason: QuotaExceeded, error: AiFailure) -> channel.Channel[str]:
    return channel.succeed("")


def check_reasons(
    ai: fx.Effect[int, AiFailure | NotFound, Port], only: fx.Effect[int, AiFailure]
) -> None:
    def retry_in(r: RateLimited, e: AiFailure) -> fx.Effect[int]:
        return fx.succeed(r.retry_after)

    assert_type(
        ai.pipe(fx.catch_reason(AiFailure, RateLimited, retry_in)),
        fx.Effect[int, AiFailure | NotFound, Port],
    )
    assert_type(
        ai.pipe(
            fx.catch_reason(AiFailure, RateLimited, lambda r, _: fx.fail(Gone()), or_else=on_quota)
        ),
        fx.Effect[int | str, NotFound | Gone, Port],
    )
    assert_type(
        only.pipe(fx.catch_reason(AiFailure, RateLimited, retry_in, or_else=on_quota)),
        fx.Effect[int | str, Never, Never],
    )
    assert_type(
        ai.pipe(
            fx.catch_reasons(
                AiFailure,
                (RateLimited, lambda r, _: fx.succeed(r.retry_after)),
                (QuotaExceeded, lambda r, _: fx.succeed(str(r.limit))),
            )
        ),
        fx.Effect[int | str, AiFailure | NotFound, Port],
    )
    assert_type(
        ai.pipe(
            fx.catch_reasons(
                AiFailure, (RateLimited, lambda r, _: fx.succeed(None)), or_else=on_quota
            )
        ),
        fx.Effect[int | str | None, NotFound, Port],
    )
    assert_type(
        ai.pipe(fx.unwrap_reason(AiFailure)),
        fx.Effect[int, NotFound | RateLimited | QuotaExceeded, Port],
    )
    assert_type(only.pipe(fx.unwrap_reason(AiFailure)), fx.Effect[int, RateLimited | QuotaExceeded])
    # or_else must cover every reason the cases leave; the tag must carry a reason.
    ai.pipe(fx.catch_reason(AiFailure, RateLimited, retry_in, or_else=on_rate_only))  # pyright: ignore[reportArgumentType]
    fx.unwrap_reason(NotFound)  # pyright: ignore[reportArgumentType]


def check_stream_and_channel_reasons(
    s: Stream[int, AiFailure | NotFound], ch: channel.Channel[int, AiFailure | NotFound, None]
) -> None:
    assert_type(
        s.pipe(
            stream.catch_reason(AiFailure, RateLimited, lambda r, _: stream.succeed(r.retry_after))
        ),
        Stream[int, AiFailure | NotFound, Never],
    )
    assert_type(
        s.pipe(
            stream.catch_reason(
                AiFailure,
                RateLimited,
                lambda r, _: stream.succeed(r.retry_after),
                or_else=on_quota_stream,
            )
        ),
        Stream[int | str, NotFound, Never],
    )
    assert_type(
        s.pipe(stream.unwrap_reason(AiFailure)),
        Stream[int, NotFound | RateLimited | QuotaExceeded, Never],
    )
    assert_type(
        ch.pipe(
            channel.catch_reasons(
                AiFailure,
                (RateLimited, lambda r, _: channel.succeed(r.retry_after)),
                or_else=on_quota_channel,
            )
        ),
        channel.Channel[int | str, NotFound, None, object, object, object, Never],
    )
    assert_type(
        ch.pipe(channel.unwrap_reason(AiFailure)),
        channel.Channel[int, NotFound | RateLimited | QuotaExceeded, None],
    )


# --- execution plans provide what every step provides ------------------------------


def busy_only(error: str) -> fx.Effect[bool, Never, Level]:
    return fx.succeed(error == "busy")


def check_execution_plan(
    eff: fx.Effect[int, str, Primary | Port], s: Stream[int, str, Primary | Port]
) -> None:
    both = layer.merge(primary_live, port_live)
    plan = execution_plan.make(
        execution_plan.Step(both, attempts=2), execution_plan.Step(primary_live)
    )
    assert_type(plan, execution_plan.ExecutionPlan[Primary, object, Never, Never])
    assert_type(eff.pipe(fx.with_execution_plan(plan)), fx.Effect[int, str, Port])
    assert_type(s.pipe(stream.with_execution_plan(plan)), Stream[int, str, Port])
    guarded = execution_plan.make(execution_plan.Step(both, while_=busy_only))
    assert_type(guarded, execution_plan.ExecutionPlan[Primary | Port, str, Never, Level])
    assert_type(eff.pipe(fx.with_execution_plan(guarded)), fx.Effect[int, str, Level])
    assert_type(
        guarded.capture_requirements,
        fx.Effect[execution_plan.ExecutionPlan[Primary | Port, str, Never, Never], Never, Level],
    )
    assert_type(
        execution_plan.merge(plan, execution_plan.make(execution_plan.Step(fx.Context.empty()))),
        execution_plan.ExecutionPlan[Never, object, Never, Never],
    )

    def observe(event: execution_plan.Event[str]) -> fx.Effect[None, Never, Level]:
        return fx.void

    assert_type(
        eff.pipe(fx.with_execution_plan(plan, on_event=observe)), fx.Effect[int, str, Port | Level]
    )
    # The plan's predicates read the errors, so the effect's errors must be theirs.
    failing_int: fx.Effect[int, int, Primary | Port] = fx.fail(1).pipe(fx.provide(merged_live))
    failing_int.pipe(fx.with_execution_plan(guarded))  # pyright: ignore[reportArgumentType]


# --- folds over iterables and conditional exit hooks -------------------------------


def check_folds_and_hooks(items: list[int], eff: fx.Effect[int, NotFound, Port]) -> None:
    assert_type(fx.succeed(items).head(), fx.Effect[int, fx.NoSuchElementException, Never])
    assert_type(
        fx.reduce(items, lambda: "", lambda acc, n: fx.succeed(acc + str(n))),
        fx.Effect[str, Never, Never],
    )
    assert_type(
        fx.find_first(items, lambda n: fx.succeed(n > 1)), fx.Effect[fx.Option[int], Never, Never]
    )

    def parse(n: int) -> fx.Effect[fx.Result[str, int], Invalid]:
        return fx.succeed(fx.Ok(str(n)))

    assert_type(fx.find_first_filter(items, parse), fx.Effect[fx.Option[str], Invalid, Never])
    assert_type(
        eff.on_exit_if(lambda ex: True, lambda ex: fx.fail(Gone())),
        fx.Effect[int, NotFound | Gone, Port],
    )
    assert_type(
        eff.on_error_filter(lambda c: c.find_error(), lambda e, c: Primary().as_void()),
        fx.Effect[int, NotFound, Port | Primary],
    )


def check_error_combinators(eff: fx.Effect[int, NotFound | Invalid, Port]) -> None:
    # The methods keep every error they may not handle.
    assert_type(
        eff.catch_if(lambda e: isinstance(e, NotFound), lambda e: fx.succeed("x")),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )
    assert_type(
        eff.catch_if(lambda e: True, lambda e: fx.succeed("x"), or_else=lambda e: fx.succeed(0.5)),
        fx.Effect[int | str | float, Never, Port],
    )
    assert_type(
        eff.catch_cause_if(lambda c: c.has_fails, lambda c: fx.succeed(None)),
        fx.Effect[int | None, NotFound | Invalid, Port],
    )
    assert_type(
        eff.tap_error_tag((NotFound, Invalid), fx.succeed),
        fx.Effect[int, NotFound | Invalid, Port],
    )
    assert_type(eff.tap_defect(fx.succeed), fx.Effect[int, NotFound | Invalid, Port])
    assert_type(
        eff.tap_cause_if(lambda c: True, lambda c: fx.fail(Gone())),
        fx.Effect[int, NotFound | Invalid | Gone, Port],
    )
    assert_type(eff.map_both(on_failure=str, on_success=str), fx.Effect[str, str, Port])
    assert_type(eff.flip(), fx.Effect[NotFound | Invalid, int, Port])
    assert_type(eff.sandbox(), fx.Effect[int, fx.Cause[NotFound | Invalid], Port])
    assert_type(eff.or_else_succeed(lambda e: None), fx.Effect[int | None, Never, Port])
    assert_type(eff.eventually(), fx.Effect[int, Never, Port])
    assert_type(eff.option(), fx.Effect[fx.Option[int], Never, Port])
    assert_type(
        eff.match_cause(on_failure=lambda c: c.failures, on_success=str),
        fx.Effect[tuple[NotFound | Invalid, ...] | str, Never, Port],
    )
    assert_type(eff.when(fx.succeed(True)), fx.Effect[fx.Option[int], NotFound | Invalid, Port])
    assert_type(
        eff.filter_or_fail(lambda n: n > 0),
        fx.Effect[int, NotFound | Invalid | fx.NoSuchElementException, Port],
    )
    assert_type(
        eff.filter_or_fail(lambda n: n > 0, lambda n: Gone()),
        fx.Effect[int, NotFound | Invalid | Gone, Port],
    )
    assert_type(
        eff.filter_or_else(lambda n: n > 0, lambda n: fx.succeed("neg")),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )
    assert_type(fx.succeed(eff).flatten(), fx.Effect[int, NotFound | Invalid, Port])
    fx.succeed(1).flatten()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def check_filter_combinators(
    items: list[int], eff: fx.Effect[int, NotFound | Invalid, Port]
) -> None:
    def not_found(e: NotFound | Invalid) -> fx.Result[str, Invalid]:
        return fx.Ok("nf") if isinstance(e, NotFound) else fx.Err(e)

    # Without or_else a rejected error keeps failing as it was, so E stays.
    assert_type(
        eff.catch_filter(not_found, lambda s: fx.succeed(0.5)),
        fx.Effect[int | float, NotFound | Invalid, Port],
    )

    def from_invalid(e: Invalid) -> fx.Effect[None, Gone]:
        return fx.fail(Gone())

    assert_type(
        eff.catch_filter(not_found, lambda s: fx.fail(Gone()), or_else=from_invalid),
        fx.Effect[int | None, Gone, Port],
    )
    # or_else must accept what the filter rejects.
    eff.catch_filter(not_found, fx.succeed, or_else=lambda e: fx.succeed(e.missing))  # pyright: ignore[reportAttributeAccessIssue, reportUnknownArgumentType, reportUnknownLambdaType, reportUnknownMemberType]

    def defects(c: fx.Cause[NotFound | Invalid]) -> fx.Result[BaseException, fx.Cause[Invalid]]:
        return fx.Err(fx.cause.fail(Invalid("bad")))

    assert_type(
        eff.catch_cause_filter(defects, lambda d, c: fx.succeed(str(d))),
        fx.Effect[int | str, Invalid, Port],
    )
    assert_type(
        eff.tap_cause_filter(defects, lambda d, c: fx.fail(Gone())),
        fx.Effect[int, NotFound | Invalid | Gone, Port],
    )

    def even(n: int) -> fx.Result[str, int]:
        return fx.Ok(str(n)) if n % 2 == 0 else fx.Err(n)

    assert_type(fx.filter_map(items, even), fx.Effect[list[str], Never, Never])

    def even_effect(n: int) -> fx.Effect[fx.Result[str, int], Invalid, Port]:
        return fx.succeed(even(n))

    assert_type(
        fx.filter_map_effect(items, even_effect, concurrency=2),
        fx.Effect[list[str], Invalid, Port],
    )


def is_int(x: int | str) -> TypeIs[int]:
    return isinstance(x, int)


async def _one_async() -> int:
    return 1


def check_error_constructors(
    mixed: list[int | str], r: fx.Result[int, str], opt: fx.Option[int | None]
) -> None:
    assert_type(fx.try_(lambda: 1), fx.Effect[int, fx.UnknownError, Never])
    assert_type(fx.try_(lambda: 1, lambda e: Invalid(str(e))), fx.Effect[int, Invalid, Never])
    assert_type(fx.try_(lambda: 1).ignore_cause(), fx.Effect[None, Never, Never])
    assert_type(fx.try_async(_one_async), fx.Effect[int, fx.UnknownError, Never])
    assert_type(fx.try_async(_one_async, lambda e: Invalid(str(e))), fx.Effect[int, Invalid, Never])
    assert_type(fx.try_blocking(lambda: 1), fx.Effect[int, fx.UnknownError, Never])
    assert_type(
        fx.try_blocking(lambda: 1, lambda e: Invalid(str(e))), fx.Effect[int, Invalid, Never]
    )
    assert_type(fx.fail_sync(Gone), fx.Effect[Never, Gone, Never])
    assert_type(fx.fail_cause_sync(lambda: fx.cause.fail(1)), fx.Effect[Never, int, Never])
    assert_type(fx.from_result(r), fx.Effect[int, str, Never])
    assert_type(fx.from_result(fx.Ok(1)), fx.Effect[int, Never, Never])
    assert_type(fx.from_option(opt), fx.Effect[int | None, fx.NoSuchElementException, Never])
    assert_type(fx.from_option(opt, Gone), fx.Effect[int | None, Gone, Never])
    assert_type(fx.from_optional(mixed[0]), fx.Effect[int | str, fx.NoSuchElementException, Never])
    assert_type(
        fx.transpose_option(fx.Some(lookup("k"))),
        fx.Effect[fx.Option[str], NotFound | Invalid, Primary | Port],
    )
    assert_type(
        fx.first_success_of([fx.succeed(1), fx.fail(Gone()), lookup("k")]),
        fx.Effect[int | str, Gone | NotFound | Invalid, Primary | Port],
    )
    assert_type(fx.filter(mixed, is_int), fx.Effect[list[int], Never, Never])
    assert_type(fx.filter(mixed, lambda x: x == 1), fx.Effect[list[int | str], Never, Never])
    assert_type(
        fx.filter(mixed, lambda x: lookup("k").as_(True), concurrency=2),
        fx.Effect[list[int | str], NotFound | Invalid, Primary | Port],
    )


# --- provide removes exactly what the layer builds --------------------------------


def check_provide() -> None:
    partial = lookup("k").pipe(fx.provide(primary_live))
    assert_type(partial, fx.Effect[str, NotFound | Invalid, Port])
    full = partial.pipe(fx.provide(port_live))
    assert_type(full, fx.Effect[str, NotFound | Invalid, Never])
    merged = layer.merge(primary_live, port_live)
    assert_type(merged, layer.Layer[Primary | Port, Never, Never])
    assert_type(lookup("k").pipe(fx.provide(merged)), fx.Effect[str, NotFound | Invalid, Never])
    local = lookup("k").pipe(fx.provide(merged, local=True))
    assert_type(local, fx.Effect[str, NotFound | Invalid, Never])


def check_merge_of_layers_building_nothing() -> None:
    # Layers that build nothing merge to Layer[Never], not Unknown (QA types 9),
    # keeping their errors and requirements; one that builds something still wins.
    startup = layer.effect_discard(fx.log_info("starting"))
    failing = layer.effect_discard(fx.fail(Invalid("bad")))
    needs_port = layer.effect_discard(Port())
    assert_type(layer.merge(startup, startup), layer.Layer[Never, Never, Never])
    assert_type(layer.merge(startup, failing, needs_port), layer.Layer[Never, Invalid, Port])
    assert_type(
        layer.merge(startup, startup, startup, startup, failing), layer.Layer[Never, Invalid, Never]
    )
    assert_type(layer.merge(startup, port_live), layer.Layer[Port, Never, Never])
    assert_type(layer.merge(port_live, startup, startup), layer.Layer[Port, Never, Never])
    assert_type(
        fx.succeed(1).pipe(fx.provide(layer.merge(startup, startup))), fx.Effect[int, Never, Never]
    )


def check_layer_dependencies() -> None:
    needs_port = layer.effect(Replica, Port().map(lambda _: GoodDb()))
    assert_type(needs_port, layer.Layer[Replica, Never, Port])
    assert_type(needs_port.pipe(fx.provide(port_live)), layer.Layer[Replica, Never, Never])
    assert_type(
        needs_port.pipe(layer.provide_merge(port_live)), layer.Layer[Replica | Port, Never, Never]
    )
    # local=True only means something for an effect: a layer target is rejected.
    needs_port.pipe(fx.provide(port_live, local=True))  # pyright: ignore[reportArgumentType]


def check_layer_shapes() -> None:
    layer.succeed(Port, "8080")  # pyright: ignore[reportArgumentType]
    layer.succeed(Primary, object())  # pyright: ignore[reportArgumentType]
    # The tag is read exactly: an expected type cannot widen it to a union.
    replica: layer.Layer[Primary] = layer.succeed(Replica, GoodDb())  # pyright: ignore[reportAssignmentType]
    synced: layer.Layer[Primary] = layer.sync(Replica, GoodDb)  # pyright: ignore[reportAssignmentType]
    built: layer.Layer[Primary] = layer.effect(Replica, fx.succeed(GoodDb()))  # pyright: ignore[reportAssignmentType]
    level: layer.Layer[Level] = layer.succeed(Level, 3)
    fewer: layer.Layer[Never] = layer.succeed(Primary, GoodDb())
    del replica, synced, built, level, fewer


# --- the run gate --------------------------------------------------------------------


def check_run_gate() -> None:
    fx.run_sync(lookup("k"))  # pyright: ignore[reportArgumentType]
    fx.run_sync(lookup("k").pipe(fx.provide(layer.merge(primary_live, port_live))))  # pyright: ignore[reportArgumentType]
    fx.run_sync_exit(lookup("k").pipe(fx.provide(layer.merge(primary_live, port_live))))
    assert_type(fx.run_sync(Level()), int)
    assert_type(fx.MaxOpsBeforeYield(), TagEffect[int, Never, fx.MaxOpsBeforeYield])
    assert_type(fx.CurrentScheduler(), TagEffect[Scheduler, Never, fx.CurrentScheduler])
    assert_type(
        fx.succeed(1).pipe(fx.provide_service(fx.MaxOpsBeforeYield, 16)),
        fx.Effect[int, Never, Never],
    )
    fx.provide_service(fx.MaxOpsBeforeYield, "16")  # pyright: ignore[reportArgumentType]
    fx.provide_service(fx.CurrentScheduler, 1)  # pyright: ignore[reportArgumentType]


# --- combining effects never widens to Unknown ---------------------------------------


def check_combinators() -> None:
    assert_type(fx.all(fx.succeed(1), fx.succeed("a")), fx.Effect[tuple[int, str], Never, Never])
    assert_type(
        fx.all(fx.succeed(1), lookup("k"), concurrency=2),
        fx.Effect[tuple[int, str], NotFound | Invalid, Primary | Port],
    )
    assert_type(fx.succeed(1).zip(fx.succeed("a")), fx.Effect[tuple[int, str], Never, Never])
    assert_type(
        fx.succeed(1).flat_map(lambda n: fx.fail(Invalid(str(n)))), fx.Effect[Never, Invalid, Never]
    )
    assert_type(fx.succeed(1).timeout(1), fx.Effect[int, fx.TimeoutException, Never])
    assert_type(fx.succeed(1).fork(), fx.Effect[fx.Fiber[int, Never], Never, Never])
    assert_type(fx.succeed(1).race(fx.succeed("a")), fx.Effect[int | str, Never, Never])


def check_fiber(fiber: fx.Fiber[int, Invalid], other: fx.Fiber[str, NotFound]) -> None:
    assert_type(fiber.interrupt(), fx.Effect[None, Never, Never])
    assert_type(fiber.interrupt_as(1), fx.Effect[None, Never, Never])
    assert_type(fiber.await_exit(), fx.Effect[fx.Exit[int, Invalid], Never, Never])
    assert_type(fiber.run_in(fx.CloseableScope()), fx.Fiber[int, Invalid])
    assert_type(fiber.add_observer_unsafe(lambda _: None), Callable[[], None])
    assert_type(fx.Fiber.get_current(), fx.Fiber[Any, Any] | None)
    assert_type(fx.Fiber.join_all([fiber]), fx.Effect[list[int], Invalid, Never])
    assert_type(
        fx.Fiber.join_all([fiber, other]), fx.Effect[list[int | str], Invalid | NotFound, Never]
    )
    assert_type(
        fx.Fiber.await_all([fiber, other]),
        fx.Effect[list[fx.Exit[int | str, Invalid | NotFound]], Never, Never],
    )
    assert_type(fx.Fiber.interrupt_all([fiber, other]), fx.Effect[None, Never, Never])
    assert_type(fx.Fiber.interrupt_all_as([fiber], 1), fx.Effect[None, Never, Never])


type _IntFiber = fx.Fiber[int, Invalid]


def check_fork_options(eff: fx.Effect[int, Invalid, Port]) -> None:
    assert_type(eff.fork(start_immediately=True), fx.Effect[_IntFiber, Never, Port])
    assert_type(eff.fork_daemon(uninterruptible="inherit"), fx.Effect[_IntFiber, Never, Port])
    assert_type(eff.fork_scoped(uninterruptible=True), fx.Effect[_IntFiber, Never, Port | fx.Scope])
    assert_type(eff.fork_in(fx.CloseableScope()), fx.Effect[_IntFiber, Never, Port])
    assert_type(eff.await_all_children(), fx.Effect[int, Invalid, Port])
    eff.fork(uninterruptible="always")  # pyright: ignore[reportArgumentType]


# --- structural combinators ----------------------------------------------------------


def check_structural() -> None:
    nf = fx.fail(NotFound("k"))
    inv = fx.fail(Invalid("r"))
    num = fx.succeed(1)
    assert_type(num.zip(inv, concurrent=True), fx.Effect[tuple[int, Never], Invalid, Never])
    assert_type(
        num.zip_with(fx.succeed("a"), lambda n, s: s * n, concurrent=True),
        fx.Effect[str, Never, Never],
    )
    assert_type(num.replicate_effect(3), fx.Effect[list[int], Never, Never])
    assert_type(num.replicate_effect(3, discard=True), fx.Effect[None, Never, Never])
    assert_type(
        fx.all(num, nf, mode="result"),
        fx.Effect[tuple[fx.Result[int, NotFound], fx.Result[Never, NotFound]], Never, Never],
    )
    assert_type(fx.all(num, nf, discard=True), fx.Effect[None, NotFound, Never])
    assert_type(fx.all(num, nf, discard=True, mode="result"), fx.Effect[None, Never, Never])
    assert_type(fx.all_dict({"a": num, "b": nf}), fx.Effect[dict[str, int], NotFound, Never])
    assert_type(
        fx.all_dict({"a": num, "b": inv}, mode="result"),
        fx.Effect[dict[str, fx.Result[int, Invalid]], Never, Never],
    )
    assert_type(fx.all_dict({"a": num}, discard=True), fx.Effect[None, Never, Never])
    assert_type(
        fx.partition([1, 2], lambda n: inv if n else num),
        fx.Effect[tuple[list[int], list[Invalid]], Never, Never],
    )
    assert_type(
        fx.validate([1, 2], lambda n: inv if n else num),
        fx.Effect[list[int], tuple[Invalid, *tuple[Invalid, ...]], Never],
    )
    assert_type(
        fx.validate([1], lambda _: lookup("k"), discard=True),
        fx.Effect[None, tuple[NotFound | Invalid, *tuple[NotFound | Invalid, ...]], Primary | Port],
    )
    assert_type(fx.validate([1], fx.succeed), fx.Effect[list[int], Never, Never])
    assert_type(fx.validate([1], fx.succeed, discard=True), fx.Effect[None, Never, Never])
    assert_type(fx.race_all_first(num, inv), fx.Effect[int, Invalid, Never])
    assert_type(
        lookup("k").timeout_option(1), fx.Effect[fx.Option[str], NotFound | Invalid, Primary | Port]
    )
    assert_type(num.timeout_or_else(1, lambda: inv), fx.Effect[int, Invalid, Never])
    assert_type(lookup("k").cached(), fx.Effect[fx.Effect[str, NotFound | Invalid, Primary | Port]])
    assert_type(
        num.cached_with_ttl(lambda ex: 0 if isinstance(ex, fx.Failure) else 1),
        fx.Effect[fx.Effect[int]],
    )
    assert_type(
        num.cached_invalidate_with_ttl(1), fx.Effect[tuple[fx.Effect[int], fx.Effect[None]]]
    )
    assert_type(
        fx.interruptible_mask(lambda restore: restore(lookup("k"))),
        fx.Effect[str, NotFound | Invalid, Primary | Port],
    )
    num.replicate_effect(2, discard=1)  # pyright: ignore[reportCallIssue, reportArgumentType]
    fx.all(num, mode="validate")  # pyright: ignore[reportCallIssue, reportArgumentType]


def check_context_managers(
    cm: AbstractContextManager[int], acm: AbstractAsyncContextManager[str]
) -> None:
    assert_type(fx.acquire_context(fx.succeed(cm)), fx.Effect[int, Never, fx.Scope])
    assert_type(
        fx.acquire_async_context(fx.succeed(acm).zip(nf_or_port()).map(lambda p: p[0])),
        fx.Effect[str, NotFound, Port | fx.Scope],
    )


def nf_or_port() -> fx.Effect[int, NotFound, Port]:
    return Port().flat_map(lambda p: fx.fail(NotFound("k")) if p < 0 else fx.succeed(p))


# --- scopes ---------------------------------------------------------------------------


def check_scopes() -> None:
    res = fx.acquire_release(fx.succeed(1), lambda _n, _ex: fx.void)
    assert_type(res, fx.Effect[int, Never, fx.Scope])
    assert_type(fx.scoped(res), fx.Effect[int, Never, Never])
    assert_type(fx.scoped(res.zip(Port())), fx.Effect[tuple[int, int], Never, Port])


# --- data types --------------------------------------------------------------------------


def check_data_types(q: fx.Queue[int], endable: fx.Queue[int, fx.Done]) -> None:
    assert_type(fx.Ref.make(0), fx.Effect[fx.Ref[int], Never, Never])
    assert_type(q.take(), fx.Effect[int, Never, Never])
    assert_type(endable.take(), fx.Effect[int, fx.Done, Never])
    endable.end()
    q.end()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(q.offer_all([1, 2]), fx.Effect[list[int], Never, Never])
    assert_type(q.shutdown(), fx.Effect[bool, Never, Never])
    assert_type(q.take_between(1, 0), fx.Effect[list[int], Never, Never])


def check_refs(
    ref: fx.Ref[int], sync: fx.SynchronizedRef[int], sub: fx.SubscriptionRef[bool]
) -> None:
    assert_type(ref.get_and_update_some(fx.Some), fx.Effect[int, Never, Never])
    assert_type(ref.modify_some(lambda n: ("s", None)), fx.Effect[str, Never, Never])
    assert_type(ref.update_some(lambda n: None), fx.Effect[None, Never, Never])
    assert_type(fx.SynchronizedRef.make(0), fx.Effect[fx.SynchronizedRef[int], Never, Never])
    assert_type(sync.update_effect(fx.succeed), fx.Effect[None, Never, Never])
    assert_type(
        sync.update_and_get_effect(lambda n: Port().map(lambda p: p + n)),
        fx.Effect[int, Never, Port],
    )
    assert_type(
        sync.modify_effect(lambda n: fx.fail(NotFound("k")).as_((str(n), n))),
        fx.Effect[str, NotFound, Never],
    )
    assert_type(
        sync.modify_some_effect(lambda n: fx.succeed((str(n), fx.Some(n)))),
        fx.Effect[str, Never, Never],
    )
    assert_type(
        sync.get_and_update_some_effect(lambda n: fx.succeed(fx.Some(n))),
        fx.Effect[int, Never, Never],
    )
    assert_type(fx.SubscriptionRef.make(0), fx.Effect[fx.SubscriptionRef[int], Never, Never])
    assert_type(sub.subscribe(), fx.Effect[Subscription[bool], Never, fx.Scope])
    sub.set(1)  # pyright: ignore[reportArgumentType]
    # Effect declares these ``in out``: a value can be put in as well as read.
    widened: fx.SubscriptionRef[int] = sub  # pyright: ignore[reportAssignmentType]
    narrowed: fx.SynchronizedRef[bool] = sync  # pyright: ignore[reportAssignmentType]
    widened_ref: fx.Ref[object] = ref  # pyright: ignore[reportAssignmentType]
    del widened, narrowed, widened_ref


def check_queue(
    q: fx.Queue[int],
    endable: fx.Queue[int, fx.Done],
    failing: fx.Queue[int, str | fx.Done],
    strings: fx.Queue[int, str],
    leftover: fx.Queue[int, fx.Done[int]],
) -> None:
    assert_type(q.take_n(2), fx.Effect[list[int], Never, Never])
    assert_type(q.take_between(1, 3), fx.Effect[list[int], Never, Never])
    assert_type(q.poll(), fx.Effect[fx.Option[int], Never, Never])
    assert_type(strings.peek(), fx.Effect[int, str, Never])
    assert_type(q.size(), fx.Effect[int, Never, Never])
    assert_type(q.is_full(), fx.Effect[bool, Never, Never])
    assert_type(q.capacity, int | None)
    assert_type(q.interrupt(), fx.Effect[bool, Never, Never])
    assert_type(q.take_unsafe(), fx.Exit[int, Never] | None)
    # clear / collect / await_done take Done out of the error type.
    assert_type(endable.clear(), fx.Effect[list[int], Never, Never])
    assert_type(failing.clear(), fx.Effect[list[int], str, Never])
    assert_type(strings.clear(), fx.Effect[list[int], str, Never])
    assert_type(endable.collect(), fx.Effect[list[int], Never, Never])
    assert_type(endable.await_done(), fx.Effect[None, Never, Never])
    assert_type(failing.collect(), fx.Effect[list[int], str, Never])
    assert_type(failing.await_done(), fx.Effect[None, str, Never])
    assert_type(q.await_done(), fx.Effect[None, Never, Never])
    # end / into need Done (Done[None]) among the queue's errors.
    failing.end()
    leftover.end()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(failing.into(fx.fail("boom")), fx.Effect[bool, Never, Never])
    assert_type(endable.into(Port()), fx.Effect[bool, Never, Port])
    endable.into(fx.fail("boom"))  # pyright: ignore[reportArgumentType]
    strings.into(fx.void)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    q.offer_all(["x"])  # pyright: ignore[reportArgumentType]
    assert_type(fx.Done(3).value, int)
    assert_type(fx.Done().value, None)


def check_queue_views(
    q: fx.Queue[int], failing: fx.Queue[int, str | fx.Done], producer: fx.Enqueue[bool, Never]
) -> None:
    # An Enqueue is contravariant, a Dequeue covariant.
    def consume(takes: fx.Dequeue[float, object]) -> None:
        assert_type(takes.take(), fx.Effect[float, object, Never])

    consume(failing)
    offers: fx.Enqueue[bool, Never] = q
    ends: fx.Enqueue[int, str | fx.Done] = failing
    wide: fx.Enqueue[object, Never] = q  # pyright: ignore[reportAssignmentType]
    assert_type(producer.offer_all([True]), fx.Effect[list[bool], Never, Never])
    producer.offer(1)  # pyright: ignore[reportArgumentType]
    producer.end()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(ends.end(), fx.Effect[bool, Never, Never])
    print(offers, wide)


def check_pubsub(ps: fx.PubSub[int], sub: Subscription[int]) -> None:
    assert_type(fx.PubSub[int].bounded(2), fx.Effect[fx.PubSub[int], Never, Never])
    assert_type(fx.PubSub[int].unbounded(replay=3), fx.Effect[fx.PubSub[int], Never, Never])
    assert_type(
        fx.PubSub.make(lambda: Atomic[str].bounded(4), "sliding"),
        fx.Effect[fx.PubSub[str], Never, Never],
    )
    assert_type(ps.subscribe(), fx.Effect[Subscription[int], Never, fx.Scope])
    assert_type(ps.publish(1), fx.Effect[bool, Never, Never])
    assert_type(ps.publish_all([1, 2]), fx.Effect[bool, Never, Never])
    assert_type(ps.end(0), fx.Effect[bool, Never, Never])
    assert_type(ps.shutdown(), fx.Effect[None, Never, Never])
    assert_type(ps.capacity, int | None)
    assert_type(sub.take(), fx.Effect[int, Never, Never])
    assert_type(sub.take_all(), fx.Effect[Sequence[int], Never, Never])
    assert_type(sub.take_up_to(2), fx.Effect[Sequence[int], Never, Never])
    assert_type(sub.take_between(1, 2), fx.Effect[Sequence[int], Never, Never])
    assert_type(sub.remaining_unsafe(), int | None)
    assert_type(Atomic[int].unbounded().subscribe().poll(), fx.Option[int])
    ps.publish("x")  # pyright: ignore[reportArgumentType]
    ps.end("x")  # pyright: ignore[reportArgumentType]
    # A Subscription only gives messages, so it is covariant; a PubSub is invariant.
    reads: Subscription[object] = sub
    widened: fx.PubSub[object] = ps  # pyright: ignore[reportAssignmentType]
    print(reads, widened)


def check_semaphore(sem: fx.Semaphore) -> None:
    assert_type(sem.take(2), fx.Effect[int, Never, Never])
    assert_type(sem.release(1), fx.Effect[int, Never, Never])
    assert_type(sem.take_if_available(2), fx.Effect[bool, Never, Never])
    assert_type(sem.release_all(), fx.Effect[int, Never, Never])
    assert_type(sem.resize(3), fx.Effect[None, Never, Never])
    assert_type(sem.with_permits(nf_or_port()), fx.Effect[int, NotFound, Port])
    assert_type(
        sem.with_permits_if_available(nf_or_port()),
        fx.Effect[fx.Some[int] | None, NotFound, Port],
    )
    assert_type(nf_or_port().pipe(sem.with_permits), fx.Effect[int, NotFound, Port])


def check_partitioned_semaphore(
    sem: fx.PartitionedSemaphore[str], any_key: fx.PartitionedSemaphore[Hashable]
) -> None:
    # Keys only go in (Effect's `in K`): a semaphore taking any key serves as a
    # str-keyed one, not the other way round.
    check_partitioned_semaphore(any_key, any_key)
    check_partitioned_semaphore(sem, sem)  # pyright: ignore[reportArgumentType]
    assert_type(
        fx.PartitionedSemaphore[str].make(2), fx.Effect[fx.PartitionedSemaphore[str], Never, Never]
    )
    assert_type(sem.take("a", 2), fx.Effect[None, Never, Never])
    assert_type(sem.release(1), fx.Effect[int, Never, Never])
    assert_type(sem.available, fx.Effect[int, Never, Never])
    assert_type(sem.with_permits("a", nf_or_port()), fx.Effect[int, NotFound, Port])
    assert_type(
        sem.with_permits_if_available(nf_or_port()),
        fx.Effect[fx.Some[int] | None, NotFound, Port],
    )
    # Keys are typed: a str-keyed semaphore rejects other keys.
    sem.take(1, 1)  # pyright: ignore[reportArgumentType]
    # Keys must be hashable.
    fx.PartitionedSemaphore[list[int]]  # pyright: ignore[reportInvalidTypeArguments]


def check_latch(latch: fx.Latch) -> None:
    assert_type(fx.Latch.make(), fx.Effect[fx.Latch, Never, Never])
    assert_type(latch.open(), fx.Effect[bool, Never, Never])
    assert_type(latch.release(), fx.Effect[bool, Never, Never])
    assert_type(latch.close(), fx.Effect[bool, Never, Never])
    assert_type(latch.wait(), fx.Effect[None, Never, Never])
    assert_type(latch.when_open(nf_or_port()), fx.Effect[int, NotFound, Port])
    assert_type(latch.is_open(), bool)
    assert_type(latch.open_unsafe(), bool)


def check_deferred(d: fx.Deferred[int, str]) -> None:
    assert_type(d.done(fx.Success(1)), fx.Effect[bool, Never, Never])
    # complete runs an effect (with its requirements); complete_with stores an unrun one.
    assert_type(d.complete(Port().map(lambda _: 1)), fx.Effect[bool, Never, Port])
    assert_type(d.complete_with(fx.succeed(1)), fx.Effect[bool, Never, Never])
    assert_type(d.poll(), fx.Effect[fx.Effect[int, str, Never] | None, Never, Never])
    assert_type(d.is_done(), fx.Effect[bool, Never, Never])
    assert_type(d.interrupt(), fx.Effect[bool, Never, Never])
    assert_type(d.die(ValueError()), fx.Effect[bool, Never, Never])
    assert_type(d.sync(lambda: 1), fx.Effect[bool, Never, Never])
    # into keeps the effect's requirements; its errors go into the deferred.
    assert_type(Port().map(lambda _: 1).pipe(d.into), fx.Effect[bool, Never, Port])
    d.into(fx.fail(1))  # pyright: ignore[reportArgumentType]
    d.sync(lambda: "x")  # pyright: ignore[reportArgumentType]
    # The pre-Effect-v4 spelling `complete(exit)` is now an error: completing with an
    # exit is `done`.
    d.complete(fx.Success(1))  # pyright: ignore[reportArgumentType]
    # A stored effect runs in each waiter, which can't provide its requirements.
    d.complete_with(Port().map(lambda _: 1))  # pyright: ignore[reportArgumentType]


def check_durations(scheduler: SyncScheduler) -> None:
    # Durations are parsed once, at the boundary, into Seconds (never NaN).
    assert_type(to_seconds(1.5), Seconds)
    assert_type(schedule.fibonacci(1), schedule.Schedule[Seconds])
    # Past the boundary, a raw float is rejected: it must go through to_seconds.
    fx.testing.TestClock().sleep(1.0)  # pyright: ignore[reportArgumentType]
    scheduler.call_later(1.0, lambda: None)  # pyright: ignore[reportArgumentType]
    # A schedule's delay is Seconds too, so custom steps can't return NaN.
    schedule.Continue(1, 1.0)  # pyright: ignore[reportArgumentType]


# --- Schedule ---------------------------------------------------------------------------
# Schedule[Out, In, E, R]: steps may fail with E and need R; combinators add to both.


def check_schedule_constructors() -> None:
    assert_type(schedule.spaced(1), schedule.Schedule[int, object, Never, Never])
    assert_type(schedule.forever, schedule.Schedule[int])
    assert_type(schedule.once, schedule.Schedule[None])
    assert_type(schedule.exponential(1), schedule.Schedule[Seconds])
    assert_type(schedule.during(1), schedule.Schedule[Seconds])
    assert_type(schedule.max(schedule.spaced(1), schedule.recurs(2)), schedule.Schedule[Seconds])
    ids: schedule.Schedule[str, str] = schedule.identity()
    assert_type(ids.passthrough(), schedule.Schedule[str, str])
    assert_type(ids.concat(schedule.spaced(1)), schedule.Schedule[str | int, str])
    assert_type(ids.concat_result(schedule.spaced(1)), schedule.Schedule[fx.Result[int, str], str])

    def step(now: float, n: int) -> fx.Effect[schedule.Decision[str], NotFound, Port]:
        return Port().as_(schedule.Stop(str(n)))

    custom = schedule.from_step(fx.succeed(step))
    assert_type(custom, schedule.Schedule[str, int, NotFound, Port])
    assert_type(
        schedule.to_step(custom),
        fx.Effect[schedule.StepFn[str, int, NotFound, Port], Never, Port],
    )


def check_schedule_combinators(s: schedule.Schedule[int, str]) -> None:
    assert_type(s.map(lambda m: m.input), schedule.Schedule[str, str])
    assert_type(
        s.map_effect(lambda _: fx.fail(NotFound("k"))), schedule.Schedule[Never, str, NotFound]
    )
    assert_type(s.tap(lambda _: Port()), schedule.Schedule[int, str, Never, Port])
    assert_type(s.while_(lambda m: m.attempt < 3), schedule.Schedule[int, str])
    assert_type(
        s.while_effect(lambda _: fx.fail(NotFound("k"))), schedule.Schedule[int, str, NotFound]
    )
    assert_type(s.modify_delay(lambda m: fx.succeed(m.duration)), schedule.Schedule[int, str])
    assert_type(s.add_delay(lambda _: Port().as_(1.0)), schedule.Schedule[int, str, Never, Port])
    assert_type(s.up_to(times=3, duration=1), schedule.Schedule[int, str])
    assert_type(s.jittered(), schedule.Schedule[int, str])
    assert_type(s.pipe(schedule.jittered), schedule.Schedule[int, str])
    assert_type(s.pipe(schedule.passthrough), schedule.Schedule[str, str])
    assert_type(schedule.forever.pipe(schedule.set_input_type(str)), schedule.Schedule[int, str])
    s.pipe(schedule.set_input_type(int))  # pyright: ignore[reportArgumentType]
    # Decisions and metadata are immutable, so covariant.
    _meta: schedule.Metadata[object, object] = schedule.Metadata[int, str](
        input="a",
        output=1,
        duration=Seconds(0.0),
        attempt=1,
        start=0.0,
        now=0.0,
        elapsed=0.0,
        elapsed_since_previous=0.0,
    )
    _decision: schedule.Decision[object] = schedule.Continue[int](1, Seconds(0.0))

    # The predicate sees the schedule's own input and output types.
    def on_int_inputs(m: schedule.Metadata[int, int]) -> bool:
        return m.input > 0

    s.while_(on_int_inputs)  # pyright: ignore[reportArgumentType]


def check_schedule_effects(
    eff: fx.Effect[int, NotFound, Port], only_str: schedule.Schedule[int, str]
) -> None:
    failing = schedule.recurs(3).while_effect(lambda _: fx.fail("boom"))
    assert_type(eff.repeat(schedule.recurs(3)), fx.Effect[int, NotFound, Port])
    assert_type(eff.repeat(failing), fx.Effect[int, NotFound | str, Port])
    assert_type(eff.repeat(times=2), fx.Effect[int, NotFound, Port])
    assert_type(eff.repeat(until=lambda n: fx.fail("x")), fx.Effect[int, NotFound | str, Port])
    assert_type(eff.retry(schedule.recurs(3)), fx.Effect[int, NotFound, Port])
    assert_type(eff.retry(failing), fx.Effect[int, NotFound | str, Port])
    assert_type(eff.retry(while_=lambda e: e.key == "k"), fx.Effect[int, NotFound, Port])
    assert_type(
        eff.retry_or_else(schedule.recurs(3), lambda e, n: fx.succeed("gave up")),
        fx.Effect[int | str, Never, Port],
    )
    assert_type(
        eff.repeat_or_else(schedule.recurs(3), lambda e, m: fx.succeed("failed")),
        fx.Effect[int | str, Never, Port],
    )
    assert_type(eff.schedule(schedule.spaced(1)), fx.Effect[int, NotFound, Port])
    assert_type(eff.schedule_from(0, schedule.spaced(1)), fx.Effect[int, NotFound, Port])
    assert_type(
        schedule.CurrentMetadata(),
        TagEffect[schedule.Metadata[object, object], Never, schedule.CurrentMetadata],
    )
    # A retry policy must accept the effect's errors; a repeat schedule its values.
    eff.retry(only_str)  # pyright: ignore[reportCallIssue, reportArgumentType]
    eff.repeat(only_str)  # pyright: ignore[reportCallIssue, reportArgumentType]
    # A builder types the schedule's metadata with the errors (or values).
    assert_type(
        eff.retry(lambda typed: typed(schedule.recurs(3)).while_(lambda m: m.input.key == "k")),
        fx.Effect[int, NotFound, Port],
    )
    assert_type(
        eff.repeat(lambda typed: typed(schedule.recurs(3)).while_(lambda m: m.input > 0)),
        fx.Effect[int, NotFound, Port],
    )
    assert_type(
        eff.repeat(lambda typed: typed(schedule.identity()).tap(lambda _: Port())),
        fx.Effect[int, NotFound, Port],
    )
    eff.retry(lambda typed: typed(only_str))  # pyright: ignore[reportArgumentType]


def only_not_found(e: NotFound | Invalid) -> TypeIs[NotFound]:
    return isinstance(e, NotFound)


def is_positive_int(v: int | str) -> TypeIs[int]:
    return isinstance(v, int)


def check_schedule_refinements(
    eff: fx.Effect[int | str, NotFound | Invalid, Port],
) -> None:
    # A TypeIs predicate as `until` narrows, as Effect's refinement does.
    assert_type(eff.retry(until=only_not_found), fx.Effect[int | str, NotFound, Port])
    assert_type(eff.repeat(until=is_positive_int), fx.Effect[int, NotFound | Invalid, Port])
    # With a schedule or times, the predicate need not have held: no narrowing.
    assert_type(
        eff.retry(times=3, until=only_not_found), fx.Effect[int | str, NotFound | Invalid, Port]
    )
    assert_type(
        eff.repeat(schedule=schedule.recurs(3), until=is_positive_int),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )
    assert_type(
        eff.retry(until=lambda e: isinstance(e, NotFound)),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )
    # `while_` can stop on an error `until` never accepted (QA types 3): no narrowing,
    # so recovering only the narrowed error leaves the rest in E.
    retried = eff.retry(until=only_not_found, while_=lambda e: isinstance(e, Invalid))
    assert_type(retried, fx.Effect[int | str, NotFound | Invalid, Port])
    assert_type(
        retried.pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(0))),
        fx.Effect[int | str, Invalid, Port],
    )
    assert_type(
        eff.repeat(until=is_positive_int, while_=lambda v: False),
        fx.Effect[int | str, NotFound | Invalid, Port],
    )


# --- Result, Exit and Option ------------------------------------------------------------
# The methods exist on both cases, so they apply to the union without narrowing, and each
# side keeps its own type.


def check_result(r: fx.Result[int, str], raising: fx.Result[int, ValueError]) -> None:
    assert_type(r.map(str), fx.Ok[str] | fx.Err[str])
    assert_type(r.map_error(len), fx.Err[int] | fx.Ok[int])
    assert_type(r.map_both(on_failure=len, on_success=str), fx.Err[int] | fx.Ok[str])
    assert_type(
        r.flat_map(lambda n: fx.Ok(n) if n else fx.Err(0.0)),
        fx.Ok[int] | fx.Err[float] | fx.Err[str],
    )
    assert_type(r.get_or_else(len), int)
    assert_type(r.match(on_failure=len, on_success=float), int | float)
    assert_type(raising.get_or_raise(), int)
    # Only an Err holding an exception can be raised.
    r.get_or_raise()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(fx.result.try_(lambda: 1), fx.Ok[int] | fx.Err[Exception])
    assert_type(fx.result.try_(lambda: 1, str), fx.Ok[int] | fx.Err[str])
    assert_type(fx.result.from_optional(1 if r else None, lambda: "none"), fx.Ok[int] | fx.Err[str])
    # all joins the error types and never widens to Unknown.
    assert_type(fx.result.all(r, raising), fx.Ok[tuple[int, int]] | fx.Err[str | ValueError])
    assert_type(fx.result.all(fx.Ok(1), fx.Err("e")), fx.Ok[tuple[int, Never]] | fx.Err[str])
    assert_type(fx.result.all(*[r, r]), fx.Ok[tuple[int, ...]] | fx.Err[str])
    # A side the callback never produces is Never, not Unknown.
    assert_type(r.flat_map(lambda n: fx.Ok(str(n))), fx.Ok[str] | fx.Err[Never] | fx.Err[str])
    assert_type(fx.Ok(1).flat_map(lambda _: fx.Err("e")), fx.Ok[Never] | fx.Err[str])
    assert_type(fx.result.from_optional(None, lambda: "none"), fx.Ok[Never] | fx.Err[str])
    if fx.result.is_ok(r):
        assert_type(r, fx.Ok[int])
    else:
        assert_type(r, fx.Err[str])


def check_exit(ex: fx.Exit[int, str], exits: list[fx.Exit[int, str]]) -> None:
    assert_type(ex.map(str), fx.Success[str] | fx.Failure[str])
    assert_type(ex.map_error(len), fx.Success[int] | fx.Failure[int])
    assert_type(ex.map_both(on_failure=len, on_success=str), fx.Success[str] | fx.Failure[int])
    assert_type(ex.as_void(), fx.Success[None] | fx.Failure[str])
    assert_type(ex.match(on_failure=lambda c: c.failures, on_success=str), str | tuple[str, ...])
    assert_type(fx.exit.as_void_all(exits), fx.Exit[None, str])
    assert_type(fx.exit.as_void_all([fx.Success(1)]), fx.Exit[None, Never])
    if fx.exit.is_failure(ex):
        assert_type(ex, fx.Failure[str])
    else:
        assert_type(ex, fx.Success[int])


def check_option(o: fx.Option[int | None]) -> None:
    # Some(None) is a present None: the nesting survives the round trip.
    assert_type(fx.option.from_optional(1 if o else None), fx.Some[int] | None)
    assert_type(fx.option.map(o, str), fx.Some[str] | None)
    assert_type(fx.option.flat_map(o, fx.option.from_optional), fx.Some[int] | None)
    assert_type(fx.option.get_or_else(o, lambda: "x"), int | str | None)
    assert_type(fx.option.get_or_raise(o), int | None)
    assert_type(fx.option.from_iterable([None]), fx.Some[None] | None)
    assert_type(fx.option.flat_map(o, lambda _: None), fx.Some[Never] | None)
    # Some, Success and Failure are covariant, like Ok and Err.
    _widened: tuple[fx.Option[object], fx.Exit[object, Exception]] = (o, fx.exit.fail(ValueError()))
    match o:
        case fx.Some(value):
            assert_type(value, int | None)
        case None:
            pass


def is_int_or_str(x: int | str) -> TypeIs[int]:
    return isinstance(x, int)


def check_result_long_tail(r: fx.Result[int, str], mixed: fx.Result[int | str, str]) -> None:
    assert_type(r.merge(), int | str)
    assert_type(r.flip(), fx.Err[int] | fx.Ok[str])
    assert_type(r.tap(print), fx.Ok[int] | fx.Err[str])
    assert_type(r.and_then(fx.Ok("x")), fx.Ok[str] | fx.Err[Never] | fx.Err[str])
    assert_type(r.or_else(lambda e: fx.Ok(len(e))), fx.Ok[int] | fx.Err[Never])
    assert_type(r.get_or_none(), int | None)
    assert_type(r.get_or_raise_with(ValueError), int)
    # A TypeIs predicate narrows the success.
    assert_type(mixed.filter_or_fail(is_int_or_str, str), fx.Ok[int] | fx.Err[str])
    assert_type(r.filter_or_fail(lambda n: n > 0, str), fx.Ok[int] | fx.Err[str])
    assert_type(fx.result.lift_predicate(1, is_int_or_str, str), fx.Ok[int] | fx.Err[str])
    assert_type(fx.result.from_option(fx.Some(1), lambda: "e"), fx.Ok[int] | fx.Err[str])
    assert_type(fx.result.succeed_some(1), fx.Ok[fx.Some[int]])
    assert_type(fx.result.transpose_option(fx.Some(r)), fx.Ok[fx.Some[int] | None] | fx.Err[str])
    assert_type(fx.result.all_dict({"a": r}), fx.Ok[dict[str, int]] | fx.Err[str])
    if fx.result.is_result(object()):
        pass


def check_option_long_tail(o: fx.Option[int], words: fx.Option[str]) -> None:
    assert_type(fx.option.void, fx.Some[None] | None)
    assert_type(fx.option.as_(o, "a"), fx.Some[str] | None)
    assert_type(fx.option.and_then(o, words), fx.Some[str] | None)
    assert_type(fx.option.flatten(fx.Some(o)), fx.Some[int] | None)
    assert_type(fx.option.product(o, words), fx.Some[tuple[int, str]] | None)
    assert_type(fx.option.all(o, words), fx.Some[tuple[int, str]] | None)
    assert_type(fx.option.all_dict({"a": o}), fx.Some[dict[str, int]] | None)
    assert_type(fx.option.zip_with(o, words, lambda n, w: w * n), fx.Some[str] | None)
    assert_type(fx.option.or_else(o, lambda: words), fx.Some[int | str] | None)
    assert_type(fx.option.or_else_result(o, lambda: words), fx.Some[fx.Result[str, int]] | None)
    assert_type(fx.option.get_success(fx.Ok(1)), fx.Some[int] | None)
    assert_type(fx.option.get_or_raise_with(o, ValueError), int)
    assert_type(fx.option.flat_map_optional(words, lambda w: w or None), fx.Some[str] | None)
    assert_type(fx.option.to_list(o), list[int])
    assert_type(
        fx.option.partition_map(o, lambda n: fx.Ok(str(n))),
        tuple[fx.Some[str] | None, fx.Some[Never] | None],
    )
    mixed: fx.Option[int | str] = None
    assert_type(fx.option.filter(mixed, is_int_or_str), fx.Some[int] | None)
    assert_type(fx.option.lift_predicate(1, is_int_or_str), fx.Some[int] | None)
    if fx.option.is_some(o):
        assert_type(o, fx.Some[int])


def check_exit_accessors(ex: fx.Exit[int, str]) -> None:
    assert_type(ex.has_fails, bool)
    assert_type(ex.find_error(), fx.Err[fx.Success[int]] | fx.Ok[str] | fx.Err[fx.Failure[str]])
    assert_type(ex.find_defect(), BaseException | None)
    assert_type(ex.get_success(), fx.Some[int] | None)
    assert_type(ex.get_cause(), fx.Some[fx.Cause[str]] | None)
    assert_type(ex.filter_value(), fx.Ok[int] | fx.Err[fx.Failure[str]])
    assert_type(fx.exit.fail_cause(fx.cause.fail("e")), fx.Failure[str])


def check_filters() -> None:
    from pyfect import filters

    def even(n: int) -> fx.Result[int, int]:
        return fx.Ok(n) if n % 2 == 0 else fx.Err(n)

    def halve(n: int) -> fx.Result[float, str]:
        return fx.Ok(n / 2) if n else fx.Err("zero")

    assert_type(filters.compose(even, halve), Callable[[int], fx.Result[float, int | str]])
    assert_type(filters.zip(even, halve), Callable[[int], fx.Result[tuple[int, float], int | str]])
    assert_type(filters.compose_passthrough(even, halve), Callable[[int], fx.Result[float, int]])
    assert_type(
        filters.from_predicate(is_int_or_str), Callable[[int | str], fx.Result[int, int | str]]
    )
    assert_type(filters.instance_of(str), Callable[[object], fx.Result[str, object]])
    assert_type(filters.to_option(even), Callable[[int], fx.Option[int]])


class _CoreADb(fx.Tag[str]): ...


def check_effect_core_a(eff: fx.Effect[int, str, _CoreADb]) -> None:
    def even(n: int) -> fx.Result[int, float]:
        return fx.Ok(n) if n % 2 == 0 else fx.Err(n / 2)

    assert_type(fx.succeed_none, fx.Effect[None])
    assert_type(fx.succeed_some(1), fx.Effect[fx.Some[int]])
    assert_type(eff.as_some(), fx.Effect[fx.Some[int], str, _CoreADb])
    assert_type(eff.is_failure(), fx.Effect[bool, Never, _CoreADb])
    assert_type(fx.with_fiber_succeed(lambda f: f.id), fx.Effect[int])
    assert_type(
        eff.filter_map_or_else(even, lambda x: fx.succeed(str(x))),
        fx.Effect[int | str, str, _CoreADb],
    )
    assert_type(eff.filter_map_or_fail(even, str), fx.Effect[int, str, _CoreADb])
    assert_type(
        eff.filter_map_or_fail(even), fx.Effect[int, str | fx.NoSuchElementException, _CoreADb]
    )
    # set_context removes the services it provides from R.
    assert_type(
        eff.pipe(fx.set_context(fx.Context.make(_CoreADb, "db"))), fx.Effect[int, str, Never]
    )


def check_cause(c: fx.Cause[str]) -> None:
    assert_type(fx.cause.empty, fx.Cause[Never])
    assert_type(fx.cause.from_reasons([Fail(1), Die(ValueError())]), fx.Cause[int])
    assert_type(c.map(len), fx.Cause[int])
    assert_type(c.interruptors, frozenset[int])
    assert_type(c.filter_interruptors(), frozenset[int] | None)
    assert_type(c.find_fail(), Fail[str] | fx.Cause[Never])
    assert_type(c.find_error(), fx.Ok[str] | fx.Err[fx.Cause[Never]])
    assert_type(c.find_die(), Die | None)
    assert_type(c.find_defect(), BaseException | None)
    assert_type(c.find_interrupt(), Interrupt | None)
    assert_type(c.pretty_errors(), tuple[BaseException, ...])
    assert_type(fx.cause.from_reasons([Interrupt(1), Die(ValueError())]), fx.Cause[Never])
    assert_type(c + fx.cause.fail(1), fx.Cause[str | int])


# --- TaggedError hashing -----------------------------------------------------------
# A plain ``@dataclass`` subclass hashes at runtime, but pyright synthesizes
# ``__hash__ = None`` for it. A ``dataclass_transform`` base would fix that only by
# giving every plain subclass a field-only ``__init__`` (``Boom("msg")`` stops
# type-checking), so ``eq=False`` is the spelling pyright accepts.


@dataclass(eq=False)
class HashableNotFound(fx.TaggedError):
    key: str


hashable_errors = {HashableNotFound("k")}
unhashable_to_pyright = {NotFound("k")}  # pyright: ignore[reportUnhashable]


# --- TaggedError fields --------------------------------------------------------------
# A field needs ``@dataclass``. A plain subclass keeps ``Exception``'s ``*args``
# constructor (no ``dataclass_transform`` base: research/typing/tagged_error_1_fields.py),
# so pyright rejects a field keyword; the positional ``TooHeavy("a")`` it can't catch
# raises TypeError when constructed (tests/test_tagged_error.py).


class PlainArgs(fx.TaggedError): ...


class UndecoratedFields(fx.TaggedError):
    task: str


@dataclass(eq=False)
class DecoratedFields(fx.TaggedError):
    task: str


def check_tagged_error_fields() -> None:
    assert_type(PlainArgs("msg", 1), PlainArgs)
    assert_type(DecoratedFields(task="a").task, str)
    DecoratedFields()  # pyright: ignore[reportCallIssue]
    UndecoratedFields(task="a")  # pyright: ignore[reportCallIssue]


# --- testing ------------------------------------------------------------------------
# A decorated test's body may need a Scope and, through a first parameter annotated
# Services[...], what a layer_fixture builds. Needing anything else is an error at the
# decorator, so a test can't be written that dies with a missing service.


@fx.testing.effect
def check_test_needs_nothing():
    yield from fx.add_finalizer(lambda _: fx.void)


@fx.testing.effect
def check_test_takes_fixtures(n: int):
    yield from fx.succeed(n)


@fx.testing.live(timeout=1)
def check_test_returns_an_effect() -> fx.Effect[int, str]:
    return fx.fail("typed errors fail the test")


@fx.testing.effect
def check_test_uses_services(ports: fx.testing.Services[Port], n: int):
    yield from Port()


@fx.testing.effect  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
def check_test_missing_a_service():
    yield from Port()


@fx.testing.effect  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
def check_test_missing_a_service_its_fixture_lacks(ports: fx.testing.Services[Port]):
    yield from Primary()


def check_property_tests() -> None:
    @fx.testing.prop(S.Int, label=S.String)
    def plain(n: int, label: str) -> bool:
        return n >= 0

    assert_type(plain, Callable[..., None])

    @fx.testing.effect_prop(S.Int)
    def effectful(n: int):
        yield from fx.succeed(n)

    assert_type(effectful, Callable[..., None])

    # A plain property returning an effect would pass without running it.
    @fx.testing.prop(S.Int)  # pyright: ignore[reportArgumentType]
    def returns_an_effect(n: int):
        return fx.succeed(n > 0)

    @fx.testing.prop(S.Int)  # pyright: ignore[reportArgumentType]
    def is_a_generator(n: int):
        yield from fx.succeed(n)


class CheckTestClass:
    """Test methods take the fixture right after ``self``."""

    @fx.testing.effect
    def check_method_uses_services(self, ports: fx.testing.Services[Port]):
        yield from Port()

    @fx.testing.live
    def check_method_needs_nothing(self):
        yield from fx.void

    @fx.testing.effect  # pyright: ignore[reportCallIssue, reportArgumentType, reportUntypedFunctionDecorator]
    def check_method_missing_a_service_its_fixture_lacks(self, ports: fx.testing.Services[Port]):
        yield from Primary()


def check_testing() -> None:
    assert_type(
        CheckTestClass.check_method_uses_services,
        Callable[[CheckTestClass, fx.testing.Services[Port]], None],
    )
    assert_type(check_test_needs_nothing, Callable[[], None])
    assert_type(check_test_takes_fixtures(1), None)
    assert_type(check_test_returns_an_effect, Callable[[], None])
    assert_type(fx.testing.effect(timeout=1, asyncio=True), fx.testing.TestDecorator)
    assert_type(fx.testing.test_clock(), fx.Effect[fx.testing.TestClock])
    assert_type(fx.testing.TestClock.layer(), fx.Layer[Never])
    assert_type(fx.testing.with_live(Port()), fx.Effect[int, Never, Port])
    assert_type(fx.testing.run_test_exit(fx.fail("e")), fx.Exit[Never, str])
    coroutine = fx.testing.run_test_async(fx.succeed(1))
    assert_type(coroutine, CoroutineType[Any, Any, int]).close()
    assert_type(fx.testing.layer_fixture(port_live), FixtureFunctionDefinition)
    scoped_value: fx.Effect[int, str, fx.Scope] = fx.succeed(1)
    assert_type(fx.testing.effect_fixture(scoped_value), FixtureFunctionDefinition)
    fx.testing.effect_fixture(Port())  # pyright: ignore[reportArgumentType]
    fx.testing.run_test(fx.fail("e"))  # pyright: ignore[reportArgumentType]


def check_flaky(scoped_int: fx.Effect[int, str, fx.Scope]) -> None:
    assert_type(fx.testing.flaky(scoped_int), fx.Effect[int])
    assert_type(fx.testing.flaky(Port().and_then(scoped_int)), fx.Effect[int, Never, Port])
    fx.testing.run_test(fx.testing.flaky(scoped_int))


def check_fiber_collections(port_int: fx.Effect[int, Never, Port]) -> None:
    assert_type(fx.FiberSet.make(), fx.Effect[fx.FiberSet[object, object], Never, fx.Scope])
    assert_type(fx.FiberSet[int, str].make(), fx.Effect[fx.FiberSet[int, str], Never, fx.Scope])
    fiber_set: fx.FiberSet[int, str] = fx.FiberSet()
    assert_type(fiber_set.run(port_int), fx.Effect[fx.Fiber[int, str], Never, Port])
    assert_type(fiber_set.join(), fx.Effect[None, str])
    assert_type(fiber_set.await_empty(), fx.Effect[None])
    fiber_set.run(fx.succeed("x"))  # pyright: ignore[reportArgumentType]
    assert_type(fiber_set.runtime(), fx.Effect[FiberSetRuntime[int, str, Never], Never, Never])
    run_set = fiber_set.runtime(Port)
    assert_type(run_set, fx.Effect[FiberSetRuntime[int, str, Port], Never, Port])
    assert_type(
        fx.FiberSet[int, str].make_runtime(Port, Primary),
        fx.Effect[FiberSetRuntime[int, str, Port | Primary], Never, fx.Scope | Port | Primary],
    )

    fiber_map: fx.FiberMap[str, int, Never] = fx.FiberMap()
    assert_type(fiber_map.run("a", fx.succeed(1)), fx.Effect[fx.Fiber[int, Never], Never, Never])
    assert_type(fiber_map.get("a"), fx.Effect[fx.Fiber[int, Never] | None])
    assert_type(fiber_map.has_unsafe("a"), bool)
    assert_type(fiber_map.remove("a"), fx.Effect[None])
    fiber_map.run(1, fx.succeed(1))  # pyright: ignore[reportArgumentType]
    fx.FiberMap[list[int]].make()  # pyright: ignore[reportInvalidTypeArguments]
    assert_type(
        fx.FiberMap[str, int, Never].make_runtime(),
        fx.Effect[FiberMapRuntime[str, int, Never, Never], Never, fx.Scope],
    )
    assert_type(
        fiber_map.runtime_async(Port),
        fx.Effect[FiberMapAsyncRuntime[str, int, Never, Port], Never, Port],
    )

    handle: fx.FiberHandle[int, str] = fx.FiberHandle()
    assert_type(
        fx.FiberHandle[int, str].make(), fx.Effect[fx.FiberHandle[int, str], Never, fx.Scope]
    )
    assert_type(handle.run(port_int), fx.Effect[fx.Fiber[int, str], Never, Port])
    assert_type(handle.get_unsafe(), fx.Fiber[int, str] | None)
    assert_type(handle.clear(), fx.Effect[None])
    assert_type(handle.runtime(Port), fx.Effect[FiberHandleRuntime[int, str, Port], Never, Port])


def check_fiber_set_runner(
    run: FiberSetRuntime[int, str, Port], port_int: fx.Effect[int, Never, Port]
) -> None:
    assert_type(run(port_int), fx.Fiber[int, str])
    run(Primary().as_(1))  # pyright: ignore[reportArgumentType]


def check_fiber_map_async_runner(run: FiberMapAsyncRuntime[str, int, Never, Never]) -> None:
    assert_type(run("a", fx.succeed(1), only_if_missing=True), asyncio.Future[int])


# --- running with a context, and ManagedRuntime ---------------------------------------


def check_run_with_context(port_ctx: fx.Context[Port], both: fx.Context[Primary | Port]) -> None:
    assert_type(fx.Context.make(Port, 1), fx.Context[Port])
    assert_type(fx.Context.make(Port, 1).add(Primary, GoodDb()), fx.Context[Port | Primary])
    assert_type(fx.Context.empty(), fx.Context[Never])
    fx.Context.make(Port, "1")  # pyright: ignore[reportArgumentType]
    assert_type(fx.run_sync(Port(), context=port_ctx), int)
    assert_type(fx.run_sync(Port(), context=both), int)
    fx.run_sync(lookup("k").catch_all(lambda _: fx.succeed("")), context=both)
    fx.run_sync(lookup("k").catch_all(lambda _: fx.succeed("")), context=port_ctx)  # pyright: ignore[reportArgumentType]
    assert_type(fx.run_sync_exit(lookup("k"), context=both), fx.Exit[str, NotFound | Invalid])
    assert_type(fx.run_fork(lookup("k"), context=both), fx.Fiber[str, NotFound | Invalid])
    assert_type(fx.run_fork(fx.succeed(1)), fx.Fiber[int, Never])
    fx.run_fork(Port())  # pyright: ignore[reportArgumentType]
    assert_type(fx.run_callback(fx.succeed(1)), fx.Interruptor)


def check_run_main() -> None:
    # As Effect's runMain: errors are allowed (teardown maps them to a status).
    assert_type(fx.run_main(fx.fail(NotFound("k")).as_(1)), int)
    fx.run_main(Port())  # pyright: ignore[reportArgumentType]


def check_managed_runtime() -> None:
    runtime = fx.ManagedRuntime.make(merged_live)
    assert_type(runtime, fx.ManagedRuntime[Primary | Port, Never])
    assert_type(runtime.run_sync(Port()), int)
    assert_type(runtime.run_sync_exit(lookup("k")), fx.Exit[str, NotFound | Invalid])
    assert_type(runtime.run_fork(lookup("k")), fx.Fiber[str, NotFound | Invalid])
    assert_type(runtime.context_effect, fx.Effect[fx.Context[Primary | Port], Never, Never])
    assert_type(runtime.run_async(Port()), CoroutineType[Any, Any, int]).close()
    runtime.run_sync(Replica())  # pyright: ignore[reportArgumentType]
    runtime.run_sync(lookup("k"))  # pyright: ignore[reportArgumentType]

    fallible = fx.ManagedRuntime.make(layer.effect(Port, fx.fail(NotFound("port"))))
    assert_type(fallible, fx.ManagedRuntime[Port, NotFound])
    assert_type(fallible.run_sync_exit(Port()), fx.Exit[int, NotFound])
    # The plain variants need a layer that cannot fail, as they need E = Never.
    fallible.run_sync(Port())  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


# --- typed Context ------------------------------------------------------------------


def check_context_operations(
    both: fx.Context[Primary | Port], port_ctx: fx.Context[Port], replica: fx.Context[Replica]
) -> None:
    assert_type(both.get(Port), int)
    assert_type(both.get(Primary), Db)
    assert_type(both.get(Level), int)  # a reference is always there
    both.get(Replica)  # pyright: ignore[reportArgumentType]
    assert_type(both.get_unsafe(Replica), Db)
    assert_type(both.get_option(Replica), fx.Option[Db])
    assert_type(both.get_or_else(Replica, lambda: None), Db | None)
    assert_type(both.pipe(fx.Context.pick(Port)), fx.Context[Port])
    both.pipe(fx.Context.pick(Replica))  # pyright: ignore[reportArgumentType]
    assert_type(both.pipe(fx.Context.omit(Port)), fx.Context[Primary])
    assert_type(port_ctx.pipe(fx.Context.omit(Port)), fx.Context[Never])
    assert_type(both.pipe(fx.Context.omit(Port, Primary)), fx.Context[Never])
    assert_type(both.pipe(fx.Context.omit(Replica)), fx.Context[Primary | Port])
    three = both.merge(replica)
    assert_type(three.pipe(fx.Context.omit(Port)), fx.Context[Primary | Replica])
    assert_type(three.pipe(fx.Context.omit(Port, Replica)), fx.Context[Primary])
    assert_type(three.pipe(fx.Context.omit(Port, Primary, Replica)), fx.Context[Never])
    three.pipe(fx.Context.omit(Port)).get(Port)  # pyright: ignore[reportArgumentType]
    assert_type(three.pipe(fx.Context.add_or_omit(Port, None)), fx.Context[Primary | Replica])
    assert_type(both.pipe(fx.Context.add_or_omit(Port, fx.Some(1))), fx.Context[Primary])
    fx.Context.add_or_omit(Port, fx.Some("1"))  # pyright: ignore[reportArgumentType]
    assert_type(fx.Context.merge_all(port_ctx, replica), fx.Context[Port | Replica])
    assert_type(port_ctx.merge(replica), fx.Context[Port | Replica])


def check_context_effects(ctx: fx.Context[Primary | Port]) -> None:
    assert_type(
        fx.context(Port, Primary), fx.Effect[fx.Context[Port | Primary], Never, Port | Primary]
    )
    assert_type(fx.context(), fx.Effect[fx.Context[Never], Never, Never])
    assert_type(fx.service_option(Port), fx.Effect[fx.Option[int]])
    assert_type(lookup("k").pipe(fx.provide_context(ctx)), fx.Effect[str, NotFound | Invalid])
    assert_type(lookup("k").pipe(fx.provide(ctx)), fx.Effect[str, NotFound | Invalid])
    assert_type(
        lookup("k").pipe(fx.provide_context(fx.Context.make(Port, 1))),
        fx.Effect[str, NotFound | Invalid, Primary],
    )
    assert_type(
        lookup("k").pipe(fx.provide_service_effect(Port, fx.fail(Invalid("x")).as_(1))),
        fx.Effect[str, NotFound | Invalid, Primary],
    )
    fx.provide_service_effect(Port, fx.succeed("1"))  # pyright: ignore[reportArgumentType]
    assert_type(fx.succeed(1).update_service(Port, lambda n: n + 1), fx.Effect[int, Never, Port])
    fx.succeed(1).update_service(Port, str)  # pyright: ignore[reportArgumentType]
    assert_type(
        fx.scoped_with(lambda scope: scope.add_finalizer(lambda _: fx.void)), fx.Effect[None]
    )


# --- layer building and combinators ---------------------------------------------------


def check_layer_building(memo: layer.MemoMap, scope: fx.CloseableScope) -> None:
    needs_port = layer.effect(Replica, Port().map(lambda _: GoodDb()))
    assert_type(needs_port.build(), fx.Effect[fx.Context[Replica], Never, Port | fx.Scope])
    assert_type(needs_port.build_with_scope(scope), fx.Effect[fx.Context[Replica], Never, Port])
    assert_type(
        needs_port.build_with_memo_map(memo, scope), fx.Effect[fx.Context[Replica], Never, Port]
    )
    assert_type(needs_port.launch(), fx.Effect[Never, Never, Port])
    assert_type(
        layer.from_build(lambda _m, _s: fx.succeed(fx.Context.make(Port, 1))), layer.Layer[Port]
    )
    assert_type(layer.empty, layer.Layer[Never])
    # Providing nothing removes nothing.
    assert_type(
        lookup("k").pipe(fx.provide(layer.empty)),
        fx.Effect[str, NotFound | Invalid, Primary | Port],
    )


def check_layer_constructors() -> None:
    assert_type(layer.succeed_context(fx.Context.make(Port, 1)), layer.Layer[Port])
    assert_type(layer.sync_context(lambda: fx.Context.make(Port, 1)), layer.Layer[Port])
    assert_type(
        layer.effect_context(Primary().map(lambda _: fx.Context.make(Port, 1))),
        layer.Layer[Port, Never, Primary],
    )
    assert_type(
        layer.effect_discard(fx.acquire_release(fx.fail(NotFound("k")), lambda _a, _e: fx.void)),
        layer.Layer[Never, NotFound],
    )
    assert_type(layer.suspend(lambda: port_live), layer.Layer[Port])
    assert_type(layer.unwrap(Primary().map(lambda _: port_live)), layer.Layer[Port, Never, Primary])
    assert_type(layer.mock(Primary, get=GoodDb().get), layer.Layer[Primary])


def check_layer_combinators() -> None:
    failing = layer.effect(Port, fx.fail(NotFound("k")))
    assert_type(
        failing.tap(lambda ctx: fx.sync(lambda: ctx.get(Port))), layer.Layer[Port, NotFound]
    )
    assert_type(
        failing.tap(lambda _: Primary().and_then(fx.Scope())),
        layer.Layer[Port, NotFound, Primary],
    )
    assert_type(failing.tap_error(lambda e: fx.sync(lambda: e.key)), layer.Layer[Port, NotFound])
    assert_type(
        failing.tap_cause(lambda _: fx.fail(Invalid("x"))), layer.Layer[Port, NotFound | Invalid]
    )
    assert_type(failing.or_die(), layer.Layer[Port])
    assert_type(failing.catch_all(lambda _: port_live), layer.Layer[Port])
    assert_type(failing.catch_cause(lambda _: merged_live), layer.Layer[Port])
    failing.catch_all(lambda _: primary_live)  # pyright: ignore[reportArgumentType]
    assert_type(
        failing.flat_map(lambda ctx: layer.succeed(Primary, GoodDb())),
        layer.Layer[Primary, NotFound],
    )
    assert_type(
        failing.update_service(Primary, lambda db: db), layer.Layer[Port, NotFound, Primary]
    )


def check_layer_catch_tag() -> None:
    two = layer.effect(Port, fx.fail(NotFound("k"))).pipe(
        layer.provide(layer.effect(Primary, fx.fail(Invalid("x"))))
    )
    assert_type(two, layer.Layer[Port, NotFound | Invalid])
    assert_type(
        two.pipe(layer.catch_tag(NotFound, lambda _: port_live)), layer.Layer[Port, Invalid]
    )
    assert_type(
        two.pipe(layer.catch_tag((NotFound, Invalid), lambda _: port_live)), layer.Layer[Port]
    )
    two.pipe(layer.catch_tag(NotFound, lambda _: primary_live))  # pyright: ignore[reportArgumentType]


def check_rc_ref() -> None:
    ref_eff = fx.RcRef.make(fx.acquire_release(fx.succeed(1), lambda _a, _e: fx.void))
    assert_type(ref_eff, fx.Effect[fx.RcRef[int, Never], Never, fx.Scope])
    needing = fx.RcRef.make(Port().flat_map(lambda _: fx.fail(NotFound("k"))), idle_time_to_live=1)
    assert_type(needing, fx.Effect[fx.RcRef[Never, NotFound], Never, fx.Scope | Port])


def check_rc_ref_methods(ref: fx.RcRef[int, NotFound]) -> None:
    assert_type(ref.get(), fx.Effect[int, NotFound, fx.Scope])
    assert_type(ref.invalidate(), fx.Effect[None])


def check_rc_ref_is_covariant(ref: fx.RcRef[bool, Never]) -> fx.RcRef[int, NotFound]:
    return ref  # Effect's RcRef<out A, out E>


def check_resource_variance(
    rc_map: fx.RcMap[str, bool], scoped: fx.ScopedRef[bool], resource: fx.Resource[bool]
) -> None:
    # Effect declares these ``in out``: a value can be put in as well as read.
    widened_map: fx.RcMap[str, int] = rc_map  # pyright: ignore[reportAssignmentType]
    widened_scoped: fx.ScopedRef[int] = scoped  # pyright: ignore[reportAssignmentType]
    widened_resource: fx.Resource[int] = resource  # pyright: ignore[reportAssignmentType]
    del widened_map, widened_scoped, widened_resource


def _lookup_port(key: str) -> fx.Effect[int, NotFound, Port]:
    return Port()


def check_rc_map() -> None:
    assert_type(
        fx.RcMap.make(_lookup_port),
        fx.Effect[fx.RcMap[str, int, NotFound], Never, fx.Scope | Port],
    )
    assert_type(
        fx.RcMap.make(_lookup_port, capacity=2, idle_time_to_live=len),
        fx.Effect[fx.RcMap[str, int, NotFound | fx.ExceededCapacityError], Never, fx.Scope | Port],
    )
    fx.RcMap.make(_lookup_port, idle_time_to_live=lambda key: key)  # pyright: ignore[reportArgumentType, reportCallIssue]


def check_rc_map_methods(rc_map: fx.RcMap[str, int, NotFound]) -> None:
    assert_type(rc_map.get("k"), fx.Effect[int, NotFound, fx.Scope])
    assert_type(rc_map.get_option("k"), fx.Effect[fx.Option[int], NotFound, fx.Scope])
    assert_type(rc_map.keys(), fx.Effect[list[str]])
    assert_type(rc_map.has("k"), fx.Effect[bool])
    assert_type(rc_map.invalidate("k"), fx.Effect[None])
    assert_type(rc_map.touch("k"), fx.Effect[None])
    rc_map.get(1)  # pyright: ignore[reportArgumentType]


def _scoped_port(key: str) -> fx.Effect[int, NotFound, Port | fx.Scope]:
    return _lookup_port(key).flat_map(
        lambda n: fx.acquire_release(fx.succeed(n), lambda _a, _e: fx.void)
    )


def check_cache() -> None:
    assert_type(
        fx.Cache.make(_lookup_port, capacity=2),
        fx.Effect[fx.Cache[str, int, NotFound], Never, Port],
    )
    assert_type(
        fx.Cache.make(_lookup_port, capacity=None, require_services_at="lookup"),
        fx.Effect[fx.Cache[str, int, NotFound, Port]],
    )

    def ttl(ex: fx.Exit[int, NotFound], key: str) -> float:
        return len(key) if isinstance(ex, fx.Success) else 0

    assert_type(
        fx.Cache.make(_lookup_port, capacity=2, time_to_live=ttl),
        fx.Effect[fx.Cache[str, int, NotFound], Never, Port],
    )
    fx.Cache.make(_lookup_port, capacity=2, time_to_live=lambda _ex, key: key)  # pyright: ignore[reportArgumentType, reportCallIssue]


def check_cache_methods(cache: fx.Cache[str, int, NotFound, Port]) -> None:
    assert_type(cache.get("k"), fx.Effect[int, NotFound, Port])
    assert_type(cache.refresh("k"), fx.Effect[int, NotFound, Port])
    assert_type(cache.get_option("k"), fx.Effect[fx.Option[int], NotFound])
    assert_type(cache.get_success("k"), fx.Effect[fx.Option[int]])
    assert_type(cache.set("k", 1), fx.Effect[None])
    assert_type(cache.has("k"), fx.Effect[bool])
    assert_type(cache.invalidate_when("k", lambda n: n > 0), fx.Effect[bool])
    assert_type(cache.invalidate_all(), fx.Effect[None])
    assert_type(cache.size(), fx.Effect[int])
    assert_type(cache.entries(), fx.Effect[list[tuple[str, int]]])
    assert_type(cache.capacity, int | None)
    cache.get(1)  # pyright: ignore[reportArgumentType]
    cache.set("k", "v")  # pyright: ignore[reportArgumentType]


def check_scoped_cache() -> None:
    assert_type(
        fx.ScopedCache.make(_scoped_port, capacity=2),
        fx.Effect[fx.ScopedCache[str, int, NotFound], Never, Port | fx.Scope],
    )
    assert_type(
        fx.ScopedCache.make(_scoped_port, capacity=2, require_services_at="lookup"),
        fx.Effect[fx.ScopedCache[str, int, NotFound, Port], Never, fx.Scope],
    )

    def scoped_length(key: str) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(fx.succeed(len(key)), lambda _a, _e: fx.void)

    scope_only = fx.ScopedCache.make(scoped_length, capacity=2, require_services_at="lookup")
    assert_type(scope_only, fx.Effect[fx.ScopedCache[str, int], Never, fx.Scope])


def check_scoped_cache_methods(cache: fx.ScopedCache[str, int, NotFound, Port]) -> None:
    assert_type(cache.get("k"), fx.Effect[int, NotFound, Port])
    assert_type(cache.get_option("k"), fx.Effect[fx.Option[int], NotFound])
    assert_type(cache.keys(), fx.Effect[list[str]])
    assert_type(cache.values(), fx.Effect[list[int]])
    assert_type(cache.is_closed, bool)
    cache.get(1)  # pyright: ignore[reportArgumentType]


def check_scoped_ref(ref: fx.ScopedRef[int]) -> None:
    assert_type(fx.ScopedRef.make(lambda: 0), fx.Effect[fx.ScopedRef[int], Never, fx.Scope])
    assert_type(
        fx.ScopedRef.from_acquire(
            Port().flat_map(lambda p: fx.acquire_release(fx.succeed(p), lambda _a, _e: fx.void))
        ),
        fx.Effect[fx.ScopedRef[int], Never, fx.Scope | Port],
    )
    assert_type(ref.get(), fx.Effect[int])
    assert_type(ref.set(fx.succeed(1)), fx.Effect[None])
    assert_type(ref.set(fx.acquire_release(fx.succeed(1), lambda _a, _e: fx.void)), fx.Effect[None])
    assert_type(ref.set(Port().and_then(fx.Scope()).as_(1)), fx.Effect[None, Never, Port])
    assert_type(ref.set(fx.fail(NotFound("k"))), fx.Effect[None, NotFound])
    ref.set(fx.succeed("x"))  # pyright: ignore[reportCallIssue, reportArgumentType]


def check_resource() -> None:
    manual = fx.Resource.manual(Port().flat_map(lambda _: fx.fail(NotFound("k"))))
    assert_type(manual, fx.Effect[fx.Resource[Never, NotFound], Never, fx.Scope | Port])
    auto = fx.Resource.auto(fx.succeed(1), schedule.spaced(1))
    assert_type(auto, fx.Effect[fx.Resource[int, Never], Never, fx.Scope])
    # Effect's ``auto`` takes any policy: its requirements flow out, its errors end the
    # refresh fiber.
    needy = schedule.spaced(1).tap(lambda _: Port()).while_effect(lambda _: fx.fail("x"))
    assert_type(
        fx.Resource.auto(Primary().as_(1), needy),
        fx.Effect[fx.Resource[int, Never], Never, fx.Scope | Primary | Port],
    )


def check_resource_methods(resource: fx.Resource[int, NotFound]) -> None:
    assert_type(resource.get(), fx.Effect[int, NotFound])
    assert_type(resource.refresh(), fx.Effect[None, NotFound])


failing_port_live = layer.effect(Port, fx.fail(NotFound("k")).and_then(Primary()).as_(1))


def check_layer_ref() -> None:
    assert_type(
        fx.LayerRef.make(failing_port_live),
        fx.Effect[fx.LayerRef[Port, NotFound], Never, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerRef.make(failing_port_live, preload=True, idle_time_to_live=1),
        fx.Effect[fx.LayerRef[Port, NotFound], NotFound, fx.Scope | Primary],
    )
    needy = schedule.spaced(1).tap(lambda _: Port()).while_effect(lambda _: fx.fail("x"))
    assert_type(
        fx.LayerRef.make(failing_port_live, invalidation_schedule=needy),
        fx.Effect[fx.LayerRef[Port, NotFound], Never, fx.Scope | Primary | Port],
    )
    assert_type(
        fx.LayerRef.make(failing_port_live, preload=True, invalidation_schedule=needy),
        fx.Effect[fx.LayerRef[Port, NotFound], NotFound, fx.Scope | Primary | Port],
    )


def check_layer_ref_methods(ref: fx.LayerRef[Port, NotFound]) -> None:
    assert_type(ref.get(), layer.Layer[Port, NotFound])
    assert_type(ref.context_effect(), fx.Effect[fx.Context[Port], NotFound, fx.Scope])
    assert_type(ref.invalidate(), fx.Effect[None])
    assert_type(ref.refresh(), fx.Effect[None, NotFound])


class PortRef(fx.LayerRefService[Port, NotFound]): ...


def check_layer_ref_service() -> None:
    assert_type(PortRef.layer(failing_port_live), layer.Layer[PortRef, Never, Primary])
    assert_type(
        PortRef.layer(failing_port_live, preload=True), layer.Layer[PortRef, NotFound, Primary]
    )
    assert_type(PortRef.get(), layer.Layer[Port, NotFound, PortRef])
    assert_type(PortRef.context_effect(), fx.Effect[fx.Context[Port], NotFound, fx.Scope | PortRef])
    assert_type(PortRef.invalidate(), fx.Effect[None, Never, PortRef])
    assert_type(PortRef.refresh(), fx.Effect[None, NotFound, PortRef])
    PortRef.layer(primary_live)  # pyright: ignore[reportArgumentType]


def _port_layer(key: str) -> layer.Layer[Port, NotFound, Primary]:
    return failing_port_live


def check_layer_map() -> None:
    assert_type(
        fx.LayerMap.make(_port_layer),
        fx.Effect[fx.LayerMap[str, Port, NotFound], Never, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerMap.make(_port_layer, preload_keys=["a"], idle_time_to_live=1),
        fx.Effect[fx.LayerMap[str, Port, NotFound], NotFound, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerMap.from_record({"a": failing_port_live}),
        fx.Effect[fx.LayerMap[str, Port, NotFound], Never, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerMap.from_record({"a": failing_port_live}, preload=True),
        fx.Effect[fx.LayerMap[str, Port, NotFound], NotFound, fx.Scope | Primary],
    )


def check_layer_map_methods(layer_map: fx.LayerMap[str, Port, NotFound]) -> None:
    assert_type(layer_map.get("a"), layer.Layer[Port, NotFound])
    assert_type(layer_map.context_effect("a"), fx.Effect[fx.Context[Port], NotFound, fx.Scope])
    assert_type(
        layer_map.context_effect_option("a"),
        fx.Effect[fx.Option[fx.Context[Port]], NotFound, fx.Scope],
    )
    assert_type(layer_map.invalidate("a"), fx.Effect[None])


class PortMap(fx.LayerMapService[str, Port, NotFound]): ...


def check_layer_map_service() -> None:
    assert_type(PortMap.layer(_port_layer), layer.Layer[PortMap, Never, Primary])
    assert_type(
        PortMap.layer(_port_layer, preload_keys=["a"]), layer.Layer[PortMap, NotFound, Primary]
    )
    assert_type(
        PortMap.layer_from_record({"a": failing_port_live}, preload=True),
        layer.Layer[PortMap, NotFound, Primary],
    )
    assert_type(PortMap.get("a"), layer.Layer[Port, NotFound, PortMap])
    assert_type(
        PortMap.context_effect("a"), fx.Effect[fx.Context[Port], NotFound, fx.Scope | PortMap]
    )
    assert_type(
        PortMap.context_effect_option("a"),
        fx.Effect[fx.Option[fx.Context[Port]], NotFound, fx.Scope | PortMap],
    )
    assert_type(PortMap.invalidate("a"), fx.Effect[None, Never, PortMap])
    PortMap.get(1)  # pyright: ignore[reportArgumentType]


def check_random() -> None:
    assert_type(fx.random.next(), fx.Effect[float])
    assert_type(fx.random.next_int_between(1, 6, half_open=True), fx.Effect[int])
    assert_type(fx.random.shuffle("abc"), fx.Effect[list[str]])
    # A non-empty tuple can't be empty; any other iterable can.
    assert_type(fx.random.choice((1, 2, 3)), fx.Effect[int])
    assert_type(fx.random.choice([1, 2, 3]), fx.Effect[int, fx.NoSuchElementException])
    assert_type(fx.random.choice(()), fx.Effect[Never, fx.NoSuchElementException])
    # with_seed keeps the effect's type.
    assert_type(
        lookup("k").pipe(fx.random.with_seed("seed")),
        fx.Effect[str, Invalid | NotFound, Port | Primary],
    )
    fx.provide_service(fx.Random, object())  # pyright: ignore[reportArgumentType]
    fx.random.with_seed(b"seed")  # pyright: ignore[reportArgumentType]


def check_clock() -> None:
    assert_type(fx.clock.now_nanos(), fx.Effect[int])
    assert_type(fx.clock.monotonic_nanos(), fx.Effect[int])
    assert_type(fx.clock.clock_with(lambda c: fx.succeed(c.now_nanos_unsafe())), fx.Effect[int])

    class SecondsOnly:
        def now_unsafe(self) -> float:
            return 0.0

        def monotonic_unsafe(self) -> float:
            return 0.0

        def sleep(self, seconds: Seconds) -> fx.Effect[None]:
            return fx.void

    # A clock must also give whole nanoseconds.
    fx.provide_service(fx.Clock, SecondsOnly())  # pyright: ignore[reportArgumentType]


def check_date_time() -> None:
    import calendar
    from datetime import datetime, tzinfo

    from pyfect import date_time
    from pyfect.date_time import CurrentTimeZone

    assert_type(date_time.now(), fx.Effect[datetime])
    assert_type(date_time.is_future(datetime.now()), fx.Effect[bool])
    assert_type(date_time.now_in_current_zone(), fx.Effect[datetime, Never, CurrentTimeZone])
    # The providers remove CurrentTimeZone; a named zone may not exist.
    assert_type(
        date_time.now_in_current_zone().pipe(date_time.with_current_zone_offset(3600)),
        fx.Effect[datetime],
    )
    assert_type(
        lookup("k")
        .pipe(lambda e: e.zip(date_time.now_in_current_zone()))
        .pipe(date_time.with_current_zone_named("Europe/London")),
        fx.Effect[
            tuple[str, datetime], Invalid | NotFound | fx.IllegalArgumentError, Port | Primary
        ],
    )
    assert_type(
        date_time.layer_current_zone_named("UTC"),
        fx.Layer[CurrentTimeZone, fx.IllegalArgumentError],
    )
    assert_type(date_time.zone_from_string("+05:30"), tzinfo | None)
    # Only "reject" can fail to resolve a wall-clock time.
    wall = datetime(2025, 3, 9, 2, 30)
    zone = date_time.zone_local()
    assert_type(date_time.make_zoned(wall, zone), datetime)
    assert_type(date_time.make_zoned(wall, zone, disambiguation="later"), datetime)
    assert_type(date_time.make_zoned(wall, zone, disambiguation="reject"), datetime | None)
    # Calendar units are whole; weeks start on a calendar.Day.
    date_time.add(datetime.now(), days=1.5)  # pyright: ignore[reportArgumentType]
    date_time.start_of(datetime.now(), "week", week_starts_on=calendar.MONDAY)
    date_time.start_of(datetime.now(), "week", week_starts_on=1)  # pyright: ignore[reportArgumentType]
    date_time.end_of(datetime.now(), "fortnight")  # pyright: ignore[reportArgumentType]


def check_cron() -> None:
    from collections.abc import Iterator
    from datetime import datetime

    from pyfect import cron
    from pyfect.cron import Cron, CronParseError
    from pyfect.result import Result

    assert_type(cron.parse("0 9 * * MON"), Result[Cron, CronParseError])
    assert_type(cron.parse_unsafe("0 9 * * MON", "Europe/Berlin"), Cron)
    c = cron.make(minutes=[0], hours=[9], days=[], months=[], weekdays=[1])
    assert_type(cron.next(c), datetime)
    assert_type(cron.prev(c, datetime.now()), datetime)
    assert_type(cron.sequence(c), Iterator[datetime])
    assert_type(cron.match(c, datetime.now()), bool)
    assert_type(cron.format(c, include_seconds=True), str)
    # A cron is immutable.
    c.minutes = frozenset()  # pyright: ignore[reportAttributeAccessIssue]
    # Parsing can fail, so the schedule carries CronParseError.
    assert_type(schedule.cron("*/5 * * * *"), schedule.Schedule[Seconds, object, CronParseError])
    assert_type(schedule.cron(c), schedule.Schedule[Seconds, object, CronParseError])
    # A Cron carries its own zone, so a zone next to one is rejected (Effect's overloads).
    schedule.cron(c, "UTC")  # pyright: ignore[reportArgumentType]


def check_pool() -> None:
    sized = fx.Pool.make(fx.acquire_release(fx.succeed(1), lambda _a, _e: fx.void), size=2)
    assert_type(sized, fx.Effect[fx.Pool[int, Never], Never, fx.Scope])
    failing = fx.Pool.make_with_ttl(
        Port().flat_map(lambda _: fx.fail(NotFound("k"))).as_("conn"),
        min=0,
        max=4,
        time_to_live=60,
        time_to_live_strategy="creation",
    )
    assert_type(failing, fx.Effect[fx.Pool[str, NotFound], Never, fx.Scope | Port])
    fx.Pool.make_with_ttl(
        fx.succeed(1),
        min=0,
        max=1,
        time_to_live=1,
        time_to_live_strategy="idle",  # pyright: ignore[reportArgumentType, reportCallIssue]
    )


def check_pool_methods(pool: fx.Pool[str, NotFound]) -> None:
    assert_type(pool.get(), fx.Effect[str, NotFound, fx.Scope])
    assert_type(pool.use(lambda s: fx.succeed(len(s))), fx.Effect[int, NotFound])
    assert_type(
        pool.use(lambda _: Port().flat_map(lambda _: fx.fail(Invalid("r")))),
        fx.Effect[Never, NotFound | Invalid, Port],
    )
    assert_type(pool.invalidate("conn"), fx.Effect[None])
    assert_type(pool.reserve("conn"), fx.Effect[None, Never, fx.Scope])
    pool.invalidate(1)  # pyright: ignore[reportArgumentType]


def check_pool_is_invariant(pool: fx.Pool[bool, Never]) -> None:
    # Effect declares Pool<in out A, in out E>: items go back in.
    widened: fx.Pool[int, NotFound] = pool  # pyright: ignore[reportAssignmentType]
    del widened


# --- request batching -----------------------------------------------------------


@dataclass(frozen=True)
class GetUser(fx.Request[str, NotFound]):
    id: int


@dataclass(frozen=True)
class GetIds(fx.Request[list[int], Never, Port]):
    pass


def _users(entries: Sequence[Entry[GetUser]]) -> fx.Effect[None, Invalid]:
    return fx.void


def _both(entries: Sequence[Entry[GetUser | GetIds]]) -> fx.Effect[None]:
    for entry in entries:
        # A union's entries take either request's outcome.
        entry.complete_unsafe(fx.Success("x"))
        entry.complete_unsafe(fx.Success([1]))
    return fx.void


def check_request() -> None:
    users = fx.RequestResolver(_users)
    assert_type(users, fx.RequestResolver[GetUser, Invalid])
    # The run's errors join the request's.
    assert_type(fx.request(GetUser(1), users), fx.Effect[str, NotFound | Invalid])
    assert_type(fx.request(GetUser(1), fx.succeed(users)), fx.Effect[str, NotFound | Invalid])
    both = fx.RequestResolver(_both)
    assert_type(fx.request(GetIds(), both), fx.Effect[list[int], Never, Port])
    assert_type(fx.request(GetUser(1), both), fx.Effect[str, NotFound])
    fx.request(GetIds(), users)  # pyright: ignore[reportCallIssue, reportArgumentType]


def check_entry(entry: Entry[GetUser]) -> None:
    assert_type(entry.request, GetUser)
    assert_type(entry.complete(fx.Success("ok")), fx.Effect[None])
    assert_type(entry.complete_effect(Port().as_("ok")), fx.Effect[None, Never, Port])
    assert_type(entry.fail(NotFound("k")), fx.Effect[None])
    entry.complete_unsafe(fx.Success(1))  # pyright: ignore[reportArgumentType]
    entry.succeed(1)  # pyright: ignore[reportArgumentType]
    entry.fail(Invalid("r"))  # pyright: ignore[reportArgumentType]


def check_resolver_constructors() -> None:
    # Named, the request type reaches a lambda's parameters (Effect's ``make<GetUser>``).
    named = fx.RequestResolver[GetUser](lambda entries: entries[0].succeed("a"))
    assert_type(named, fx.RequestResolver[GetUser])
    assert_type(
        fx.RequestResolver[GetUser].from_effect(lambda e: fx.succeed(str(e.request.id))),
        fx.RequestResolver[GetUser],
    )

    def lookup(entry: Entry[GetUser]) -> fx.Effect[str, Invalid]:
        return fx.succeed("a")

    assert_type(fx.RequestResolver.from_effect(lookup), fx.RequestResolver[GetUser, Invalid])
    assert_type(
        fx.RequestResolver[GetUser].from_function(lambda e: str(e.request.id)),
        fx.RequestResolver[GetUser],
    )
    assert_type(
        fx.RequestResolver[GetUser].make_grouped(
            key=lambda e: e.request.id % 2, resolver=lambda _entries, key: fx.succeed(None)
        ),
        fx.RequestResolver[GetUser],
    )
    assert_type(
        fx.RequestResolver.from_effect_tagged({GetUser: lambda es: fx.succeed(["a"] * len(es))}),
        fx.RequestResolver[GetUser],
    )
    assert_type(fx.RequestResolver.never(), fx.RequestResolver[object])
    fx.RequestResolver[GetIds].from_effect(lookup)  # pyright: ignore[reportArgumentType]


def check_resolver_combinators(users: fx.RequestResolver[GetUser, Invalid]) -> None:
    assert_type(users.batch_n(10), fx.RequestResolver[GetUser, Invalid])
    assert_type(users.grouped(lambda e: e.request.id), fx.RequestResolver[GetUser, Invalid])
    assert_type(users.set_delay(0.01), fx.RequestResolver[GetUser, Invalid])
    assert_type(
        users.around(lambda _: fx.succeed(1), lambda _es, n: fx.fail(NotFound(str(n)))),
        fx.RequestResolver[GetUser, Invalid | NotFound],
    )
    other = fx.RequestResolver[GetUser](lambda _: fx.void)
    assert_type(users.race(other), fx.RequestResolver[GetUser, Invalid])
    assert_type(users.with_cache(capacity=10), fx.Effect[fx.RequestResolver[GetUser, Invalid]])
    users.with_cache(capacity=10, strategy="random")  # pyright: ignore[reportArgumentType]


def check_resolver_is_contravariant(
    both: fx.RequestResolver[GetUser | GetIds], users: fx.RequestResolver[GetUser]
) -> None:
    # A resolver of more requests stands in for one of fewer.
    narrowed: fx.RequestResolver[GetUser] = both
    widened: fx.RequestResolver[GetUser | GetIds] = users  # pyright: ignore[reportAssignmentType]
    del narrowed, widened


# --- logging -------------------------------------------------------------------


def check_log_effects(eff: fx.Effect[int, NotFound, Primary]) -> None:
    assert_type(fx.log("a", 1), fx.Effect[None])
    assert_type(fx.log_with_level(fx.LogLevel.DEBUG, "a"), fx.Effect[None])
    assert_type(fx.log_warning(fx.cause.fail("x")), fx.Effect[None])
    assert_type(fx.annotate_logs_scoped("k", 1), fx.Effect[None, Never, fx.Scope])
    assert_type(fx.annotate_logs_scoped({"k": 1}), fx.Effect[None, Never, fx.Scope])
    assert_type(eff.annotate_logs("k", 1), fx.Effect[int, NotFound, Primary])
    assert_type(eff.annotate_logs({"k": 1}), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_log_span("db"), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_logger(logger.format_json), fx.Effect[int, NotFound, Primary])
    assert_type(eff.ignore(log=True), fx.Effect[None, Never, Primary])
    assert_type(
        eff.ignore_cause(log=fx.LogLevel.ERROR, message="m"), fx.Effect[None, Never, Primary]
    )
    assert_type(fx.LogLevel.INFO.is_enabled(), fx.Effect[bool])
    # ALL and NONE are thresholds, not levels to log at.
    fx.log_with_level(fx.LogLevel.NONE, "x")  # pyright: ignore[reportArgumentType]
    eff.ignore(log=fx.LogLevel.ALL)  # pyright: ignore[reportArgumentType]


def check_log_references() -> None:
    assert_type(fx.MinimumLogLevel(), TagEffect[fx.LogLevel, Never, fx.MinimumLogLevel])
    assert_type(fx.CurrentLogLevel(), TagEffect[logger.Severity, Never, fx.CurrentLogLevel])
    fx.log("x").pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ALL))
    fx.log("x").pipe(fx.provide_service(fx.CurrentLogLevel, fx.LogLevel.NONE))  # pyright: ignore[reportArgumentType]


def check_loggers() -> None:
    assert_type(fx.Logger.make(lambda o: len(o.message)), fx.Logger[int])
    assert_type(logger.format_simple, fx.Logger[str])
    assert_type(logger.format_structured, fx.Logger[logger.StructuredLog])
    assert_type(logger.format_json.map(len), fx.Logger[int])
    assert_type(logger.format_logfmt.with_console_log(), fx.Logger[None])
    assert_type(logger.console_pretty(colors=False), fx.Logger[None])
    assert_type(logger.to_logging("app"), fx.Logger[None])
    batched = logger.format_json.batched(window=1.0, flush=lambda lines: fx.log(len(lines)))
    assert_type(batched, fx.Effect[fx.Logger[None], Never, fx.Scope])
    # Outputs are covariant: any logger is a Logger[object].
    loggers: list[fx.Logger[object]] = [logger.format_json, logger.format_structured]
    assert_type(loggers, list[fx.Logger[object]])


def check_logger_layer(make: fx.Effect[fx.Logger[str], NotFound, Primary]) -> None:
    assert_type(logger.layer([logger.default_logger]), layer.Layer[Never])
    batched = logger.format_json.batched(window=1.0, flush=lambda _: fx.void)
    assert_type(logger.layer([logger.format_json, batched]), layer.Layer[Never])
    assert_type(
        logger.layer([make], merge_with_existing=True), layer.Layer[Never, NotFound, Primary]
    )


def check_console(eff: fx.Effect[int, NotFound, Primary]) -> None:
    assert_type(fx.console.log("a", 1), fx.Effect[None])
    assert_type(fx.console.clear, fx.Effect[None])
    assert_type(fx.console.group(label="g"), fx.Effect[None, Never, fx.Scope])
    assert_type(fx.console.time(), fx.Effect[None, Never, fx.Scope])
    assert_type(fx.console.with_group(eff, label="g"), fx.Effect[int, NotFound, Primary])
    assert_type(fx.console.with_time(eff, "t"), fx.Effect[int, NotFound, Primary])
    assert_type(fx.console.console_with(fx.succeed), fx.Effect[fx.console.Console])
    assert_type(fx.testing.log_lines, fx.Effect[list[object]])
    assert_type(fx.testing.test_console(), fx.Effect[fx.testing.TestConsole])
    assert_type(fx.testing.TestConsole.layer(), layer.Layer[Never])
    # A TestConsole is a Console; a partial console is not.
    fx.void.pipe(fx.provide_service(fx.console.CurrentConsole, fx.testing.TestConsole()))
    fx.void.pipe(fx.provide_service(fx.console.CurrentConsole, object()))  # pyright: ignore[reportArgumentType]


# --- error reporting -----------------------------------------------------------


def check_error_reporting(
    eff: fx.Effect[int, NotFound, Primary],
    make: fx.Effect[fx.ErrorReporter, NotFound, Primary],
) -> None:
    assert_type(eff.with_error_reporting(), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_error_reporting(defects_only=True), fx.Effect[int, NotFound, Primary])
    reporter = fx.error_reporter.make(lambda report: None)
    assert_type(reporter, fx.ErrorReporter)
    assert_type(fx.error_reporter.report(fx.cause.fail(1)), fx.Effect[None])
    assert_type(fx.error_reporter.layer([reporter]), layer.Layer[Never])
    assert_type(
        fx.error_reporter.layer([reporter, make], merge_with_existing=True),
        layer.Layer[Never, NotFound, Primary],
    )
    fx.error_reporter.make(lambda report: assert_type(report.severity, fx.logger.Severity))
    fx.error_reporter.layer([fx.succeed(1)])  # pyright: ignore[reportCallIssue, reportArgumentType]


# --- tracing -------------------------------------------------------------------


def check_span_effects(eff: fx.Effect[int, NotFound, Primary]) -> None:
    from pyfect.tracer import AnySpan, ExternalSpan, Span, SpanLink

    parent = ExternalSpan(span_id="s", trace_id="t")
    # Spans add nothing to E or R: ParentSpan is a Reference.
    assert_type(
        eff.with_span("a", kind="client", attributes={"k": 1}), fx.Effect[int, NotFound, Primary]
    )
    assert_type(eff.with_span("a", parent=parent, root=True), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_span_scoped("a"), fx.Effect[int, NotFound, Primary | fx.Scope])
    assert_type(eff.with_parent_span(parent), fx.Effect[int, NotFound, Primary])
    assert_type(eff.annotate_spans("k", 1), fx.Effect[int, NotFound, Primary])
    assert_type(eff.annotate_spans({"k": 1}), fx.Effect[int, NotFound, Primary])
    assert_type(eff.link_spans(parent, attributes={"r": 1}), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_tracer(fx.tracer.native_tracer), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_tracer_enabled(False), fx.Effect[int, NotFound, Primary])
    assert_type(eff.with_tracer_timing(False), fx.Effect[int, NotFound, Primary])
    assert_type(fx.make_span("a"), fx.Effect[Span])
    assert_type(fx.make_span_scoped("a"), fx.Effect[Span, Never, fx.Scope])
    assert_type(fx.use_span("a", lambda _span: eff), fx.Effect[int, NotFound, Primary])
    assert_type(fx.current_span(), fx.Effect[Span, fx.NoSuchElementException])
    assert_type(fx.current_parent_span(), fx.Effect[AnySpan, fx.NoSuchElementException])
    assert_type(fx.annotate_current_span("k", 1), fx.Effect[None])
    assert_type(fx.tracer.ParentSpan(), TagEffect[AnySpan | None, Never, fx.tracer.ParentSpan])
    assert_type(SpanLink(parent).span, AnySpan)
    eff.with_span("a", kind="sideways")  # pyright: ignore[reportArgumentType]
    eff.with_span("a", colour="red")  # pyright: ignore[reportCallIssue]


def check_stack_frames(eff: fx.Effect[int, NotFound, Primary], c: fx.Cause[NotFound]) -> None:
    from pyfect.cause import Fail, reason_annotations
    from pyfect.tracer import CurrentStackFrame, ExternalSpan, StackFrame, StackTrace

    # capture_stack_trace is a with_span / with_span_scoped / with_parent_span
    # option; it changes nothing in the type.
    assert_type(eff.with_span("a", capture_stack_trace=False), fx.Effect[int, NotFound, Primary])
    assert_type(
        eff.with_span_scoped("a", capture_stack_trace=lambda: "at f (x.py:1)"),
        fx.Effect[int, NotFound, Primary | fx.Scope],
    )
    assert_type(
        eff.with_parent_span(ExternalSpan("s", "t"), capture_stack_trace=False),
        fx.Effect[int, NotFound, Primary],
    )
    assert_type(CurrentStackFrame(), TagEffect[StackFrame | None, Never, CurrentStackFrame])
    assert_type(
        c.annotate(fx.Context.make(StackTrace, StackFrame("f", lambda: None))), fx.Cause[NotFound]
    )
    assert_type(c.annotations, fx.Context)
    assert_type(Fail(NotFound("u")).annotate(fx.Context.empty()), Fail[NotFound])
    assert_type(reason_annotations(c.reasons[0]), fx.Context)
    # Spans that run no effect inside take no stack frame option.
    fx.make_span("a", capture_stack_trace=False)  # pyright: ignore[reportCallIssue]
    fx.use_span("a", lambda _span: eff, capture_stack_trace=False)  # pyright: ignore[reportCallIssue]
    eff.with_span("a", capture_stack_trace="here")  # pyright: ignore[reportArgumentType]
    # A frame's location is read lazily: a plain string is not one.
    StackFrame("f", "at f (x.py:1)")  # pyright: ignore[reportArgumentType]


def check_traced_fn() -> None:
    @fx.fn("find", kind="server")
    def find(user_id: str):
        db = yield from Primary()
        value = db.get(user_id)
        if value is None:
            return (yield from NotFound(user_id))
        return value

    # The span changes nothing in the function's type.
    assert_type(find("u"), fx.Effect[str, NotFound, Primary])
    find(1)  # pyright: ignore[reportArgumentType]
    fx.fn("find", kind="sideways")  # pyright: ignore[reportArgumentType]

    # Effect.fn("name")'s body may return an effect instead of yielding.
    @fx.fn("lookup")
    def lookup(user_id: str) -> fx.Effect[str, NotFound, Primary]:
        return find(user_id)

    assert_type(lookup("u"), fx.Effect[str, NotFound, Primary])
    lookup(1)  # pyright: ignore[reportArgumentType]


def check_fn_pipeables() -> None:
    def find(user_id: str):
        db = yield from Primary()
        value = db.get(user_id)
        if value is None:
            return (yield from NotFound(user_id))
        return value

    # Each pipeable sees the previous result; one taking more parameters
    # also gets the call's arguments.
    def tagged(
        eff: fx.Effect[str, NotFound, Primary], user_id: str
    ) -> fx.Effect[str, NotFound, Primary]:
        return eff.map(lambda v: f"{user_id}={v}")

    untraced = fx.fn_untraced(find, lambda eff: eff.map(len), lambda eff: eff.map(str))
    assert_type(untraced("u"), fx.Effect[str, NotFound, Primary])
    assert_type(fx.fn(find, tagged)("u"), fx.Effect[str, NotFound, Primary])
    caught = fx.fn("find")(find, fx.catch_tag(NotFound, lambda _: fx.succeed("none")))
    assert_type(caught("u"), fx.Effect[str, Never, Primary])
    assert_type(fx.fn("count")(find, lambda _eff: 3)("u"), int)

    # A pipeable's arguments must be the call's.
    def wrong(eff: fx.Effect[str, NotFound, Primary], user_id: int) -> int:
        return user_id

    fx.fn(find, wrong)  # pyright: ignore[reportArgumentType]
    # A pipeable must take what the one before gave.
    fx.fn_untraced(find, lambda eff: eff.map(len), tagged)  # pyright: ignore[reportArgumentType]
    fx.fn("find", find)  # pyright: ignore[reportArgumentType]


def check_scope_use(
    needs_scope: fx.Effect[int, NotFound, fx.Scope | Primary], scope: fx.CloseableScope
) -> None:
    assert_type(fx.scope.make(), fx.Effect[fx.CloseableScope])
    assert_type(needs_scope.pipe(fx.scope.provide(scope)), fx.Effect[int, NotFound, Primary])
    assert_type(needs_scope.pipe(fx.scope.use(scope)), fx.Effect[int, NotFound, Primary])
    assert_type(fx.succeed(1).pipe(fx.scope.use(scope)), fx.Effect[int])
    assert_type(scope.fork_unsafe("parallel"), fx.CloseableScope)
    fx.scope.use(fx.Scope)  # pyright: ignore[reportArgumentType]
    fx.scope.make("concurrent")  # pyright: ignore[reportArgumentType]


def check_should_yield() -> None:
    from pyfect.scheduler import ShouldYield

    def every_four(_fiber: fx.Fiber[Any, Any], ops: int) -> bool:
        return ops >= 4

    assert_type(fx.void.pipe(fx.provide_service(ShouldYield, every_four)), fx.Effect[None])
    fx.provide_service(ShouldYield, lambda _fiber: True)  # pyright: ignore[reportArgumentType]


def check_runtime_error_attributes(ctx: fx.Context[Primary]) -> None:
    from pyfect.run import get_error_exit_code, get_error_reported

    assert_type(get_error_exit_code(ValueError()), int)
    assert_type(get_error_reported("anything"), bool)
    assert_type(ctx.get_or_none(Primary), Db | None)


def check_layer_spans(built: layer.Layer[Primary, NotFound, Replica]) -> None:
    from pyfect.tracer import ExternalSpan, ParentSpan

    assert_type(layer.span("a"), layer.Layer[ParentSpan])
    assert_type(layer.parent_span(ExternalSpan("s", "t")), layer.Layer[ParentSpan])
    assert_type(built.with_span("a"), layer.Layer[Primary, NotFound, Replica])
    assert_type(
        built.with_span("a", capture_stack_trace=False), layer.Layer[Primary, NotFound, Replica]
    )
    assert_type(
        built.with_parent_span(ExternalSpan("s", "t")), layer.Layer[Primary, NotFound, Replica]
    )


# --- metrics -------------------------------------------------------------------


def check_metric_constructors() -> None:
    from datetime import timedelta

    from pyfect import metric

    assert_type(metric.counter("c"), metric.Metric[float, metric.CounterState[float]])
    assert_type(metric.counter("c", bigint=True), metric.Metric[int, metric.CounterState[int]])
    assert_type(metric.gauge("g"), metric.Metric[float, metric.GaugeState[float]])
    assert_type(metric.gauge("g", bigint=True), metric.Metric[int, metric.GaugeState[int]])
    assert_type(metric.frequency("f"), metric.Metric[str, metric.FrequencyState])
    assert_type(
        metric.histogram("h", boundaries=[1, 2]), metric.Metric[float, metric.HistogramState]
    )
    assert_type(
        metric.summary("s", max_age=1, max_size=1, quantiles=[0.5]),
        metric.Metric[float, metric.SummaryState],
    )
    assert_type(
        metric.summary_with_timestamp("s", max_age=1, max_size=1, quantiles=[0.5]),
        metric.Metric[tuple[float, float], metric.SummaryState],
    )
    assert_type(metric.timer("t"), metric.Metric[float | timedelta, metric.HistogramState])
    assert_type(metric.linear_boundaries(start=0, width=1, count=3), tuple[float, ...])
    metric.counter("c", attributes={"k": 1})  # pyright: ignore[reportArgumentType]
    metric.histogram("h")  # pyright: ignore[reportCallIssue]


def check_metric_methods() -> None:
    from pyfect import metric

    counter = metric.counter("c")
    assert_type(counter.update(1), fx.Effect[None])
    assert_type(counter.modify(1.5), fx.Effect[None])
    assert_type(counter.value(), fx.Effect[metric.CounterState[float]])
    assert_type(counter.remove(), fx.Effect[None])
    assert_type(counter.map_input(len), metric.Metric[Sized, metric.CounterState[float]])
    assert_type(counter.with_constant_input(1), metric.Metric[object, metric.CounterState[float]])
    assert_type(
        counter.with_attributes({"k": "v"}), metric.Metric[float, metric.CounterState[float]]
    )
    assert_type(metric.snapshot, fx.Effect[list[metric.Snapshot]])
    assert_type(metric.dump, fx.Effect[str])
    assert_type(metric.prometheus_format(prefix="app"), fx.Effect[str])
    # An int counter takes no floats; a frequency takes only strings.
    metric.counter("c", bigint=True).update(1.5)  # pyright: ignore[reportArgumentType]
    metric.frequency("f").update(1)  # pyright: ignore[reportArgumentType]
    # Metrics are contravariant in their input and covariant in their state.
    _floats: metric.Metric[int, metric.CounterState[float]] = counter
    _ints: metric.Metric[float, object] = metric.counter("c", bigint=True)  # pyright: ignore[reportAssignmentType]


def check_track_methods(eff: fx.Effect[int, NotFound, Primary]) -> None:
    from pyfect import metric

    counter = metric.counter("c")
    errors = metric.frequency("errors")
    assert_type(eff.track(counter.with_constant_input(1)), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track(errors, lambda ex: type(ex).__name__), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_successes(counter), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_errors(errors, lambda e: e.key), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_defects(errors, repr), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_duration(metric.timer("t")), fx.Effect[int, NotFound, Primary])
    assert_type(eff.track_duration(counter, lambda d: d * 2), fx.Effect[int, NotFound, Primary])
    # A metric must take what it is given.
    eff.track_successes(errors)  # pyright: ignore[reportArgumentType]
    eff.track_errors(counter)  # pyright: ignore[reportArgumentType]
    eff.track(counter)  # pyright: ignore[reportArgumentType]


def check_runtime_metrics(eff: fx.Effect[int, NotFound, Primary]) -> None:
    from pyfect import metric

    assert_type(metric.enable_runtime_metrics(eff), fx.Effect[int, NotFound, Primary])
    assert_type(eff.pipe(metric.disable_runtime_metrics), fx.Effect[int, NotFound, Primary])
    assert_type(metric.enable_runtime_metrics_layer, layer.Layer[metric.FiberRuntimeMetrics])


# --- OpenTelemetry bridge ------------------------------------------------------


def check_otel_layers(
    config: fx.Effect[otel.sdk.Configuration, NotFound, Primary],
    eff: fx.Effect[int, NotFound, Primary],
    span_context: SpanContext,
) -> None:
    assert_type(
        otel.tracer.layer,
        layer.Layer[otel.tracer.OtelTracer, Never, otel.tracer.OtelTracerProvider],
    )
    assert_type(otel.tracer.layer_global, layer.Layer[otel.tracer.OtelTracer])
    assert_type(otel.sdk.layer(otel.sdk.Configuration()), layer.Layer[otel.resource.OtelResource])
    assert_type(otel.sdk.layer(config), layer.Layer[otel.resource.OtelResource, NotFound, Primary])
    assert_type(
        otel.metrics.layer(lambda: ()), layer.Layer[Never, Never, otel.resource.OtelResource]
    )
    assert_type(otel.logger.layer(), layer.Layer[Never, Never, otel.logger.OtelLoggerProvider])
    assert_type(
        otel.tracer.current_otel_span(),
        fx.Effect[OtelApiSpan, fx.NoSuchElementException],
    )
    assert_type(
        eff.pipe(otel.tracer.with_span_context(span_context)), fx.Effect[int, NotFound, Primary]
    )
    # An effect still needing the tracer provider cannot run.
    fx.run_sync(otel.tracer.current_otel_span().or_die().pipe(fx.provide(otel.tracer.layer)))  # pyright: ignore[reportArgumentType]


# --- channels, pulls and takes ---------------------------------------------------

type _Ch[O, E = Never, D = None, I = object, IE = object, ID = object, R = Never] = (
    fx.channel.Channel[O, E, D, I, IE, ID, R]
)


def check_channel_constructors(eff: fx.Effect[int, NotFound, Primary]) -> None:
    ch = fx.channel
    assert_type(ch.succeed(1), _Ch[int])
    assert_type(ch.sync(lambda: "a"), _Ch[str])
    assert_type(ch.end(1), _Ch[Never, Never, int])
    assert_type(ch.end_sync(lambda: 1), _Ch[Never, Never, int])
    assert_type(ch.empty, _Ch[Never])
    assert_type(ch.never, _Ch[Never, Never, Never])
    assert_type(ch.fail(NotFound("k")), _Ch[Never, NotFound, Never])
    assert_type(ch.die(RuntimeError()), _Ch[Never, Never, Never])
    assert_type(ch.from_effect(eff), _Ch[int, NotFound, None, object, object, object, Primary])
    assert_type(
        ch.from_effect_done(eff), _Ch[Never, NotFound, int, object, object, object, Primary]
    )
    assert_type(ch.from_iterable([1, 2]), _Ch[int])
    assert_type(ch.from_iterable_array([1, 2], 2), _Ch[tuple[int, ...]])
    assert_type(ch.from_iterator(lambda: iter("ab")), _Ch[str])


def _generator() -> Generator[int, None, str]:
    yield 1
    return "done"


def check_channel_generators() -> None:
    assert_type(fx.channel.from_iterable(_generator()), _Ch[int, Never, str])
    assert_type(fx.channel.from_iterator(_generator), _Ch[int, Never, str])
    assert_type(fx.channel.from_iterator_array(_generator), _Ch[tuple[int, ...], Never, str])


def check_channel_from_pull(
    p: fx.Effect[fx.Pull[int, NotFound, str, Primary], ValueError, Replica],
    ends: fx.Effect[int, fx.Done[str]],
) -> None:
    assert_type(
        fx.channel.from_pull(p),
        _Ch[int, NotFound | ValueError, str, object, object, object, Primary | Replica],
    )
    assert_type(fx.channel.from_pull(fx.succeed(ends)), _Ch[int, Never, str])
    assert_type(fx.channel.from_pull(fx.succeed(fx.succeed(1))), _Ch[int, Never, Never])


def _transform(
    up: fx.Pull[int, ValueError, str], scope: fx.CloseableScope
) -> fx.Effect[fx.Pull[str, NotFound], KeyError, Primary]: ...


def _plain_transform(up: fx.Pull[int], scope: fx.CloseableScope) -> fx.Effect[fx.Pull[str]]: ...


def check_from_transform() -> None:
    assert_type(
        fx.channel.from_transform(_transform),
        _Ch[str, NotFound | KeyError, None, int, ValueError, str, Primary],
    )
    assert_type(
        fx.channel.from_transform(_plain_transform), _Ch[str, Never, None, int, Never, None]
    )


def check_channel_methods(
    source: _Ch[int, ValueError, str, object, object, object, Replica],
    other: _Ch[bytes, KeyError, float, object, object, object, Port],
) -> None:
    transform = fx.channel.from_transform(_transform)
    assert_type(source.map(str), _Ch[str, ValueError, str, object, object, object, Replica])
    assert_type(source.map_done(len), _Ch[int, ValueError, int, object, object, object, Replica])
    assert_type(
        source.map_done_effect(lambda d: fx.fail(NotFound(d))),
        _Ch[int, ValueError | NotFound, Never, object, object, object, Replica],
    )
    assert_type(
        source.concat(other),
        _Ch[int | bytes, ValueError | KeyError, float, object, object, object, Replica | Port],
    )
    assert_type(
        source.pipe_to(transform),
        _Ch[str, NotFound | KeyError, None, object, object, object, Replica | Primary],
    )
    other.pipe_to(transform)  # pyright: ignore[reportArgumentType]


def check_channel_runs(source: _Ch[int, ValueError, str, object, object, object, Replica]) -> None:
    assert_type(source.run_collect(), fx.Effect[list[int], ValueError, Replica])
    assert_type(source.run_drain(), fx.Effect[str, ValueError, Replica])
    assert_type(
        source.run_for_each(lambda _: fx.fail(KeyError())),
        fx.Effect[str, ValueError | KeyError, Replica],
    )
    assert_type(
        source.run_fold(lambda: "", lambda s, n: s + str(n)), fx.Effect[str, ValueError, Replica]
    )
    assert_type(source.run_count(), fx.Effect[int, ValueError, Replica])
    assert_type(source.run_head(), fx.Effect[fx.Option[int], ValueError, Replica])
    assert_type(
        source.to_pull(), fx.Effect[fx.Pull[int, ValueError, str], Never, Replica | fx.Scope]
    )
    needs_input = fx.channel.from_transform(_transform)
    needs_input.run_collect()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def check_channel_unwrap(
    made: fx.Effect[_Ch[int, NotFound, None, object, object, object, Primary], NotFound, fx.Scope],
    made_with: fx.Effect[_Ch[int], NotFound, fx.Scope | Replica],
) -> None:
    assert_type(fx.channel.unwrap(made), _Ch[int, NotFound, None, object, object, object, Primary])
    assert_type(
        fx.channel.unwrap(made_with), _Ch[int, NotFound, None, object, object, object, Replica]
    )


def check_pull_helpers(
    p: fx.Effect[int, NotFound | fx.Done[str], Primary], ends: fx.Effect[int, fx.Done[str]]
) -> None:
    assert_type(
        fx.pull.catch_done(p, lambda left: fx.succeed(len(left))),
        fx.Effect[int, NotFound, Primary],
    )
    assert_type(fx.pull.catch_done(ends, fx.succeed), fx.Effect[int | str])
    assert_type(
        fx.pull.match_effect(
            p,
            on_success=lambda n: fx.succeed(str(n)),
            on_failure=lambda c: fx.succeed(str(c.failures)),
            on_done=fx.succeed,
        ),
        fx.Effect[str, Never, Primary],
    )
    assert_type(fx.take.to_pull((1, 2)), fx.Effect[tuple[int, ...], fx.Done[None]])


def check_channel_resources(
    acquire: fx.Effect[int, NotFound, Primary],
    takes: fx.Effect[fx.Take[str, KeyError, int], KeyError, Primary],
) -> None:
    assert_type(
        fx.channel.acquire_use_release(
            acquire, lambda n: fx.channel.succeed(str(n)), lambda _, __: fx.void
        ),
        _Ch[str, NotFound, None, object, object, object, Primary],
    )
    assert_type(
        fx.channel.acquire_release(acquire, lambda _, __: fx.void),
        _Ch[int, NotFound, None, object, object, object, Primary],
    )
    assert_type(
        fx.channel.from_effect_take(takes),
        _Ch[tuple[str, ...], KeyError, int, object, object, object, Primary],
    )


def check_channel_transforms(
    source: _Ch[int, ValueError, str, object, object, object, Replica],
    other: _Ch[bytes, KeyError, float, object, object, object, Port],
) -> None:
    assert_type(
        source.map_effect(lambda n: fx.fail(NotFound(str(n))), concurrency=4),
        _Ch[Never, ValueError | NotFound, str, object, object, object, Replica],
    )
    assert_type(
        source.flat_map(lambda _: other, concurrency="unbounded"),
        _Ch[bytes, ValueError | KeyError, str, object, object, object, Replica | Port],
    )
    assert_type(
        source.filter(lambda n: n > 0), _Ch[int, ValueError, str, object, object, object, Replica]
    )
    assert_type(
        source.scan("", lambda s, n: s + str(n)),
        _Ch[str, ValueError, str, object, object, object, Replica],
    )
    assert_type(
        source.map_accum(lambda: 0, lambda s, n: (s + n, [str(n)])),
        _Ch[str, ValueError, str, object, object, object, Replica],
    )
    assert_type(source.drain(), _Ch[Never, ValueError, str, object, object, object, Replica])


def check_channel_filter_maps(
    source: _Ch[int, ValueError, str, object, object, object, Replica],
    chunks: _Ch[tuple[int, ...], ValueError, str, object, object, object, Replica],
) -> None:
    def halve(n: int) -> fx.Result[float, int]:
        return fx.Ok(n / 2) if n % 2 == 0 else fx.Err(n)

    def halve_effect(n: int) -> fx.Effect[fx.Result[float, int], KeyError, Port]:
        return fx.succeed(halve(n))

    assert_type(
        source.filter_map(halve), _Ch[float, ValueError, str, object, object, object, Replica]
    )
    assert_type(
        source.filter_map_effect(halve_effect),
        _Ch[float, ValueError | KeyError, str, object, object, object, Replica | Port],
    )
    assert_type(
        chunks.filter_map_array(halve),
        _Ch[tuple[float, ...], ValueError, str, object, object, object, Replica],
    )
    assert_type(
        chunks.filter_map_array_effect(halve_effect),
        _Ch[tuple[float, ...], ValueError | KeyError, str, object, object, object, Replica | Port],
    )
    source.filter_map_array(halve)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def check_channel_catch_filters(
    source: _Ch[int, NotFound | Invalid, str, object, object, object, Replica],
) -> None:
    def not_found(e: NotFound | Invalid) -> fx.Result[NotFound, Invalid]:
        return fx.Ok(e) if isinstance(e, NotFound) else fx.Err(e)

    def found_cause(c: fx.Cause[NotFound | Invalid]) -> fx.Result[str, fx.Cause[Invalid]]:
        return fx.Ok("found")

    assert_type(
        source.catch_filter(not_found, lambda e: fx.channel.succeed(e.key)),
        _Ch[int | str, Invalid, str | None, object, object, object, Replica],
    )
    assert_type(
        source.catch_filter(
            not_found, lambda e: fx.channel.succeed(e.key), or_else=lambda _: fx.channel.empty
        ),
        _Ch[int | str, Never, str | None, object, object, object, Replica],
    )
    assert_type(
        source.catch_cause_filter(found_cause, lambda s, _: fx.channel.succeed(s)),
        _Ch[int | str, Invalid, str | None, object, object, object, Replica],
    )


def check_channel_failures(
    source: _Ch[int, NotFound | Invalid, str, object, object, object, Replica],
) -> None:
    assert_type(
        source.catch_all(fx.channel.succeed),
        _Ch[int | NotFound | Invalid, Never, str | None, object, object, object, Replica],
    )
    assert_type(
        source.catch_cause(lambda _: fx.channel.fail(KeyError())),
        _Ch[int, KeyError, str, object, object, object, Replica],
    )
    assert_type(
        source.catch_if(is_not_found, lambda _: fx.channel.succeed("x")),
        _Ch[int | str, NotFound | Invalid, str | None, object, object, object, Replica],
    )
    assert_type(
        source.pipe(fx.channel.catch_tag(NotFound, lambda _: fx.channel.succeed("x"))),
        _Ch[int | str, Invalid, str | None, object, object, object, Replica],
    )
    assert_type(
        source.pipe(fx.channel.catch_if(is_not_found, lambda _: fx.channel.empty)),
        _Ch[int, Invalid, str | None, object, object, object, Replica],
    )
    assert_type(
        source.map_error(lambda _: KeyError()),
        _Ch[int, KeyError, str, object, object, object, Replica],
    )
    assert_type(source.or_die(), _Ch[int, Never, str, object, object, object, Replica])
    assert_type(source.ignore(), _Ch[int, Never, str | None, object, object, object, Replica])
    assert_type(
        source.retry(schedule.recurs(2)),
        _Ch[int, NotFound | Invalid, str, object, object, object, Replica],
    )


def check_channel_services(
    source: _Ch[int, ValueError, str, object, object, object, Replica | Port],
) -> None:
    assert_type(
        source.pipe(fx.channel.provide_service(Port, 1)),
        _Ch[int, ValueError, str, object, object, object, Replica],
    )
    assert_type(
        source.pipe(fx.channel.provide_service_effect(Port, fx.fail(KeyError()).as_(1))),
        _Ch[int, ValueError | KeyError, str, object, object, object, Replica],
    )
    assert_type(
        source.update_service(Primary, lambda db: db),
        _Ch[int, ValueError, str, object, object, object, Replica | Port | Primary],
    )
    scoped = fx.channel.from_effect(fx.add_finalizer(lambda _: fx.void))
    assert_type(scoped, _Ch[None, Never, None, object, object, object, fx.Scope])
    assert_type(fx.channel.scoped(scoped), _Ch[None])
    source.pipe(fx.channel.provide_service(Port, "not an int"))  # pyright: ignore[reportArgumentType]


def check_channel_lifecycle(
    source: _Ch[int, ValueError, str, object, object, object, Replica],
) -> None:
    assert_type(
        source.on_end(fx.fail(KeyError())),
        _Ch[int, ValueError | KeyError, str, object, object, object, Replica],
    )
    assert_type(
        source.ensuring(fx.void), _Ch[int, ValueError, str, object, object, object, Replica]
    )
    assert_type(source.forever(), _Ch[int, ValueError, Never, object, object, object, Replica])
    assert_type(
        source.repeat(schedule.recurs(2)),
        _Ch[int, ValueError, str, object, object, object, Replica],
    )
    assert_type(
        source.schedule(schedule.recurs(2)),
        _Ch[int, ValueError, str | int, object, object, object, Replica],
    )


def check_channel_concurrency(
    source: _Ch[int, ValueError, str, object, object, object, Replica],
    other: _Ch[bytes, KeyError, float, object, object, object, Port],
    halt: fx.Effect[bool, NotFound],
) -> None:
    assert_type(
        source.merge(other, halt_strategy="either"),
        _Ch[
            int | bytes, ValueError | KeyError, str | float, object, object, object, Replica | Port
        ],
    )
    assert_type(
        source.interrupt_when(halt),
        _Ch[int, ValueError | NotFound, str | bool, object, object, object, Replica],
    )
    assert_type(
        source.switch_map(lambda _: other),
        _Ch[bytes, ValueError | KeyError, str, object, object, object, Replica | Port],
    )
    assert_type(
        source.buffer(capacity=4, strategy="sliding"),
        _Ch[int, ValueError, str, object, object, object, Replica],
    )
    nested = fx.channel.succeed(other)
    assert_type(
        nested.merge_all(concurrency=2), _Ch[bytes, KeyError, None, object, object, object, Port]
    )
    source.merge_all(concurrency=2)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def _offer_one(queue: fx.Queue[int, fx.Done]) -> fx.Effect[bool]:
    return queue.offer(1).and_then(queue.end())


def check_channel_io(
    queue: fx.Queue[int, NotFound | fx.Done],
    pubsub: fx.PubSub[str],
    chunks: _Ch[tuple[bytes, ...], ValueError, str],
) -> None:
    assert_type(fx.channel.from_queue(queue), _Ch[int, NotFound])
    assert_type(fx.channel.from_pubsub(pubsub), _Ch[str])
    assert_type(fx.channel.from_schedule(schedule.recurs(2)), _Ch[int, Never, int])
    assert_type(fx.channel.callback(_offer_one), _Ch[int])
    assert_type(chunks.run_bytes(), fx.Effect[bytes, ValueError])
    assert_type(chunks.pipe_to(fx.channel.decode_text()), _Ch[tuple[str, ...], ValueError, str])
    assert_type(
        fx.channel.from_iterable([1]).to_queue(capacity="unbounded"),
        fx.Effect[Dequeue[int, fx.Done], Never, fx.Scope],
    )
    chunks.run_into_queue(queue)  # pyright: ignore[reportArgumentType]


# --- streams ---------------------------------------------------------------------

type _St[A, E = Never, R = Never] = fx.stream.Stream[A, E, R]


def check_stream_constructors(eff: fx.Effect[int, NotFound, Primary]) -> None:
    st = fx.stream
    assert_type(st.succeed(1), _St[int])
    assert_type(st.make(1, 2), _St[int])
    assert_type(st.make(), _St[Never])
    assert_type(st.sync(lambda: "a"), _St[str])
    assert_type(st.empty, _St[Never])
    assert_type(st.never, _St[Never])
    assert_type(st.fail(NotFound("k")), _St[Never, NotFound])
    assert_type(st.die(RuntimeError()), _St[Never])
    assert_type(st.from_effect(eff), _St[int, NotFound, Primary])
    assert_type(st.from_effect_drain(eff), _St[Never, NotFound, Primary])
    assert_type(st.from_iterable("ab", chunk_size=1), _St[str])
    assert_type(st.from_arrays([1], (2,)), _St[int])
    assert_type(st.from_iterable_effect(eff.map(lambda n: [n])), _St[int, NotFound, Primary])
    assert_type(st.range(0, 3), _St[int])
    assert_type(st.range_inclusive(0, 3), _St[int])
    assert_type(st.iterate(1, lambda n: n + 1), _St[int])
    assert_type(st.service(Primary), _St[Db, Never, Primary])
    assert_type(st.service_option(Primary), _St[fx.Option[Db]])
    assert_type(st.suspend(lambda: st.from_effect(eff)), _St[int, NotFound, Primary])
    assert_type(st.tick(1), _St[None])
    st.range(0, 1.5)  # pyright: ignore[reportArgumentType]


def check_stream_repeats(
    ends: fx.Effect[int, NotFound | fx.Done, Primary], only_ends: fx.Effect[str, fx.Done]
) -> None:
    assert_type(fx.stream.from_effect_repeat(ends), _St[int, NotFound, Primary])
    assert_type(fx.stream.from_effect_repeat(only_ends), _St[str])
    assert_type(fx.stream.from_effect_repeat(fx.succeed(1)), _St[int])
    assert_type(fx.stream.from_iterable_effect_repeat(only_ends.map(list)), _St[str, Never, Never])
    assert_type(
        fx.stream.from_effect_schedule(fx.fail(NotFound("k")), schedule.recurs(1)),
        _St[Never, NotFound],
    )
    assert_type(fx.stream.from_effect_schedule(fx.succeed(1), schedule.recurs(1)), _St[int])
    assert_type(fx.stream.from_schedule(schedule.recurs(1)), _St[int])


def check_stream_unfolds(
    step: Callable[[int], fx.Effect[tuple[str, int] | None, NotFound]],
) -> None:
    assert_type(fx.stream.unfold(0, step), _St[str, NotFound])

    def page(s: int) -> fx.Effect[tuple[list[str], fx.Option[int]], NotFound, Port]: ...

    assert_type(fx.stream.paginate(0, page), _St[str, NotFound, Port])


def check_stream_pulls(
    pull: fx.Effect[fx.Effect[tuple[int, ...], NotFound | fx.Done, Primary], NotFound, Primary],
    source: _St[int, ValueError, Replica],
) -> None:
    assert_type(fx.stream.from_pull(pull), _St[int, NotFound, Primary])
    channel = fx.stream.to_channel(source)
    assert_type(
        channel,
        fx.channel.Channel[tuple[int, ...], ValueError, None, object, object, object, Replica],
    )
    assert_type(fx.stream.from_channel(channel), _St[int, ValueError, Replica])
    chunks: list[tuple[int, ...]] = [(1,)]
    assert_type(fx.stream.from_channel(fx.channel.from_iterable(chunks)), _St[int])
    fx.stream.from_channel(fx.channel.from_iterable([1]))  # pyright: ignore[reportArgumentType]
    assert_type(
        fx.stream.transform_pull(source, lambda p, _scope: fx.succeed(p.map(lambda c: c * 2))),
        _St[int, ValueError, Replica],
    )


def check_stream_sources(
    queue: Dequeue[int, NotFound | fx.Done],
    pubsub: fx.PubSub[str],
    takes: fx.PubSub[fx.Take[int, NotFound]],
    subscription: Subscription[bytes],
) -> None:
    assert_type(fx.stream.from_queue(queue), _St[int, NotFound])
    assert_type(fx.stream.from_pubsub(pubsub), _St[str])
    assert_type(fx.stream.from_pubsub_take(takes), _St[int, NotFound])
    assert_type(fx.stream.from_subscription(subscription), _St[bytes])
    assert_type(fx.SubscriptionRef(1).changes(), _St[int])

    def register(q: fx.Queue[int, NotFound | fx.Done]) -> fx.Effect[None, NotFound, fx.Scope]: ...

    def register_with(q: fx.Queue[int, fx.Done]) -> fx.Effect[None, Never, fx.Scope | Port]: ...

    assert_type(fx.stream.callback(register), _St[int, NotFound])
    assert_type(fx.stream.callback(register_with, buffer_size=2), _St[int, Never, Port])


def check_stream_scopes(
    made: fx.Effect[_St[int, NotFound, Primary], NotFound, fx.Scope],
    needs_scope: _St[int, NotFound, fx.Scope | Primary],
    only_scope: _St[int, NotFound, fx.Scope],
) -> None:
    assert_type(fx.stream.unwrap(made), _St[int, NotFound, Primary])
    assert_type(needs_scope.pipe(fx.stream.scoped), _St[int, NotFound, Primary])
    assert_type(only_scope.pipe(fx.stream.scoped), _St[int, NotFound])


def check_stream_services(
    source: _St[int, ValueError, Replica | Port],
    only_port: _St[int, ValueError, Port],
    port_layer: fx.Layer[Port, KeyError, Primary],
) -> None:
    assert_type(source.pipe(fx.stream.provide_service(Port, 1)), _St[int, ValueError, Replica])
    assert_type(only_port.pipe(fx.stream.provide_service(Port, 1)), _St[int, ValueError])
    assert_type(
        source.pipe(fx.stream.provide_service_effect(Port, fx.fail(KeyError()).as_(1))),
        _St[int, ValueError | KeyError, Replica],
    )
    assert_type(
        only_port.pipe(fx.stream.provide_context(fx.Context.make(Port, 1))), _St[int, ValueError]
    )
    assert_type(
        source.pipe(fx.stream.provide(fx.Context.make(Port, 1))), _St[int, ValueError, Replica]
    )
    assert_type(
        source.pipe(fx.stream.provide(port_layer)),
        _St[int, ValueError | KeyError, Replica | Primary],
    )

    def add_port(ctx: fx.Context[Primary]) -> fx.Context[Primary | Port]:
        return ctx.add(Port, 1)

    assert_type(only_port.pipe(fx.stream.update_context(add_port)), _St[int, ValueError, Primary])
    assert_type(
        source.update_service(Primary, lambda db: db),
        _St[int, ValueError, Replica | Port | Primary],
    )
    assert_type(source.with_span("s"), _St[int, ValueError, Replica | Port])
    source.pipe(fx.stream.provide_service(Port, "not an int"))  # pyright: ignore[reportArgumentType]


def check_stream_runs(source: _St[int, ValueError, Replica], words: _St[str]) -> None:
    assert_type(source.run_collect(), fx.Effect[list[int], ValueError, Replica])
    assert_type(source.run_drain(), fx.Effect[None, ValueError, Replica])
    assert_type(source.run_count(), fx.Effect[int, ValueError, Replica])
    assert_type(source.run_sum(), fx.Effect[int, ValueError, Replica])
    assert_type(
        source.run_fold(lambda: "", lambda s, n: s + str(n)), fx.Effect[str, ValueError, Replica]
    )
    assert_type(
        source.run_fold_effect(lambda: 0, lambda s, n: fx.fail(KeyError()).as_(s + n)),
        fx.Effect[int, ValueError | KeyError, Replica],
    )
    assert_type(source.run_head(), fx.Effect[fx.Option[int], ValueError, Replica])
    assert_type(source.run_last(), fx.Effect[fx.Option[int], ValueError, Replica])
    assert_type(
        source.run_for_each(lambda _: fx.fail(KeyError())),
        fx.Effect[None, ValueError | KeyError, Replica],
    )
    assert_type(
        source.run_for_each_while(lambda n: fx.succeed(n < 3).pipe(fx.provide_service(Port, 1))),
        fx.Effect[None, ValueError, Replica],
    )
    assert_type(
        source.run_for_each_array(lambda chunk: fx.succeed(len(chunk))),
        fx.Effect[None, ValueError, Replica],
    )
    assert_type(
        source.to_pull(), fx.Effect[fx.Pull[tuple[int, ...], ValueError], Never, Replica | fx.Scope]
    )
    assert_type(words.run_string(), fx.Effect[str])
    assert_type(fx.stream.make(b"a").run_bytes(), fx.Effect[bytes])
    source.run_string()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def _is_not_found(error: object) -> TypeIs[NotFound]:
    return isinstance(error, NotFound)


def _is_int(value: object) -> TypeIs[int]:
    return isinstance(value, int)


def check_stream_operators(
    source: _St[int, ValueError, Replica], other: _St[str, KeyError]
) -> None:
    assert_type(source.map(str), _St[str, ValueError, Replica])
    assert_type(
        source.map_effect(lambda n: fx.fail(KeyError()).as_(n)),
        _St[int, ValueError | KeyError, Replica],
    )
    assert_type(source.flat_map(lambda _: other), _St[str, ValueError | KeyError, Replica])
    assert_type(source.switch_map(lambda _: other), _St[str, ValueError | KeyError, Replica])
    assert_type(fx.stream.make(other).flatten(), _St[str, KeyError])
    source.flatten()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(source.filter(lambda n: n > 0), _St[int, ValueError, Replica])
    mixed: _St[int | str] = fx.stream.make(1, "a")
    assert_type(mixed.filter(_is_int), _St[int])
    assert_type(mixed.take_while(_is_int), _St[int])
    assert_type(source.take(2).drop(1).changes(), _St[int, ValueError, Replica])
    assert_type(source.grouped(2), _St[tuple[int, ...], ValueError, Replica])
    assert_type(source.zip_with_next(), _St[tuple[int, fx.Option[int]], ValueError, Replica])
    assert_type(fx.stream.make(b"ab").limit_bytes(1, lambda: fx.stream.empty), _St[bytes])
    source.limit_bytes(1, lambda: fx.stream.empty)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(source.zip(other), _St[tuple[int, str], ValueError | KeyError, Replica])
    assert_type(
        source.zip(other).zip_flatten(source),
        _St[tuple[int, str, int], ValueError | KeyError, Replica],
    )
    assert_type(source.merge(other), _St[int | str, ValueError | KeyError, Replica])
    assert_type(
        fx.stream.make(1).interleave_with(fx.stream.make("a"), fx.stream.make(True)),
        _St[int | str],
    )
    assert_type(
        source.interleave_with(other, fx.stream.make(True)),
        _St[int | str, ValueError | KeyError, Replica],
    )
    assert_type(
        source.combine(other, lambda: 0, lambda s, left, _right: left.map(lambda n: (n, s))),
        _St[int, ValueError, Replica],
    )
    assert_type(
        source.combine(other, lambda: 0, lambda s, _left, right: right.map(lambda a: (a, s))),
        _St[str, KeyError, Replica],
    )
    assert_type(
        fx.stream.make(1).combine(
            fx.stream.make("a"), lambda: 0, lambda s, left, _right: left.map(lambda n: (n, s))
        ),
        _St[int],
    )
    assert_type(
        source.combine_array(other, lambda: 0, lambda s, left, _right: left.map(lambda c: (c, s))),
        _St[int, ValueError, Replica],
    )
    assert_type(source.collect(), _St[list[int], ValueError, Replica])
    assert_type(source.accumulate(), _St[tuple[int, ...], ValueError, Replica])
    assert_type(fx.stream.merge_all([source, source], concurrency=2), _St[int, ValueError, Replica])
    assert_type(
        fx.stream.zip_latest_all(source, other),
        _St[tuple[int, str], ValueError | KeyError, Replica],
    )
    assert_type(fx.stream.race_all(source, source), _St[int, ValueError, Replica])
    assert_type(source.buffer(capacity="unbounded"), _St[int, ValueError, Replica])
    assert_type(source.buffer(capacity=2, strategy="sliding"), _St[int, ValueError, Replica])
    assert_type(source.catch_all(lambda _: other), _St[int | str, KeyError, Replica])
    assert_type(source.ignore(), _St[int, Never, Replica])
    assert_type(
        source.catch_filter(lambda e: fx.Ok(e) if e.args else fx.Err(e), lambda _: other),
        _St[int | str, ValueError | KeyError, Replica],
    )


def check_stream_catch_removes_errors(source: _St[int, NotFound | ValueError]) -> None:
    caught = source.pipe(fx.stream.catch_tag(NotFound, lambda _: fx.stream.make("x")))
    assert_type(caught, _St[int | str, ValueError])
    refined = source.pipe(fx.stream.catch_if(_is_not_found, lambda _: fx.stream.make("x")))
    assert_type(refined, _St[int | str, ValueError])
    assert_type(
        source.catch_if(_is_not_found, lambda _: fx.stream.make("x")),
        _St[int | str, NotFound | ValueError],
    )


# --- sinks -----------------------------------------------------------------------

type _Sk[A, In = object, L = Never, E = Never, R = Never] = fx.sink.Sink[A, In, L, E, R]


def _add_one(n: int, item: int) -> fx.Effect[int, NotFound]: ...
def _int_below(n: int) -> bool: ...
def _keep_int(n: int) -> fx.Result[str, None]: ...
def _int_check(n: int) -> fx.Effect[bool, NotFound, Primary]: ...
def _str_len(s: str) -> int: ...
def _plus(a: int, b: int) -> int: ...


def check_sink_constructors(eff: fx.Effect[int, NotFound, Primary], word: str) -> None:
    sk = fx.sink
    assert_type(sk.succeed(word), _Sk[str])
    assert_type(sk.succeed(word, (word,)), _Sk[str, object, str])
    assert_type(sk.sync(lambda: "a"), _Sk[str])
    assert_type(sk.fail(NotFound("k")), _Sk[Never, object, Never, NotFound])
    assert_type(sk.die(ValueError()), _Sk[Never])
    assert_type(sk.never, _Sk[Never])
    assert_type(sk.drain, _Sk[None])
    assert_type(sk.count, _Sk[int])
    assert_type(sk.timed, _Sk[float])
    assert_type(sk.from_effect(eff), _Sk[int, object, Never, NotFound, Primary])
    assert_type(sk.fold(lambda: 0, _int_below, _add_one), _Sk[int, int, int, NotFound])
    assert_type(sk.fold_until(lambda: 0, 3, _add_one), _Sk[int, int, int, NotFound])
    assert_type(
        sk.reduce_while_effect(lambda: 0, _int_below, _add_one), _Sk[int, int, int, NotFound]
    )
    assert_type(sk.reduce_effect(lambda: 0, _add_one), _Sk[int, int, Never, NotFound])
    assert_type(sk.reduce(lambda: 0, _plus), _Sk[int, int])
    assert_type(sk.every(_int_below), _Sk[bool, int, int])
    assert_type(sk.take_while(_int_below), _Sk[list[int], int, int])
    assert_type(sk.take_while(_is_int), _Sk[list[int], object, object])
    assert_type(sk.take_while_filter(_keep_int), _Sk[list[str], int, int])
    assert_type(sk.take_until_effect(_int_check), _Sk[list[int], int, int, NotFound, Primary])
    assert_type(sk.find(_is_int), _Sk[fx.Option[int], object, object])
    assert_type(sk.for_each(_int_check), _Sk[None, int, Never, NotFound, Primary])
    assert_type(sk.from_queue(fx.Queue[int, fx.Done]()), _Sk[None, int])
    sk.from_queue(fx.Queue[int]())  # pyright: ignore[reportArgumentType]


def check_sink_inference(source: _St[int, ValueError, Replica], words: _Sk[list[str], str]) -> None:
    sk = fx.sink
    assert_type(source.run(sk.sum()), fx.Effect[int, ValueError, Replica])
    assert_type(source.run(sk.collect()), fx.Effect[list[int], ValueError, Replica])
    assert_type(source.run(sk.head()), fx.Effect[fx.Option[int], ValueError, Replica])
    assert_type(source.run(sk.take(2)), fx.Effect[list[int], ValueError, Replica])
    assert_type(source.run(sk.count), fx.Effect[int, ValueError, Replica])
    source.run(words)  # pyright: ignore[reportArgumentType]


def check_sink_methods(
    taking: _Sk[list[int], int, int],
    counting: _Sk[int, int],
    failing: _Sk[int, int, Never, NotFound],
) -> None:
    assert_type(taking.map(len), _Sk[int, int, int])
    assert_type(taking.as_("a"), _Sk[str, int, int])
    assert_type(taking.map_effect(lambda _: fx.fail(NotFound("k"))), _Sk[Never, int, int, NotFound])
    assert_type(counting.map_input(_str_len), _Sk[int, str])
    assert_type(taking.map_leftover(str), _Sk[list[int], int, str])
    assert_type(taking.ignore_leftover(), _Sk[list[int], int])
    assert_type(taking.with_duration(), _Sk[tuple[list[int], float], int, int])
    assert_type(taking.flat_map(lambda _: counting), _Sk[int, int, int])
    assert_type(counting.flat_map(lambda _: taking), _Sk[list[int], int, int])
    assert_type(failing.map_error(str), _Sk[int, int, Never, str])
    assert_type(failing.catch_all(lambda _: fx.succeed("x")), _Sk[int | str, int])
    assert_type(failing.catch_cause(lambda _: fx.succeed("x")), _Sk[int | str, int])
    assert_type(failing.or_else(lambda _: taking), _Sk[int | list[int], int, int])
    assert_type(failing.ensuring(fx.void), _Sk[int, int, Never, NotFound])


def check_sink_services(needing: _Sk[int, int, Never, NotFound, Primary | Replica]) -> None:
    assert_type(
        needing.pipe(fx.sink.provide_service(Primary, GoodDb())),
        _Sk[int, int, Never, NotFound, Replica],
    )
    built = fx.sink.unwrap(fx.succeed(fx.sink.count))
    assert_type(built, _Sk[int])


def check_stream_sink_methods(
    source: _St[int, ValueError, Replica],
    taking: _Sk[list[int], int, int, NotFound],
    words: _Sk[list[str], str, str],
) -> None:
    assert_type(source.run(taking), fx.Effect[list[int], ValueError | NotFound, Replica])
    assert_type(source.transduce(taking), _St[list[int], ValueError | NotFound, Replica])
    assert_type(source.aggregate(taking), _St[list[int], ValueError | NotFound, Replica])
    assert_type(
        source.aggregate_within(taking, schedule.spaced(1)),
        _St[list[int], ValueError | NotFound, Replica],
    )
    assert_type(source.grouped_within(3, 1), _St[list[int], ValueError, Replica])
    assert_type(source.pipe_through(taking), _St[int, ValueError | NotFound, Replica])
    assert_type(source.tap_sink(fx.sink.drain), _St[int, ValueError, Replica])
    assert_type(
        source.peel(taking),
        fx.Effect[
            tuple[list[int], _St[int, ValueError]], ValueError | NotFound, fx.Scope | Replica
        ],
    )
    assert_type(fx.stream.empty.transduce(fx.sink.reduce(lambda: 0, _plus)), _St[int])
    source.transduce(words)  # pyright: ignore[reportArgumentType]


def check_stream_transform_pull_without_services(source: _St[int, ValueError]) -> None:
    assert_type(
        fx.stream.transform_pull(source, lambda p, _scope: fx.succeed(p)), _St[int, ValueError]
    )


def _parity_of(n: int) -> fx.Effect[tuple[bool, str], NotFound, Primary]: ...


def _sign_of(n: int) -> fx.Ok[int] | fx.Err[str]: ...


def check_stream_fan_out(source: _St[int, ValueError, Replica]) -> None:
    assert_type(
        source.group_by(_parity_of),
        _St[tuple[bool, _St[str]], ValueError | NotFound, Replica | Primary],
    )
    assert_type(
        source.group_by_key(lambda n: n % 2), _St[tuple[int, _St[int]], ValueError, Replica]
    )
    assert_type(
        source.group_adjacent_by(str), _St[tuple[str, tuple[int, ...]], ValueError, Replica]
    )
    assert_type(
        source.partition(_sign_of),
        fx.Effect[tuple[_St[int, ValueError], _St[str, ValueError]], Never, Replica | fx.Scope],
    )
    assert_type(
        source.partition_effect(lambda n: fx.succeed(_sign_of(n)), concurrency=2),
        fx.Effect[tuple[_St[int, ValueError], _St[str, ValueError]], Never, Replica | fx.Scope],
    )
    assert_type(
        source.partition_queue(_sign_of),
        fx.Effect[
            tuple[Dequeue[int, ValueError | fx.Done], Dequeue[str, ValueError | fx.Done]],
            Never,
            Replica | fx.Scope,
        ],
    )
    assert_type(
        source.broadcast(capacity=8), fx.Effect[_St[int, ValueError], Never, Replica | fx.Scope]
    )
    assert_type(
        source.broadcast(capacity="unbounded", replay=2),
        fx.Effect[_St[int, ValueError], Never, Replica | fx.Scope],
    )
    source.broadcast(capacity="unbounded", strategy="dropping")  # pyright: ignore[reportArgumentType]
    assert_type(
        source.broadcast_n(2, capacity=4, strategy="sliding"),
        fx.Effect[tuple[_St[int, ValueError], ...], Never, Replica | fx.Scope],
    )
    assert_type(
        source.share(capacity=16, idle_time_to_live=1),
        fx.Effect[_St[int, ValueError], Never, Replica | fx.Scope],
    )


def check_stream_bridges(
    source: _St[int, ValueError, Replica],
    plain: _St[str],
    queue: fx.Queue[int, ValueError | fx.Done],
    pubsub: fx.PubSub[int],
    replica: fx.Context[Replica],
) -> None:
    assert_type(
        source.to_queue(capacity="unbounded"),
        fx.Effect[Dequeue[int, ValueError | fx.Done], Never, Replica | fx.Scope],
    )
    assert_type(source.run_into_queue(queue), fx.Effect[None, Never, Replica])
    plain.run_into_queue(queue)  # pyright: ignore[reportArgumentType]
    assert_type(source.run_into_pubsub(pubsub), fx.Effect[None, ValueError, Replica])
    assert_type(source.to_pubsub(capacity=8), fx.Effect[fx.PubSub[int], Never, Replica | fx.Scope])
    assert_type(
        source.to_pubsub_take(capacity=8),
        fx.Effect[fx.PubSub[fx.Take[int, ValueError]], Never, Replica | fx.Scope],
    )
    assert_type(plain.to_async_iterable(), fx.stream.StreamAsyncIterable[str])
    source.to_async_iterable()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(source.to_async_iterable_with(replica), fx.stream.StreamAsyncIterable[int])
    source.to_async_iterable_with(fx.Context.empty())  # pyright: ignore[reportArgumentType]
    assert_type(
        source.to_async_iterable_effect(),
        fx.Effect[fx.stream.StreamAsyncIterable[int], Never, Replica],
    )
    assert_type(aiter(plain.to_async_iterable()), fx.stream.StreamAsyncIterator[str])


async def check_stream_async_for(plain: _St[str]) -> None:
    async for word in plain.to_async_iterable():
        assert_type(word, str)


# --- Stream channel and text methods, framers ----------------------------------------

type _Duplexed[T, IE] = fx.Channel[tuple[T, ...], KeyError, int, tuple[T, ...], IE, str, Replica]


def check_stream_text_and_framers(
    *,
    data: _St[bytes, ValueError, Replica],
    text: _St[str, ValueError],
    plain: _St[int],
    events: _St[sse.Event, sse.Retry],
    failing_events: _St[sse.Event, ValueError],
    to_bytes: _Duplexed[bytes, ValueError | ndjson.NdjsonError],
    to_text: _Duplexed[str, ndjson.NdjsonError],
) -> None:
    assert_type(data.decode_text(), _St[str, ValueError, Replica])
    assert_type(data.decode_text("latin-1"), _St[str, ValueError, Replica])
    assert_type(text.encode_text(), _St[bytes, ValueError])
    assert_type(text.split_lines(), _St[str, ValueError])
    plain.decode_text()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    plain.split_lines()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    data.encode_text()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    # A channel's upstream error is the stream's: the channel decides.
    assert_type(
        data.pipe_through_channel(ndjson.decode()),
        _St[Json, ValueError | ndjson.NdjsonError, Replica],
    )
    assert_type(
        text.pipe_through_channel(ndjson.decode_string(ignore_empty_lines=True)),
        _St[Json, ValueError | ndjson.NdjsonError],
    )
    assert_type(
        data.pipe_through_channel(json_array.decode(pointer="/items")),
        _St[Json, ValueError | json_array.JsonArrayError, Replica],
    )
    assert_type(
        text.pipe_through_channel(json_array.decode_string()),
        _St[Json, ValueError | json_array.JsonArrayError],
    )
    assert_type(plain.pipe_through_channel(ndjson.encode()), _St[bytes, ndjson.NdjsonError])
    assert_type(
        plain.pipe_through_channel(json_array.encode_string()), _St[str, json_array.JsonArrayError]
    )
    assert_type(
        text.pipe_through_channel(sse.decode()),
        _St[sse.Event, ValueError | sse.Retry | sse.SseError],
    )
    # ``sse.encode`` writes a ``Retry`` failure and ends: it leaves the errors.
    assert_type(events.pipe_through_channel(sse.encode()), _St[str])
    # Pyright cannot solve ``E | Retry`` from an upstream error without
    # ``Retry``; such a stream's failures pass by the encoder instead.
    failing_events.pipe_through_channel(sse.encode())  # pyright: ignore[reportArgumentType]
    assert_type(failing_events.pipe_through_channel_or_fail(sse.encode()), _St[str, ValueError])
    assert_type(
        data.pipe_through_channel_or_fail(fx.channel.decode_text()),
        _St[str, ValueError, Replica],
    )
    text.pipe_through_channel(ndjson.decode())  # pyright: ignore[reportArgumentType]
    plain.pipe_through_channel(sse.encode())  # pyright: ignore[reportArgumentType]
    assert_type(
        ndjson.duplex(to_bytes),
        fx.Channel[
            tuple[Json, ...],
            ndjson.NdjsonError | KeyError,
            int,
            tuple[object, ...],
            ValueError,
            str,
            Replica,
        ],
    )
    assert_type(
        ndjson.duplex_string(to_text),
        fx.Channel[
            tuple[Json, ...],
            ndjson.NdjsonError | KeyError,
            int,
            tuple[object, ...],
            Never,
            str,
            Replica,
        ],
    )
    ndjson.duplex(to_text)  # pyright: ignore[reportArgumentType, reportCallIssue]


# --- ChannelSchema and the schema framers ------------------------------------------------


def check_channel_schema(
    *,
    texts: _St[str, ValueError, Replica],
    numbers: _St[float],
    data: _St[bytes, ValueError],
    sse_text: _St[str],
    wire: fx.Channel[
        tuple[str, ...], KeyError, int, tuple[str, ...], ValueError | fx.schema.SchemaError, str
    ],
) -> None:
    from pyfect import channel_schema
    from pyfect import schema as S

    # The channel reads the schema's Encoded and writes its Type.
    assert_type(
        channel_schema.decode(S.NumberFromString),
        fx.Channel[tuple[float, ...], S.SchemaError, None, tuple[str, ...], Never, None],
    )
    assert_type(
        channel_schema.decode_unknown(S.NumberFromString),
        fx.Channel[tuple[float, ...], S.SchemaError, None, tuple[object, ...], Never, None],
    )
    assert_type(
        channel_schema.encode(S.NumberFromString),
        fx.Channel[tuple[str, ...], S.SchemaError, None, tuple[float, ...], Never, None],
    )
    assert_type(
        texts.pipe_through_channel(channel_schema.decode(S.NumberFromString)),
        _St[float, ValueError | S.SchemaError, Replica],
    )
    assert_type(
        channel_schema.duplex(
            wire, input_schema=S.NumberFromString, output_schema=S.NumberFromString
        ),
        fx.Channel[
            tuple[float, ...], S.SchemaError | KeyError, int, tuple[float, ...], ValueError, str
        ],
    )
    assert_type(
        data.pipe_through_channel(ndjson.decode_schema(S.NumberFromString)),
        _St[float, ValueError | ndjson.NdjsonError | S.SchemaError],
    )
    assert_type(
        numbers.pipe_through_channel(json_array.encode_schema_string(S.NumberFromString)),
        _St[str, json_array.JsonArrayError | S.SchemaError],
    )
    assert_type(
        sse_text.pipe_through_channel(sse.decode_data_schema(S.Int)),
        _St[sse.DataEvent[int], sse.Retry | sse.SseError | S.SchemaError],
    )


# --- ConfigProvider --------------------------------------------------------------------


def check_config_provider(needs_db: fx.Effect[fx.ConfigProvider, NotFound, Primary]) -> None:
    from pyfect import config_provider as cp

    provider = cp.from_env(env={"A": "1"})
    assert_type(provider.load(["A"]), fx.Effect[cp.Node | None, cp.SourceError])
    assert_type(provider.load(("A", 0)), fx.Effect[cp.Node | None, cp.SourceError])
    provider.load("A")  # pyright: ignore[reportArgumentType]
    assert_type(provider.or_else(cp.from_unknown({})).nested("APP"), cp.ConfigProvider)
    assert_type(provider.constant_case().map_input(lambda path: (*path, "x")), cp.ConfigProvider)
    assert_type(cp.make(lambda _path: fx.succeed(cp.Value("v"))), cp.ConfigProvider)
    assert_type(cp.from_dot_env(), fx.Effect[cp.ConfigProvider, fx.PlatformError, fx.FileSystem])
    assert_type(
        cp.from_dir("/run/secrets"), fx.Effect[cp.ConfigProvider, Never, fx.Path | fx.FileSystem]
    )
    assert_type(
        fx.CurrentConfigProvider(), TagEffect[cp.ConfigProvider, Never, fx.CurrentConfigProvider]
    )
    assert_type(cp.layer(provider), fx.Layer[fx.CurrentConfigProvider])
    assert_type(
        cp.layer(cp.from_dot_env()),
        fx.Layer[fx.CurrentConfigProvider, fx.PlatformError, fx.FileSystem],
    )
    assert_type(cp.layer(needs_db), fx.Layer[fx.CurrentConfigProvider, NotFound, Primary])
    assert_type(cp.layer_add(provider, as_primary=True), fx.Layer[fx.CurrentConfigProvider])
    assert_type(cp.layer_add(needs_db), fx.Layer[fx.CurrentConfigProvider, NotFound, Primary])
    cp.Record({"A"})  # pyright: ignore[reportArgumentType]


# --- Config ------------------------------------------------------------------------------


def check_config_constructors() -> None:
    from datetime import datetime
    from typing import Literal

    from pyfect import config
    from pyfect.byte_size import ByteSize
    from pyfect.http.url import Url

    assert_type(config.string("A"), fx.Config[str])
    assert_type(config.non_empty_string(), fx.Config[str])
    assert_type(config.number("A"), fx.Config[float])
    assert_type(config.finite("A"), fx.Config[float])
    assert_type(config.integer("A"), fx.Config[int])
    assert_type(config.port("A"), fx.Config[int])
    assert_type(config.boolean("A"), fx.Config[bool])
    assert_type(config.duration("A"), fx.Config[Seconds])
    assert_type(config.byte_size("A"), fx.Config[ByteSize])
    assert_type(config.date_time("A"), fx.Config[datetime])
    assert_type(config.url("A"), fx.Config[Url])
    assert_type(config.log_level("A"), fx.Config[fx.LogLevel])
    assert_type(config.redacted("A"), fx.Config[fx.Redacted[str]])
    assert_type(config.literal(1, 2, name="A"), fx.Config[int])
    env: fx.Config[Literal["dev", "prod"]] = config.literal("dev", "prod", name="ENV")
    assert_type(env, fx.Config[Literal["dev", "prod"]])
    config.literal([object()], name="A")  # pyright: ignore[reportArgumentType, reportCallIssue]
    assert_type(config.succeed(1), fx.Config[int])
    assert_type(
        config.fail(config.SchemaError(config.Forbidden({"message": "no"}))), fx.Config[Never]
    )
    assert_type(config.list_of(config.integer(), "PORTS"), fx.Config[list[int]])
    assert_type(config.dict_of(config.finite(), "W", separator=";"), fx.Config[dict[str, float]])
    config.list_of(config.integer, "PORTS")  # pyright: ignore[reportArgumentType]


def check_config_schema() -> None:
    import typing

    from pyfect import config
    from pyfect import schema as S

    class Db(typing.TypedDict):
        host: str
        port: int

    # ``config.schema`` decodes to the schema's type, whatever it encodes to.
    assert_type(config.schema(S.Int, "PORT"), fx.Config[int])
    assert_type(config.schema(S.Struct(Db), "db"), fx.Config[Db])
    assert_type(config.schema(S.Array(S.Finite), ("a", 0)), fx.Config[tuple[float, ...]])
    # A collection reads its items with a config or with a schema.
    assert_type(config.list_of(S.Finite, "PORTS"), fx.Config[list[float]])
    assert_type(config.dict_of(S.Int, "W"), fx.Config[dict[str, int]])
    config.schema(config.integer(), "PORT")  # pyright: ignore[reportArgumentType]
    config.schema(S.Int, 1)  # pyright: ignore[reportArgumentType]


def check_config_combinators(port: fx.Config[int], host: fx.Config[str]) -> None:
    from typing import Literal

    from pyfect import config

    assert_type(port.map(str), fx.Config[str])
    assert_type(port.with_default(None), fx.Config[int | None])
    assert_type(port.with_default(3000), fx.Config[int])
    assert_type(port.with_default("auto"), fx.Config[int | str])
    # A literal config keeps its literal when the default is one of them (as Flag does),
    # and widens like Effect's ``withDefault`` otherwise (research/typing/config_1).
    env: fx.Config[Literal["dev", "prod"]] = config.literal("dev", "prod", name="ENV")
    assert_type(env.with_default("dev"), fx.Config[Literal["dev", "prod"]])
    assert_type(env.with_default(None), fx.Config[Literal["dev", "prod"] | None])
    _: fx.Config[Literal["dev", "prod"]] = env.with_default("staging")  # pyright: ignore[reportAssignmentType]
    # Empty groups are Never, not Unknown, so their with_default stays typed.
    assert_type(config.all_dict({}), fx.Config[dict[Never, Never]])
    assert_type(config.all(*iter(())), fx.Config[tuple[Never, ...]])
    assert_type(config.all_dict({}).with_default("x"), fx.Config[dict[Never, Never] | str])
    assert_type(port.or_else(lambda _e: host), fx.Config[int | str])
    assert_type(port.nested("server"), fx.Config[int])
    assert_type(port.map_effect(lambda p: fx.succeed(p + 1)), fx.Config[int])
    port.map_effect(lambda p: fx.fail(NotFound("x")))  # pyright: ignore[reportArgumentType]
    assert_type(port.flat_map(lambda p: host if p == 80 else config.succeed("dev")), fx.Config[str])
    assert_type(port.flat_map(lambda p: fx.succeed(str(p))), fx.Effect[str, config.ConfigError])
    assert_type(
        port.flat_map(lambda _p: fx.fail(NotFound("x"))),
        fx.Effect[Never, config.ConfigError | NotFound],
    )
    assert_type(config.option(port), fx.Config[fx.Option[int]])
    # The method is Config.option too (DOGFOOD B3), not Effect.option.
    assert_type(port.option(), fx.Config[fx.Option[int]])
    assert_type(config.all(port, host), fx.Config[tuple[int, str]])
    assert_type(config.all(*[port, port]), fx.Config[tuple[int, ...]])
    assert_type(config.all(), fx.Config[tuple[()]])
    assert_type(config.all_dict({"port": port}), fx.Config[dict[str, int]])
    assert_type(config.unwrap({"a": port}), fx.Config[Any])
    assert_type(port.parse(fx.config_provider.from_env()), fx.Effect[int, config.ConfigError])
    config.all(port, 5)  # pyright: ignore[reportArgumentType, reportCallIssue]


def check_config_is_an_effect(port: fx.Config[int]) -> None:
    from pyfect import config

    @fx.gen
    def program():
        value = yield from port
        return value + 1

    assert_type(program, fx.Effect[int, config.ConfigError])
    eff: fx.Effect[int, config.ConfigError] = port
    _ = eff
    assert_type(
        port.pipe(fx.catch_tag(config.ConfigError, lambda _e: fx.succeed(0))), fx.Effect[int]
    )


def check_config_gen(port: fx.Config[int], db: fx.Effect[Db, Never, Primary]) -> None:
    from pyfect import config

    @config.gen
    def server():
        host = yield from config.string("HOST")
        p = yield from port
        return f"{host}:{p}"

    assert_type(server, fx.Config[str])

    @config.gen  # pyright: ignore[reportArgumentType]
    def needs_service():
        found = yield from db
        return found

    @config.gen  # pyright: ignore[reportArgumentType]
    def other_error():
        yield from fx.fail(NotFound("x"))
        return 1


# --- Values: Redacted, ByteSize, Brand, case ---------------------------------------------


def check_redacted() -> None:
    from pyfect import redacted

    secret = redacted.make("sk", label="key")
    assert_type(secret, fx.Redacted[str])
    assert_type(redacted.value(secret), str)
    assert_type(secret.pipe(redacted.value), str)
    wide: fx.Redacted[object] = secret
    _ = wide
    assert_type(redacted.wipe_unsafe(secret), bool)
    secret.label = "other"  # pyright: ignore[reportAttributeAccessIssue]


def check_byte_size(unknown: object) -> None:
    from pyfect import byte_size
    from pyfect.byte_size import ByteSize

    size = byte_size.mebibytes(1.5)
    assert_type(size, ByteSize)
    assert_type(byte_size.bytes(10), ByteSize)
    assert_type(byte_size.from_string("1 kB"), ByteSize | None)
    assert_type(byte_size.from_input(1.0), ByteSize | None)
    assert_type(byte_size.sum(size, size), ByteSize)
    assert_type(byte_size.subtract(size, size), ByteSize | None)
    assert_type(byte_size.times(size, 2), ByteSize | None)
    assert_type(byte_size.divide(size, 2), ByteSize | None)
    assert_type(min(size, byte_size.zero), ByteSize)
    assert_type(byte_size.to_unit(size, "KiB"), float)
    assert_type(byte_size.format(size, unit="kB"), str)
    assert_type(byte_size.format(size, system="decimal", unit="MB"), str)
    byte_size.format(size, system="decimal", unit="MiB")  # pyright: ignore[reportCallIssue, reportArgumentType]
    byte_size.format(size, system="binary", unit="MB")  # pyright: ignore[reportCallIssue, reportArgumentType]
    byte_size.to_unit(size, "mb")  # pyright: ignore[reportArgumentType]
    byte_size.bytes(1.5)  # pyright: ignore[reportArgumentType]
    plain: int = size
    _ = plain
    if byte_size.is_byte_size(unknown):
        assert_type(unknown, ByteSize)


def check_brand(value: float) -> None:
    from typing import NewType

    from pyfect import schema as S
    from pyfect.brand import Brand, BrandError
    from pyfect.option import Option
    from pyfect.result import Result

    Int = NewType("Int", float)
    PositiveInt = NewType("PositiveInt", float)
    to_int = Brand[float, Int].make(lambda n: n.is_integer())
    assert_type(to_int, Brand[float, Int])
    assert_type(to_int(1.0), Int)
    assert_type(to_int.option(1.0), Option[Int])
    assert_type(to_int.result(1.0), Result[Int, BrandError])
    positive = Brand[float, Int].check(S.is_greater_than(0).abort())
    Brand[float, Int].check(S.is_min_length(1))  # pyright: ignore[reportArgumentType]
    assert_type(Brand[float, PositiveInt].all(to_int, positive), Brand[float, PositiveInt])
    assert_type(Brand[float, Int].nominal(), Brand[float, Int])
    if to_int.is_(value):
        assert_type(value, Int)
    to_int("1")  # pyright: ignore[reportArgumentType]
    Brand[float, Int].check()  # pyright: ignore[reportCallIssue]
    Brand[str, Int].all(to_int)  # pyright: ignore[reportArgumentType]
    Brand[float, Int].make(lambda n: n.upper())  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownLambdaType]
    # Without the types named, nothing is known: strict mode rejects it.
    Brand.make(lambda n: n)  # pyright: ignore[reportUnknownLambdaType, reportUnknownMemberType]


def check_case() -> None:
    import re

    from pyfect import case

    assert_type(case.snake_case("helloWorld"), str)
    assert_type(case.no_case("a", split=[re.compile("(a)(b)")], transform=str.upper), str)
    case.no_case("a", split="(a)(b)")  # pyright: ignore[reportArgumentType]


# --- Schema ------------------------------------------------------------------------------
# The contract later schema clusters build on (docs/SCHEMA_DESIGN.md).


def check_schema_parameters() -> None:
    from typing import Any as TAny

    from pyfect import schema as S

    # Codec[T, E = T, RD = Never, RE = Never]
    assert_type(S.String, S.Bottom[str, str, Never, Never])
    assert_type(S.Number, S.Bottom[float])
    assert_type(S.BigInt, S.Bottom[int])
    assert_type(S.Boolean, S.Bottom[bool])
    assert_type(S.Null, S.Bottom[None])
    assert_type(S.Unknown, S.Bottom[object])
    assert_type(S.Any, S.Bottom[TAny])
    assert_type(S.Never, S.Bottom[Never])
    # Covariant in all four: a narrower schema is a wider one.
    wide: S.Bottom[object, object, object, object] = S.String
    narrow: S.Bottom[str] = S.Unknown  # pyright: ignore[reportAssignmentType]
    # Schema[T] / Decoder[T, RD] / Encoder[E, RE] leave the rest open.
    as_schema: S.Schema[str] = S.String
    as_decoder: S.Decoder[float] = S.Number
    as_encoder: S.Encoder[float] = S.Number
    not_str: S.Schema[str] = S.Number  # pyright: ignore[reportAssignmentType]
    _ = (wide, narrow, as_schema, as_decoder, as_encoder, not_str)
    assert_type(S.String.annotate(title="name"), S.Bottom[str])
    assert_type(S.String.pipe(lambda s: s.ast), S.ast.AST)


def check_schema_decoders(unknown: object) -> None:
    from pyfect import schema as S
    from pyfect.option import Option
    from pyfect.result import Result

    assert_type(S.decode_unknown_sync(S.String), S.Parser[object, str])
    assert_type(S.decode_unknown_sync(S.String)(unknown, errors="all"), str)
    assert_type(S.decode_sync(S.String)("a"), str)
    S.decode_sync(S.String)(1)  # pyright: ignore[reportArgumentType]
    assert_type(S.decode_unknown_exit(S.String)(unknown), fx.Exit[str, S.SchemaError])
    assert_type(S.decode_unknown_option(S.String)(unknown), Option[str])
    assert_type(S.decode_unknown_result(S.String)(unknown), Result[str, S.SchemaError])
    assert_type(S.decode_unknown_effect(S.String)(unknown), fx.Effect[str, S.SchemaError, Never])
    assert_type(S.encode_sync(S.Number), S.Parser[float, float])
    assert_type(S.encode_unknown_result(S.Number)(unknown), Result[float, S.SchemaError])
    S.encode_sync(S.Number)("a")  # pyright: ignore[reportArgumentType]
    S.decode_unknown_sync(S.String, errors="some")  # pyright: ignore[reportArgumentType]
    S.decode_unknown_sync(S.String, exact=True)  # pyright: ignore[reportCallIssue]
    guard = S.is_(S.String)
    if guard(unknown):
        assert_type(unknown, str)
    assert_type(S.String.make("a"), str)
    S.String.make(1)  # pyright: ignore[reportArgumentType]
    assert_type(S.String.make_option("a"), Option[str])
    assert_type(S.String.make_effect("a"), fx.Effect[str, S.issue.Issue])


def check_schema_services(unknown: object) -> None:
    from pyfect import schema as S

    # A schema needing a service to decode (Primary) and to encode (Port).
    needs: S.Bottom[int, str, Primary, Port] = S.Bottom(S.ast.unknown)
    assert_type(S.decode_unknown_effect(needs)(unknown), fx.Effect[int, S.SchemaError, Primary])
    assert_type(S.decode_effect(needs), S.Parser[str, fx.Effect[int, S.SchemaError, Primary]])
    assert_type(S.encode_effect(needs), S.Parser[int, fx.Effect[str, S.SchemaError, Port]])
    # The synchronous adapters run no services: such a schema is rejected.
    S.decode_unknown_sync(needs)  # pyright: ignore[reportArgumentType]
    S.encode_unknown_exit(needs)  # pyright: ignore[reportArgumentType]
    # Schema assertions run once ``provide`` gave each direction its service.
    fx.testing.SchemaAsserts(needs).decoding().succeed(unknown)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    fx.testing.SchemaAsserts(needs).decoding().provide(Port, 1).succeed(unknown)  # pyright: ignore[reportArgumentType]
    # The effectful round trip needs both directions' services; the synchronous one none.
    assert_type(
        fx.testing.SchemaAsserts(needs).verify_round_trip_effect(),
        fx.Effect[None, Never, Primary | Port],
    )
    fx.testing.SchemaAsserts(needs).verify_round_trip()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    decode_only: S.Bottom[int, str, Primary] = S.Bottom(S.ast.unknown)
    assert_type(S.encode_unknown_sync(decode_only)(unknown), str)


def check_schema_codec_protocol(unknown: object) -> None:
    """A class is a schema through a ``__codec__`` classmethod: the shape
    schema classes (``S.Class``) will have."""
    from collections.abc import Mapping
    from typing import Self

    from pyfect import schema as S

    class Record:
        @classmethod
        def __codec__(cls) -> S.Bottom[Self, Mapping[str, object]]:
            return S.Bottom(S.ast.unknown)

    assert_type(S.decode_unknown_sync(Record)(unknown), Record)
    assert_type(S.decode_sync(Record), S.Parser[Mapping[str, object], Record])
    assert_type(S.encode_sync(Record), S.Parser[Record, Mapping[str, object]])
    as_schema: S.Schema[Record] = Record
    _ = as_schema


def stream_any(e: NotFound | Invalid) -> stream.Stream[int]:
    return stream.succeed(0)


def stream_rest(e: Invalid) -> stream.Stream[int]:
    return stream.succeed(0)


def layer_any(e: NotFound | Invalid) -> layer.Layer[Port]:
    return layer.succeed(Port, 0)


def layer_rest(e: Invalid) -> layer.Layer[Port]:
    return layer.succeed(Port, 0)


def check_catch_all_pipeables(
    s: stream.Stream[str, NotFound | Invalid], live: layer.Layer[Port, NotFound | Invalid]
) -> None:
    # Stream and Layer spell catch_all as Effect does (both a method and a pipeable).
    assert_type(s.pipe(stream.catch_all(stream_any)), stream.Stream[str | int, Never, Never])
    s.pipe(stream.catch_all(stream_rest))  # pyright: ignore[reportArgumentType]
    assert_type(live.pipe(layer.catch_all(layer_any)), layer.Layer[Port, Never, Never])
    live.pipe(layer.catch_all(layer_rest))  # pyright: ignore[reportArgumentType]


def check_literals_sequence_form() -> None:
    # Effect's sequence form (DOGFOOD B1) keeps the literals too.
    assert_type(S.Literals(["a", "b"]), S.LiteralsSchema[Literal["a", "b"]])
    assert_type(S.Literals(("a", "b")), S.LiteralsSchema[Literal["a", "b"]])
    assert_type(S.Literals("a", "b").pick(["a"]), S.LiteralsSchema[Literal["a", "b"]])
    S.Literals([object()])  # pyright: ignore[reportArgumentType, reportCallIssue]
    S.Literals("a", "b").pick(["c"])  # pyright: ignore[reportArgumentType, reportCallIssue]
    # Union and config.literal take Effect's sequence form too.
    assert_type(S.Union([S.String, S.Int]), S.UnionSchema[str | int, str | int, Never, Never])
    assert_type(S.Union((S.String,)), S.UnionSchema[str, str, Never, Never])
    S.Union([1])  # pyright: ignore[reportArgumentType, reportCallIssue]
    from pyfect import config

    env: fx.Config[Literal["dev", "prod"]] = config.literal(["dev", "prod"], name="ENV")
    _ = env


def check_schema_checks(unknown: object) -> None:
    import enum
    from collections.abc import Mapping, Sized
    from datetime import datetime
    from typing import Literal, NewType

    from pyfect import schema as S
    from pyfect.brand import Brand

    # A check keeps the schema's type; it must accept that type (checks are
    # contravariant: a check on Sized fits a str schema).
    assert_type(S.String.check(S.is_min_length(1), S.is_trimmed()), S.Bottom[str])
    assert_type(S.is_min_length(1), S.Filter[Sized])
    assert_type(S.is_greater_than(1), S.Filter[float])
    assert_type(S.is_greater_than_date(datetime.now()), S.Filter[datetime])
    assert_type(S.is_int32(), S.FilterGroup[float])
    assert_type(S.is_property_names(S.String), S.Filter[Mapping[Any, object]])
    S.String.check(S.is_greater_than(1))  # pyright: ignore[reportArgumentType]
    S.Number.check(S.is_trimmed())  # pyright: ignore[reportArgumentType]
    S.String.check()  # pyright: ignore[reportCallIssue]
    on_str: S.Filter[str] = S.make_filter(lambda s: s.isupper() or "lower")
    assert_type(S.make_filter_group(on_str, S.is_min_length(1)), S.FilterGroup[str])
    assert_type(on_str.and_(S.is_trimmed()), S.FilterGroup[str])
    assert_type(on_str.abort(), S.Filter[str])

    def big(n: int) -> str:
        return f"{n}n"

    assert_type(S.make_is_greater_than(formatter=big), S.Bound[int])
    assert_type(S.Int, S.Bottom[int])
    assert_type(S.Finite, S.Bottom[float])
    assert_type(S.Port, S.Bottom[int])

    # Literals keep their values; numbers need the type written out.
    assert_type(S.Literal("a"), S.LiteralSchema[Literal["a"]])
    assert_type(S.Literals("a", "b"), S.LiteralsSchema[Literal["a", "b"]])
    S.Literals("a", "b").pick("c")  # pyright: ignore[reportArgumentType, reportCallIssue]
    assert_type(S.decode_unknown_sync(S.Literals("a", "b"))(unknown), Literal["a", "b"])
    assert_type(S.Literals(1, 2), S.LiteralsSchema[int])
    ones: S.LiteralsSchema[Literal[1, 2]] = S.Literals(1, 2)
    S.Literal(b"a")  # pyright: ignore[reportArgumentType]
    S.Literal(("a",))  # pyright: ignore[reportArgumentType]

    class Color(enum.Enum):
        RED = "red"

    assert_type(S.Enum(Color), S.EnumSchema[Color])
    assert_type(S.decode_unknown_sync(S.Enum(Color))(unknown), Color)
    assert_type(S.encode_sync(S.Enum(Color))(Color.RED), str | int | float)
    S.Enum(int)  # pyright: ignore[reportArgumentType]

    assert_type(S.Union(S.String, S.Number), S.UnionSchema[str | float, str | float, Never, Never])
    assert_type(
        S.Union(S.String).map_members(lambda ms: (*ms, S.Boolean)),
        S.UnionSchema[str | bool, str | bool, Never, Never],
    )

    def is_a(s: str) -> TypeIs[Literal["a"]]:
        return s == "a"

    assert_type(S.String.pipe(S.refine(is_a)), S.Bottom[Literal["a"], str])
    S.Number.pipe(S.refine(is_a))  # pyright: ignore[reportArgumentType]

    Small = NewType("Small", float)
    small = Brand[float, Small].check(S.is_less_than(10))
    assert_type(S.Number.pipe(S.from_brand(small)), S.Bottom[Small, float])
    S.String.pipe(S.from_brand(small))  # pyright: ignore[reportArgumentType]
    assert_type(S.resolve_annotations(S.String), S.ast.Annotations | None)
    _ = ones


def check_schema_structs(unknown: object) -> None:
    """A TypedDict declares a struct: its Type is exact, its Encoded a
    ``Mapping[str, object]``; keyword schemas carry their services."""
    from collections.abc import Mapping
    from typing import NotRequired, TypedDict

    from pyfect import schema as S

    class UserDict(TypedDict):
        id: int
        nick: NotRequired[str]

    users = S.Struct(UserDict)
    assert_type(users, S.StructSchema[UserDict, Never, Never])
    assert_type(S.decode_unknown_sync(users)(unknown), UserDict)
    assert_type(S.encode_sync(users), S.Parser[UserDict, Mapping[str, object]])
    assert_type(users.make({"id": 1}), UserDict)
    users.make({"nick": "a"})  # pyright: ignore[reportArgumentType]
    assert_type(users.fields, Mapping[str, S.Bottom[object, object, Never, Never]])
    needs: S.Bottom[int, str, Primary, Never] = S.Bottom(S.ast.unknown)
    assert_type(S.Struct(UserDict, id=needs), S.StructSchema[UserDict, Primary, Never])
    S.decode_unknown_sync(S.Struct(UserDict, id=needs))  # pyright: ignore[reportArgumentType]
    S.Struct(int)  # pyright: ignore[reportCallIssue, reportArgumentType]
    checked = users.check(S.make_filter(lambda u: u["id"] > 0))
    assert_type(checked, S.StructSchema[UserDict, Never, Never])
    assert_type(S.String.annotate_key(message_missing_key="required"), S.Bottom[str])


type _Tree = dict[str, _Tree]


def check_schema_records(unknown: object) -> None:
    from collections.abc import Mapping
    from typing import Literal

    from pyfect import schema as S

    scores = S.Record(S.String, S.Number)
    assert_type(scores, S.RecordSchema[str, float, str, float, Never, Never])
    assert_type(S.decode_unknown_sync(scores)(unknown), dict[str, float])
    assert_type(S.encode_sync(scores), S.Parser[dict[str, float], Mapping[str, float]])
    keyed = S.Record(S.Literals("a", "b"), S.Boolean)
    assert_type(S.decode_unknown_sync(keyed)(unknown), dict[Literal["a", "b"], bool])

    tree: S.Bottom[_Tree, object] = S.Record(S.String, S.suspend(lambda: tree))
    assert_type(S.suspend(lambda: S.Number), S.Bottom[float])
    _ = tree


def check_schema_classes(unknown: object) -> None:
    """A schema class is a frozen, keyword-only dataclass and its own schema
    (``Codec[Self, Mapping[str, object]]``)."""
    from collections.abc import Mapping

    from pyfect import schema as S
    from pyfect.option import Option

    class User(S.Class):
        id: int
        name: str
        score: float = S.field(S.Finite)
        nick: str | None = None

        @S.class_check(expected="a short name")
        def short_name(self) -> bool:
            return len(self.name) < 10

    user = User(id=1, name="a", score=1.0)
    User(id=1, name="a")  # pyright: ignore[reportCallIssue]
    User(id="1", name="a", score=1.0)  # pyright: ignore[reportArgumentType]
    User(1, "a", 1.0)  # pyright: ignore[reportCallIssue]
    user.id = 2  # pyright: ignore[reportAttributeAccessIssue]
    assert_type(user.short_name(), bool)
    assert_type(S.decode_unknown_sync(User)(unknown), User)
    assert_type(S.encode_sync(User), S.Parser[User, Mapping[str, object]])
    assert_type(User.make(user), User)
    assert_type(User.make_option(user), Option[User])
    assert_type(User.make_effect(user), fx.Effect[User, S.issue.Issue])
    assert_type(User.check(S.make_filter(lambda u: u.id > 0)), S.Bottom[User, Mapping[str, object]])
    assert_type(User.annotate(title="user"), S.Bottom[User, Mapping[str, object]])
    assert_type(User.pipe(S.decode_unknown_sync), S.Parser[object, User])
    as_schema: S.Schema[User] = User
    assert_type(
        S.Union(User, S.Null), S.UnionSchema[User | None, Mapping[str, object] | None, Never, Never]
    )

    class Wrong(S.Class):
        name: str = S.field(S.Int)  # pyright: ignore[reportAssignmentType]

    needs: S.Bottom[int, str, Primary, Never] = S.Bottom(S.ast.unknown)

    class NeedsServices(S.Class):
        id: int = S.field(needs)  # pyright: ignore[reportArgumentType, reportUnknownVariableType]

    class Mutable(S.Class, frozen=False):
        count: int = 0

    counter = Mutable()
    counter.count = 1

    class Admin(User):
        level: int

    assert_type(S.decode_unknown_sync(Admin)(unknown), Admin)
    Admin(id=1, name="a", score=1.0)  # pyright: ignore[reportCallIssue]

    class Circle(S.TaggedClass, tag="circle"):
        radius: float

    assert_type(Circle(radius=1).radius, float)
    _ = (as_schema, Wrong, NeedsServices)


class _NotFound(fx.schema.TaggedError):
    id: int


class _Invalid(fx.schema.Error):
    message: str


def check_schema_errors(failing: fx.Effect[int, _NotFound | _Invalid]) -> None:
    """``S.TaggedError`` subclasses are ``pyfect.errors.TaggedError``s:
    yieldable and removed by ``catch_tag``."""
    from pyfect import schema as S

    def find() -> Generator[Any, Any, int]:
        return (yield from _NotFound(id=1))

    found = fx.gen(find)
    recovered = failing.pipe(fx.catch_tag(_NotFound, lambda e: fx.succeed(e.id)))
    assert_type(recovered, fx.Effect[int, _Invalid, Never])
    assert_type(S.decode_unknown_sync(_NotFound)(None), _NotFound)
    _NotFound(id=1).id = 2  # pyright: ignore[reportAttributeAccessIssue]
    _ = found


def check_schema_composites(unknown: object) -> None:
    """Tuples are exact up to eight elements; an optional element (or more
    elements) joins them. Arrays decode to tuples, ``List`` to a list."""
    from collections.abc import Mapping, Sequence
    from datetime import datetime, timedelta, tzinfo

    from pyfect import schema as S
    from pyfect.byte_size import ByteSize
    from pyfect.cause import Cause, Reason
    from pyfect.option import Option
    from pyfect.redacted import Redacted
    from pyfect.result import Result

    pair = S.Tuple(S.String, S.Number)
    assert_type(pair, S.TupleSchema[tuple[str, float], tuple[str, float], Never, Never])
    assert_type(S.decode_unknown_sync(pair)(unknown), tuple[str, float])
    assert_type(S.Tuple(), S.TupleSchema[tuple[()], tuple[()], Never, Never])
    assert_type(
        S.Tuple(S.String, S.optional_key(S.Number)),
        S.TupleSchema[tuple[str | float, ...], tuple[str | float, ...], Never, Never],
    )
    assert_type(
        S.TupleWithRest(pair, S.Boolean),
        S.TupleWithRestSchema[
            tuple[str, float, *tuple[bool, ...]], tuple[str, float, *tuple[bool, ...]], Never, Never
        ],
    )
    assert_type(
        S.TupleWithRest(S.Tuple(S.String), S.Boolean, S.Number),
        S.TupleWithRestSchema[
            tuple[str, *tuple[bool, ...], float], tuple[str, *tuple[bool, ...], float], Never, Never
        ],
    )
    # A rest element is never optional.
    S.TupleWithRest(pair, S.optional_key(S.Boolean))  # pyright: ignore[reportCallIssue, reportArgumentType]
    assert_type(
        pair.map_elements(lambda es: (*es, S.Boolean)),
        S.TupleSchema[tuple[object, ...], tuple[object, ...], Never, Never],
    )

    assert_type(S.decode_unknown_sync(S.Array(S.String))(unknown), tuple[str, ...])
    assert_type(S.decode_sync(S.Array(S.Number)), S.Parser[Sequence[float], tuple[float, ...]])
    assert_type(S.decode_unknown_sync(S.List(S.String))(unknown), list[str])
    assert_type(
        S.decode_unknown_sync(S.NonEmptyArray(S.String))(unknown), tuple[str, *tuple[str, ...]]
    )
    assert_type(S.Array(S.String).value, S.Codec[str, str, Never, Never])
    assert_type(
        S.UniqueArray(S.Int).check(S.is_min_length(1)),
        S.ArraySchema[tuple[int, ...], int, int, Never, Never],
    )
    S.Array(S.String).check(S.is_trimmed())  # pyright: ignore[reportArgumentType]

    assert_type(S.decode_unknown_sync(S.FrozenSet(S.Int))(unknown), frozenset[int])
    assert_type(S.decode_unknown_sync(S.Map(S.Int, S.String))(unknown), dict[int, str])
    assert_type(S.encode_sync(S.Map(S.Int, S.String)), S.Parser[dict[int, str], Mapping[int, str]])

    assert_type(S.decode_unknown_sync(S.Option(S.Int))(unknown), Option[int])
    assert_type(S.decode_unknown_sync(S.Result(S.Int, S.String))(unknown), Result[int, str])
    exceptions = S.instance_of(Exception)
    assert_type(exceptions, S.Bottom[Exception])
    assert_type(S.decode_unknown_sync(S.Cause(S.String, exceptions))(unknown), Cause[str])
    assert_type(S.decode_unknown_sync(S.CauseReason(S.String, exceptions))(unknown), Reason[str])
    assert_type(
        S.decode_unknown_sync(S.Exit(S.Int, S.String, exceptions))(unknown), fx.Exit[int, str]
    )
    # A Die holds an exception: the defect schema must make one.
    S.Cause(S.String, S.Unknown)  # pyright: ignore[reportArgumentType]
    assert_type(S.decode_unknown_sync(S.Redacted(S.String))(unknown), Redacted[str])

    assert_type(S.Duration, S.Bottom[timedelta])
    assert_type(S.DateTimeUtc, S.Bottom[datetime])
    assert_type(S.TimeZone, S.Bottom[tzinfo])
    assert_type(S.ByteSize, S.Bottom[ByteSize])
    assert_type(S.decode_unknown_sync(S.Json)(unknown), S.JsonValue)
    loaded: Json = {"a": [1, None]}
    as_json: S.JsonValue = loaded
    _ = as_json

    def is_str(value: object) -> TypeIs[str]:
        return isinstance(value, str)

    assert_type(S.declare(is_str, expected="text"), S.Bottom[str])


def check_schema_completeness_pass() -> None:
    from pyfect import schema as S

    ensured = S.ArrayEnsure(S.FiniteFromString)
    assert_type(ensured, S.DecodeToSchema[tuple[float, ...], str | tuple[str, ...], Never, Never])
    assert_type(S.FiniteFromString.annotate_encoded(title="t"), S.DecodeToSchema[float, str])
    assert_type(S.resolve_annotations_key(S.String), S.ast.Annotations | None)


def check_schema_classes_are_covariant() -> None:
    """A schema needing no services is a schema needing some, and a schema of
    a narrower type one of a wider type: every schema class is covariant, so
    combinators sharing one ``RD`` / ``RE`` accept parts that need fewer."""
    from pyfect import schema as S

    def pins(
        *,
        needs_db: S.Codec[int, str, Db, Never],
        pair: S.TupleSchema[tuple[str, float], tuple[str, float], Never, Never],
        rest: S.TupleWithRestSchema[tuple[str, *tuple[bool, ...]], tuple[str], Never, Never],
        array: S.ArraySchema[tuple[str, ...], str, str, Never, Never],
        frozen: S.FrozenSetSchema[str, str, Never, Never],
        mapping: S.MapSchema[str, int, str, int, Never, Never],
        record: S.RecordSchema[str, int, str, int, Never, Never],
        struct: S.StructSchema[dict[str, int], Never, Never],
        union: S.UnionSchema[str, str, Never, Never],
        option: S.OptionSchema[str, str, Never, Never],
        result: S.ResultSchema[str, int, str, int, Never, Never],
        reason: S.CauseReasonSchema[str, str, Never, Never],
        cause_: S.CauseSchema[str, str, Never, Never],
        exit_: S.ExitSchema[str, int, str, int, Never, Never],
        secret: S.RedactedSchema[str, str, Never, Never],
    ) -> None:
        assert_type(
            S.TupleWithRest(S.Tuple(S.String), needs_db),
            S.TupleWithRestSchema[
                tuple[str, *tuple[int, ...]], tuple[str, *tuple[str, ...]], Db, Never
            ],
        )
        _1: S.TupleSchema[tuple[object, object], tuple[object, ...], Db, object] = pair
        _2: S.TupleWithRestSchema[tuple[object, ...], tuple[object, ...], Db, object] = rest
        _3: S.ArraySchema[tuple[object, ...], object, object, Db, object] = array
        _4: S.FrozenSetSchema[object, object, Db, object] = frozen
        _5: S.MapSchema[str, int, str, object, Db, object] = mapping
        _6: S.RecordSchema[str, int, str, object, Db, object] = record
        _7: S.StructSchema[dict[str, int], Db, object] = struct
        _8: S.UnionSchema[object, object, Db, object] = union
        _11: S.OptionSchema[object, object, Db, object] = option
        _12: S.ResultSchema[object, object, object, object, Db, object] = result
        _13: S.CauseReasonSchema[object, object, Db, object] = reason
        _14: S.CauseSchema[object, object, Db, object] = cause_
        _15: S.ExitSchema[object, object, object, object, Db, object] = exit_
        _16: S.RedactedSchema[object, object, Db, object] = secret

    _ = pins


def check_schema_transformations(db: Db) -> None:
    from pyfect import schema as S
    from pyfect.option import Option, Some
    from pyfect.schema import getter as G
    from pyfect.schema import transformation as T
    from pyfect.schema.issue import Issue

    # Codecs: decoded type first, encoded second.
    assert_type(S.NumberFromString, S.DecodeToSchema[float, str])
    assert_type(S.FiniteFromString.to, S.Codec[float, object])
    assert_type(S.flip(S.NumberFromString), S.FlipSchema[str, float, Never, Never])
    assert_type(S.flip(S.flip(S.NumberFromString)), S.Codec[float, str])
    assert_type(S.OptionFromNullOr(S.String), S.DecodeToSchema[Option[str], str | None])
    assert_type(
        S.OptionFromOptionalNullOr(S.FiniteFromString), S.DecodeToSchema[Option[float], str | None]
    )
    assert_type(S.OptionFromOptionalKey(S.String), S.DecodeToSchema[Option[str], str])

    # Getters and transformations compose end to end; a mismatch is an error.
    length: G.Getter[int, str] = G.transform(len)
    assert_type(G.trim().compose(length), G.Getter[int, str])
    G.number().compose(length)  # pyright: ignore[reportArgumentType]
    assert_type(T.trim().compose(T.to_lower_case()), T.Transformation[str, str])
    assert_type(T.number_from_string.flip(), T.Transformation[str, float])

    # ``decode_to`` checks that the transformation meets both schemas and
    # joins the services each side needs.
    to_int: T.Transformation[int, str] = T.Transformation(G.transform(int), G.transform(str))
    assert_type(S.String.pipe(S.decode_to(S.Int, to_int)), S.DecodeToSchema[int, str])
    S.Number.pipe(S.decode_to(S.Int, to_int))  # pyright: ignore[reportArgumentType]

    def from_db(value: str, options: S.ParseOptions) -> fx.Effect[int, Issue, Primary]:
        return Primary().map(lambda _: len(value))

    needs_db: T.Transformation[int, str, Primary] = T.Transformation(
        G.transform_effect(from_db), G.transform(str)
    )
    assert_type(
        S.String.pipe(S.decode_to(S.Int, needs_db)), S.DecodeToSchema[int, str, Primary, Never]
    )

    # A middleware replaces the services it provides; catching adds its own.
    def fallback(issue: Issue) -> fx.Effect[Option[str], Issue, Port]:
        return Port().map(lambda port: Some(str(port)))

    assert_type(S.String.pipe(S.catch_decoding(fallback)), S.Bottom[str, str, Port, Never])

    def provide_port(
        parse: fx.Effect[Option[str], Issue, Port], options: S.ParseOptions
    ) -> fx.Effect[Option[str], Issue]:
        return parse.pipe(fx.provide_service(Port, 1))

    caught = S.String.pipe(S.catch_decoding(fallback))
    assert_type(caught.pipe(S.middleware_decoding(provide_port)), S.Bottom[str, str, Never, Never])

    # A decoding default needing a service puts it on the decoding side.
    with_db = S.FiniteFromString.pipe(S.with_decoding_default_key(Primary().map(lambda _: "1")))
    assert_type(with_db, S.DecodeToSchema[float, str, Primary, Never])
    S.FiniteFromString.pipe(S.with_decoding_default_key(fx.succeed(1)))  # pyright: ignore[reportArgumentType]
    _ = db


def schema_errors_and_tagged_unions() -> None:
    from collections.abc import Mapping
    from typing import Literal, TypedDict, assert_never

    from pyfect import schema as S
    from pyfect.cause import Cause

    unknown: object = None

    # Errors in JSON decode to data (S.ErrorInstance), never to a class the
    # input names; a defect is a DecodedDefect, since a Die holds an exception.
    assert_type(S.decode_unknown_sync(S.ErrorInstance)(unknown), BaseException | S.ErrorInstance)
    assert_type(
        S.ErrorInstance.schema(include_stack=True), S.Bottom[BaseException | S.ErrorInstance]
    )
    assert_type(S.Defect(), S.DecodeToSchema[BaseException, S.JsonValue, Never, Never])
    assert_type(S.decode_unknown_sync(S.Cause(S.String, S.Defect()))(unknown), Cause[str])
    assert_type(
        S.decode_unknown_sync(S.Exit(S.Int, S.ErrorInstance, S.Defect()))(unknown),
        fx.Exit[int, BaseException | S.ErrorInstance],
    )
    assert_type(S.DecodedDefect("a").value, S.ErrorInstance | S.JsonValue)

    class Circle(TypedDict):
        _tag: Literal["Circle"]
        radius: float

    class Square(TypedDict):
        _tag: Literal["Square"]
        side: float

    class Point(S.TaggedClass):
        x: int

    circle = S.TaggedStruct(Circle)
    assert_type(circle, S.TaggedStructSchema[Circle, Never, Never])
    assert_type(
        S.TaggedStruct(Square, side=S.FiniteFromString), S.TaggedStructSchema[Square, Never, Never]
    )
    shapes = S.TaggedUnion(circle, S.TaggedStruct(Square))
    assert_type(shapes, S.TaggedUnionSchema[Circle | Square, Mapping[str, object], Never, Never])
    assert_type(
        S.Union(circle, S.Struct(Square)).pipe(S.to_tagged_union("_tag")),
        S.TaggedUnionSchema[Circle | Square, Mapping[str, object], Never, Never],
    )
    assert_type(
        S.TaggedUnion(Point, circle),
        S.TaggedUnionSchema[Point | Circle, Mapping[str, object], Never, Never],
    )
    assert_type(shapes.is_any_of("Circle"), Callable[[Circle | Square], bool])
    shape = S.decode_unknown_sync(shapes)(unknown)
    if shapes.guards["Circle"](unknown):
        assert_type(unknown, Circle | Square)

    # Exhaustive matching is Python's match statement: a missing case is an error.
    def area(shape: Circle | Square) -> float:
        match shape:
            case {"_tag": "Circle"}:
                return 3.14 * shape["radius"] ** 2
            case {"_tag": "Square"}:
                return shape["side"] ** 2
            case _:
                assert_never(shape)

    def partial(shape: Circle | Square) -> float:
        match shape:
            case {"_tag": "Circle"}:
                return shape["radius"]
            case _:
                assert_never(shape)  # pyright: ignore[reportArgumentType]

    _ = (area(shape), partial(shape))
    assert_type(S.tag_default_omit("A"), S.DecodeToSchema[Literal["A"], Literal["A"], Never, Never])

    # StructWithRest keeps the struct's TypedDict (an open type); PEP 728's
    # extra_items types the other keys.
    with_rest = S.StructWithRest(S.Struct(Circle), S.Record(S.String, S.Number))
    assert_type(with_rest, S.StructWithRestSchema[Circle, Never, Never])
    S.StructWithRest(S.Record(S.String, S.Number), S.Record(S.String, S.Number))  # pyright: ignore[reportArgumentType]


# --- JSON Pointer, JSON Patch, JSON Schema -------------------------------------------------


def json_tools() -> None:
    from typing import Literal

    from pyfect import json_patch, json_pointer, json_schema

    assert_type(json_pointer.parse_uri_fragment("#/a"), list[str] | None)
    assert_type(json_pointer.format_uri_fragment(["a"]), str)
    patch = json_patch.get({"a": 1}, {"a": 2})
    assert_type(patch, list[json_patch.JsonPatchOperation])
    assert_type(json_patch.apply(patch, {"a": 1}), json_patch.JsonValue)
    json_patch.apply([{"op": "move", "path": "/a"}], {})  # pyright: ignore[reportArgumentType]

    doc = json_schema.from_schema_draft_07({"type": "string"})
    assert_type(doc, json_schema.Document[Literal["draft-2020-12"]])
    assert_type(json_schema.to_document_draft_07(doc), json_schema.Document[Literal["draft-07"]])
    assert_type(json_schema.to_document_draft_04(doc), json_schema.Document[Literal["draft-04"]])
    draft_07 = json_schema.to_document_draft_07(doc)
    json_schema.to_document_draft_04(draft_07)  # pyright: ignore[reportArgumentType]
    multi = json_schema.MultiDocument("draft-2020-12", (doc.schema,), {})
    assert_type(
        json_schema.to_multi_document_open_api_3_1(multi),
        json_schema.MultiDocument[Literal["openapi-3.1"]],
    )


def schema_equivalence_and_formatter() -> None:
    from collections.abc import Callable
    from datetime import timedelta

    from pyfect import schema as S

    # Both derivations are typed by the schema's decoded side.
    assert_type(S.to_equivalence(S.FiniteFromString), Callable[[float, float], bool])
    assert_type(S.to_formatter(S.Duration), Callable[[timedelta], str])
    # An override is checked against the schema's values.
    assert_type(
        S.String.override_to_equivalence(lambda: lambda a, b: a[:1] == b[:1]),
        S.Bottom[str, str, Never, Never],
    )
    S.String.override_to_formatter(lambda: lambda n: f"{n + 1}")  # pyright: ignore[reportOperatorIssue]
    S.Number.override_to_equivalence(lambda: str.__eq__)  # pyright: ignore[reportArgumentType]
    S.to_equivalence(1)  # pyright: ignore[reportArgumentType]


def schema_json() -> None:
    from datetime import timedelta
    from typing import Literal

    from pyfect import json_schema
    from pyfect import schema as S
    from pyfect.json_patch import JsonValue

    # The JSON codec keeps the type and requirements; its encoded side is JSON.
    assert_type(S.to_codec_json(S.Duration), S.Bottom[timedelta, JsonValue, Never, Never])
    assert_type(S.to_codec_json(S.FiniteFromString), S.Bottom[float, JsonValue, Never, Never])
    assert_type(
        S.to_json_schema_document(S.String),
        json_schema.Document[Literal["draft-2020-12"]],
    )
    assert_type(
        S.to_json_schema_multi_document((S.String, S.Number)),
        json_schema.MultiDocument[Literal["draft-2020-12"]],
    )
    # A multi-document has at least one root (Effect's non-empty tuple).
    S.to_json_schema_multi_document(())  # pyright: ignore[reportArgumentType]
    S.to_json_schema_document(S.String, on_excess_property="strip")  # pyright: ignore[reportArgumentType]
    S.to_codec_json(1)  # pyright: ignore[reportArgumentType]
    # The string-tree codec keeps the type; its encoded side is a string tree.
    assert_type(S.to_codec_string_tree(S.Int), S.Bottom[int, S.StringTree, Never, Never])
    assert_type(S.to_codec_string_tree(S.Duration), S.Bottom[timedelta, S.StringTree, Never, Never])
    S.to_codec_string_tree("x")  # pyright: ignore[reportArgumentType]


def check_schema_adapters() -> None:
    import msgspec
    import pydantic

    from pyfect import msgspec as M
    from pyfect import pydantic as P
    from pyfect import schema as S
    from pyfect.json_patch import JsonValue

    class Item(pydantic.BaseModel):
        sku: str

    class Line(msgspec.Struct):
        sku: str

    # Each adapter is a schema of the library's type, read from JSON values.
    assert_type(P.from_model(Item), S.Bottom[Item, JsonValue])
    assert_type(M.from_struct(Line), S.Bottom[Line, JsonValue])
    assert_type(S.decode_unknown_sync(S.Array(M.from_struct(Line)))([]), tuple[Line, ...])
    P.from_model(Line)  # pyright: ignore[reportArgumentType]
    M.from_struct(Item)  # pyright: ignore[reportArgumentType]


# --- Hypothesis strategies, optics ----------------------------------------------------------


def schema_strategies() -> None:
    from hypothesis.strategies import SearchStrategy

    from pyfect import schema as S

    assert_type(S.to_strategy(S.Int), SearchStrategy[int])
    assert_type(S.to_strategy(S.NumberFromString), SearchStrategy[float])
    assert_type(S.to_strategy(S.Array(S.String)), SearchStrategy[tuple[str, ...]])


def optics() -> None:
    from typing import TypedDict

    from pyfect import optic
    from pyfect.option import Option
    from pyfect.result import Result

    class Point(TypedDict):
        x: int
        tags: list[str]

    point = optic.Id[Point]()
    assert_type(point, optic.Id[Point])
    x = point.key("x")
    assert_type(x.get({"x": 1, "tags": []}), Any)
    positive = optic.Id[int]().check(fx.schema.is_greater_than(0))
    assert_type(positive, optic.Prism[int, int])
    assert_type(x.compose(optic.Id[Any]()), optic.Lens[Point, Any])
    maybe = optic.Id[int | None]().not_none()
    assert_type(maybe, optic.Prism[int | None, int])
    some = optic.Id[Option[int]]().compose(optic.some())
    assert_type(some, optic.Prism[Option[int], int])
    success = optic.Id[Result[int, str]]().compose(optic.success())
    assert_type(success, optic.Prism[Result[int, str], int])
    each = optic.Id[list[int]]().for_each(lambda item: item.check(fx.schema.is_int()))
    assert_type(each.get_all([1]), list[int])
    positive.get(1)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    x.set(1)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def check_transactions() -> None:
    ref = fx.TxRef(1)
    assert_type(ref, fx.TxRef[int])
    assert_type(fx.TxRef.make("a"), fx.Effect[fx.TxRef[str], Never, Never])
    assert_type(ref.get(), fx.Effect[int, Never, Never])
    assert_type(ref.set(2), fx.Effect[None, Never, Never])
    assert_type(ref.update(lambda n: n + 1), fx.Effect[None, Never, Never])
    assert_type(ref.modify(lambda n: (str(n), n + 1)), fx.Effect[str, Never, Never])
    assert_type(fx.tx_retry, fx.Effect[Never, Never, fx.Transaction])

    @fx.fn
    def retrying():
        meta = yield from fx.Transaction()
        assert_type(meta.retry_reason, fx.transaction.TransactionRetryReason | None)
        if (yield from ref.get()) == 0:
            return (yield from fx.tx_retry)
        return meta.attempt

    assert_type(retrying(), fx.Effect[int, Never, fx.Transaction])
    assert_type(fx.tx(retrying()), fx.Effect[int, Never, Never])
    assert_type(fx.tx(retrying().zip(Port())), fx.Effect[tuple[int, int], Never, Port])
    assert_type(fx.tx(ref.get()), fx.Effect[int, Never, Never])
    ref.set("a")  # pyright: ignore[reportArgumentType]
    widened_tx_ref: fx.TxRef[object] = ref  # pyright: ignore[reportAssignmentType]
    del widened_tx_ref


def check_tx_collections(
    chunk: fx.TxChunk[int],
    tx_map: fx.TxHashMap[str, int],
    tx_set: fx.TxHashSet[str],
    optional_map: fx.TxHashMap[str, fx.option.Option[bytes]],
) -> None:
    assert_type(fx.TxChunk.make([1, 2]), fx.Effect[fx.TxChunk[int], Never, Never])
    assert_type(fx.TxChunk[str].empty(), fx.Effect[fx.TxChunk[str], Never, Never])
    assert_type(chunk.get(), fx.Effect[tuple[int, ...], Never, Never])
    assert_type(chunk.modify(lambda c: (len(c), c)), fx.Effect[int, Never, Never])
    assert_type(chunk.concat(chunk), fx.Effect[None, Never, Never])
    chunk.append("a")  # pyright: ignore[reportArgumentType]
    widened_chunk: fx.TxChunk[object] = chunk  # pyright: ignore[reportAssignmentType]
    del widened_chunk

    assert_type(fx.TxHashMap.make(("a", 1)), fx.Effect[fx.TxHashMap[str, int], Never, Never])
    assert_type(fx.TxHashMap[str, int].empty(), fx.Effect[fx.TxHashMap[str, int], Never, Never])
    assert_type(tx_map.get("a"), fx.Effect[fx.option.Option[int], Never, Never])
    assert_type(tx_map.remove("a"), fx.Effect[bool, Never, Never])
    assert_type(tx_map.modify("a", lambda n: n + 1), fx.Effect[fx.option.Option[int], Never, Never])
    assert_type(tx_map.entries(), fx.Effect[list[tuple[str, int]], Never, Never])
    assert_type(
        tx_map.find_first(lambda v, k: v > 1), fx.Effect[tuple[str, int] | None, Never, Never]
    )
    assert_type(tx_map.map(lambda v, k: str(v)), fx.Effect[fx.TxHashMap[str, str], Never, Never])
    assert_type(
        tx_map.filter_map(lambda v, k: fx.Ok(float(v)) if v else fx.Err(k)),
        fx.Effect[fx.TxHashMap[str, float], Never, Never],
    )
    assert_type(optional_map.compact(), fx.Effect[fx.TxHashMap[str, bytes], Never, Never])
    tx_map.compact()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    assert_type(tx_map.for_each(lambda v, k: fx.fail(k).zip(Port())), fx.Effect[None, str, Port])
    assert_type(
        tx_map.flat_map(lambda v, k: fx.fail(1).and_then(fx.TxHashMap.make((k, str(v))))),
        fx.Effect[fx.TxHashMap[str, str], int, Never],
    )
    assert_type(tx_map.reduce(0.0, lambda acc, v, k: acc + v), fx.Effect[float, Never, Never])
    tx_map.set("a", "b")  # pyright: ignore[reportArgumentType]

    def is_bool(value: int | bool, key: str) -> TypeIs[bool]:
        return isinstance(value, bool)

    mixed = fx.TxHashMap[str, int | bool](fx.TxRef(HashMap[str, int | bool].empty()))
    assert_type(mixed.filter(is_bool), fx.Effect[fx.TxHashMap[str, bool], Never, Never])

    assert_type(fx.TxHashSet.make("a"), fx.Effect[fx.TxHashSet[str], Never, Never])
    assert_type(fx.TxHashSet[int].empty(), fx.Effect[fx.TxHashSet[int], Never, Never])
    assert_type(tx_set.to_hash_set(), fx.Effect[HashSet[str], Never, Never])
    assert_type(tx_map.snapshot(), fx.Effect[HashMap[str, int], Never, Never])
    tx_map.union({"a": 1})  # pyright: ignore[reportArgumentType]
    assert_type(tx_set.remove("a"), fx.Effect[bool, Never, Never])
    assert_type(
        tx_set.union(fx.TxHashSet[int](fx.TxRef(HashSet[int].empty()))),
        fx.Effect[fx.TxHashSet[str | int], Never, Never],
    )
    assert_type(tx_set.map(len), fx.Effect[fx.TxHashSet[int], Never, Never])
    assert_type(tx_set.reduce(0, lambda acc, v: acc + len(v)), fx.Effect[int, Never, Never])
    tx_set.add(1)  # pyright: ignore[reportArgumentType]


def check_tx_queue(
    queue: fx.TxQueue[int, str],
    ended: fx.TxQueue[int, fx.Done],
    mixed: fx.TxQueue[int, str | fx.Done],
) -> None:
    assert_type(fx.TxQueue[int].bounded(2), fx.Effect[fx.TxQueue[int, Never], Never, Never])
    assert_type(
        fx.TxQueue[int, fx.Done].unbounded(), fx.Effect[fx.TxQueue[int, fx.Done], Never, Never]
    )
    assert_type(queue.offer(1), fx.Effect[bool, Never, Never])
    assert_type(queue.offer_all([1, 2]), fx.Effect[list[int], Never, Never])
    assert_type(queue.take(), fx.Effect[int, str, Never])
    assert_type(queue.poll(), fx.Effect[fx.option.Option[int], Never, Never])
    assert_type(queue.take_n(2), fx.Effect[list[int], str, Never])
    assert_type(queue.clear(), fx.Effect[list[int], str, Never])
    assert_type(ended.clear(), fx.Effect[list[int], Never, Never])
    assert_type(mixed.clear(), fx.Effect[list[int], str, Never])
    assert_type(ended.end(), fx.Effect[bool, Never, Never])
    assert_type(mixed.end(), fx.Effect[bool, Never, Never])
    assert_type(queue.await_completion(), fx.Effect[None, Never, Never])
    queue.end()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    queue.offer("a")  # pyright: ignore[reportArgumentType]

    def drain(dequeue: fx.TxDequeue[float, object]) -> None:
        assert_type(dequeue.take_all(), fx.Effect[Sequence[float], object, Never])

    def clear_view(
        ended_view: fx.TxDequeue[int, fx.Done], mixed_view: fx.TxDequeue[int, str | fx.Done]
    ) -> None:
        assert_type(ended_view.clear(), fx.Effect[Sequence[int], Never, Never])
        assert_type(mixed_view.clear(), fx.Effect[Sequence[int], str, Never])

    clear_view(ended, mixed)

    def produce(enqueue: fx.TxEnqueue[bool, str]) -> None:
        assert_type(enqueue.offer(True), fx.Effect[bool, Never, Never])

    drain(queue)
    produce(queue)
    widened_queue: fx.TxQueue[object, str] = queue  # pyright: ignore[reportAssignmentType]
    del widened_queue


def check_tx_coordination(
    deferred: fx.TxDeferred[int, str],
    semaphore: fx.TxSemaphore,
    lock: fx.TxReentrantLock,
    pq: fx.TxPriorityQueue[str],
) -> None:
    assert_type(fx.TxDeferred[int].make(), fx.Effect[fx.TxDeferred[int, Never], Never, Never])
    assert_type(deferred.wait(), fx.Effect[int, str, Never])
    assert_type(deferred.poll(), fx.Effect[fx.option.Option[fx.Result[int, str]], Never, Never])
    assert_type(deferred.done(fx.Err("e")), fx.Effect[bool, Never, Never])
    deferred.fail(1)  # pyright: ignore[reportArgumentType]

    assert_type(fx.TxSemaphore.make(2), fx.Effect[fx.TxSemaphore, Never, Never])
    assert_type(
        semaphore.with_permit(fx.fail("e").zip(Port())), fx.Effect[tuple[Never, int], str, Port]
    )
    assert_type(semaphore.with_permit_scoped(), fx.Effect[None, Never, fx.Scope])

    assert_type(lock.acquire_read(), fx.Effect[int, Never, Never])
    assert_type(lock.write_lock(), fx.Effect[int, Never, fx.Scope])
    assert_type(
        lock.with_read_lock(fx.succeed("a").zip(Port())), fx.Effect[tuple[str, int], Never, Port]
    )

    assert_type(fx.TxPriorityQueue.make(3, 1), fx.Effect[fx.TxPriorityQueue[int], Never, Never])
    assert_type(
        fx.TxPriorityQueue.from_iterable([b"a"], key=len),
        fx.Effect[fx.TxPriorityQueue[bytes], Never, Never],
    )
    assert_type(fx.TxPriorityQueue[str].empty(), fx.Effect[fx.TxPriorityQueue[str], Never, Never])
    assert_type(pq.take(), fx.Effect[str, Never, Never])
    assert_type(pq.take_up_to(2), fx.Effect[list[str], Never, Never])
    assert_type(pq.peek_option(), fx.Effect[fx.option.Option[str], Never, Never])
    fx.TxPriorityQueue.make(object())  # pyright: ignore[reportArgumentType]
    fx.TxPriorityQueue[object].empty()  # pyright: ignore[reportCallIssue]
    pq.offer(1)  # pyright: ignore[reportArgumentType]


def check_tx_pubsub(hub: fx.TxPubSub[int], ref: fx.TxSubscriptionRef[str]) -> None:
    assert_type(fx.TxPubSub[int].bounded(2), fx.Effect[fx.TxPubSub[int], Never, Never])
    assert_type(hub.capacity, int | None)
    assert_type(hub.publish(1), fx.Effect[bool, Never, Never])
    assert_type(hub.publish_all(iter([1, 2])), fx.Effect[bool, Never, Never])
    assert_type(hub.subscribe(), fx.Effect[fx.TxDequeue[int, Never], Never, fx.Scope])
    assert_type(hub.acquire_subscriber(), fx.Effect[fx.TxDequeue[int, Never], Never, Never])
    assert_type(hub.await_shutdown(), fx.Effect[None, Never, Never])
    hub.publish("a")  # pyright: ignore[reportArgumentType]
    widened_hub: fx.TxPubSub[object] = hub  # pyright: ignore[reportAssignmentType]
    del widened_hub

    assert_type(fx.TxSubscriptionRef.make(1), fx.Effect[fx.TxSubscriptionRef[int], Never, Never])
    assert_type(ref.modify(lambda s: (len(s), s + "!")), fx.Effect[int, Never, Never])
    assert_type(ref.update_and_get(str.upper), fx.Effect[str, Never, Never])
    assert_type(ref.changes(), fx.Effect[fx.TxDequeue[str, Never], Never, fx.Scope])
    assert_type(ref.changes_stream(), fx.Stream[str, Never, Never])
    ref.set(1)  # pyright: ignore[reportArgumentType]


def check_platform(
    fs: fx.file_system.FileSystemService,
    file: fx.file_system.File,
    paths: fx.path.PathService,
    io: fx.stdio.StdioService,
    term: fx.terminal.TerminalService,
) -> None:
    from pyfect import file_system, platform, platform_error, stdio, terminal

    assert_type(
        fx.FileSystem(), TagEffect[file_system.FileSystemService, fx.FileSystem, fx.FileSystem]
    )
    assert_type(fs.read_file("a"), fx.Effect[bytes, fx.PlatformError, Never])
    assert_type(fs.read_file_string("a"), fx.Effect[str, fx.PlatformError, Never])
    assert_type(fs.exists("a"), fx.Effect[bool, fx.PlatformError, Never])
    assert_type(fs.stat("a"), fx.Effect[file_system.FileInfo, fx.PlatformError, Never])
    assert_type(fs.open("a", flag="a+"), fx.Effect[file_system.File, fx.PlatformError, fx.Scope])
    assert_type(fs.make_temp_directory_scoped(), fx.Effect[str, fx.PlatformError, fx.Scope])
    assert_type(fs.stream("a"), fx.Stream[bytes, fx.PlatformError, Never])
    assert_type(fs.sink("a"), fx.Sink[None, bytes, Never, fx.PlatformError, Never])
    assert_type(fs.watch("a"), fx.Stream[file_system.WatchEvent, fx.PlatformError, Never])
    assert_type(file.read_alloc(5), fx.Effect[bytes | None, fx.PlatformError, Never])
    assert_type(file.seek(5, "current"), fx.Effect[int, fx.PlatformError, Never])
    fs.open("a", flag="rw")  # pyright: ignore[reportArgumentType]
    fs.read_file(1)  # pyright: ignore[reportArgumentType]
    file.seek(0, "end")  # pyright: ignore[reportArgumentType]
    assert_type(file_system.layer, fx.Layer[fx.FileSystem])
    assert_type(file_system.layer_noop(), fx.Layer[fx.FileSystem])

    error = platform_error.system_error("NotFound", module="FileSystem", method="stat")
    assert_type(error, fx.PlatformError)
    assert_type(error.reason, platform_error.BadArgument | platform_error.SystemError)
    platform_error.system_error("Missing", module="m", method="m")  # pyright: ignore[reportArgumentType]
    assert_type(
        fs.read_file_string("a").pipe(
            fx.catch_reason(
                fx.PlatformError, platform_error.NotFound, lambda _r, _e: fx.succeed("")
            )
        ),
        fx.Effect[str, fx.PlatformError, Never],
    )

    assert_type(paths.join("a", "b"), str)
    assert_type(paths.resolve_within("/srv", "a"), str | None)
    assert_type(paths.from_file_url("file:///a"), fx.Effect[str, platform_error.BadArgument, Never])
    assert_type(fx.path.layer, fx.Layer[fx.Path])

    assert_type(io.args, fx.Effect[tuple[str, ...], Never, Never])
    assert_type(io.stdout(), fx.Sink[None, str | bytes, Never, fx.PlatformError, Never])
    assert_type(io.stdin, fx.Stream[bytes, fx.PlatformError, Never])
    assert_type(stdio.layer_test(), fx.Layer[fx.Stdio])

    assert_type(term.read_line, fx.Effect[str, terminal.QuitError, Never])
    assert_type(
        term.read_input, fx.Effect[fx.Dequeue[terminal.UserInput, fx.Done], Never, fx.Scope]
    )
    assert_type(term.display("x"), fx.Effect[None, fx.PlatformError, Never])
    assert_type(platform.layer, fx.Layer[platform.PlatformServices])

    def lines(logger: fx.Logger[str], numbers: fx.Logger[int]) -> None:
        assert_type(
            logger.to_file("app.log"),
            fx.Effect[fx.Logger[None], fx.PlatformError, fx.Scope | fx.FileSystem],
        )
        numbers.to_file("x")  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

    del lines


def check_process(
    handle: fx.process.ChildProcessHandle, spawner: fx.process.ChildProcessSpawnerService
) -> None:
    from pyfect import process
    from pyfect.process import ChildProcessHandle, ChildProcessSpawner, ExitCode

    command = process.make("echo", ["hello"], cwd="/tmp", force_kill_after=0.5)
    assert_type(command, process.StandardCommand)
    assert_type(command.options.force_kill_after, Seconds | None)
    assert_type(command.pipe_to(process.make("cat"), from_="stderr"), process.PipedCommand)
    assert_type(command.set_cwd("/"), process.Command)
    spawned: fx.Effect[ChildProcessHandle, fx.PlatformError, ChildProcessSpawner | fx.Scope] = (
        command
    )
    del spawned
    assert_type(
        fx.scoped(command.flat_map(lambda h: h.exit_code)),
        fx.Effect[ExitCode, fx.PlatformError, ChildProcessSpawner],
    )
    assert_type(handle.exit_code, fx.Effect[ExitCode, fx.PlatformError, Never])
    assert_type(handle.stdout, fx.Stream[bytes, fx.PlatformError, Never])
    assert_type(handle.stdin, fx.Sink[None, bytes, Never, fx.PlatformError, Never])
    assert_type(handle.kill(force_kill_after=1), fx.Effect[None, fx.PlatformError, Never])
    assert_type(handle.unref, fx.Effect[fx.Effect[None, fx.PlatformError], fx.PlatformError, Never])
    assert_type(spawner.string(command), fx.Effect[str, fx.PlatformError, Never])
    assert_type(spawner.lines(command), fx.Effect[list[str], fx.PlatformError, Never])
    assert_type(spawner.stream_lines(command), fx.Stream[str, fx.PlatformError, Never])
    assert_type(process.layer, fx.Layer[ChildProcessSpawner, Never, fx.FileSystem | fx.Path])
    process.make("echo", stdin="closed")  # pyright: ignore[reportArgumentType]
    process.make("echo", stdout=stream.make(b"x"))  # pyright: ignore[reportArgumentType]
    command.pipe_to(command, from_="stdin")  # pyright: ignore[reportArgumentType]
    handle.kill(kill_signal="SIGKILL")  # pyright: ignore[reportArgumentType]


def check_http_client(service: fx.http.HttpClientService[fx.http.HttpClientError]) -> None:
    from typing import TypedDict

    from pyfect import schema as S
    from pyfect.http import client, httpx_client, request, response
    from pyfect.http.error import HttpClientError, TransportError
    from pyfect.http.response import HttpClientResponse

    class Todo(TypedDict):
        id: int

    assert_type(
        client.HttpClient(),
        TagEffect[client.HttpClientService[HttpClientError], client.HttpClient, client.HttpClient],
    )
    assert_type(
        client.get("/todos"), fx.Effect[HttpClientResponse, HttpClientError, client.HttpClient]
    )
    assert_type(service.get("/"), fx.Effect[HttpClientResponse, HttpClientError, Never])
    assert_type(service.filter_status_ok(), client.HttpClientService[HttpClientError])
    assert_type(service.retry_transient(times=3), client.HttpClientService[HttpClientError, Never])
    assert_type(
        service.catch_all(lambda e: fx.succeed(e.response or response.make(e.request))),
        client.HttpClientService[Never],
    )
    assert_type(
        service.map_request_effect(lambda r: fx.fail(KeyError()).as_(r)),
        client.HttpClientService[HttpClientError | KeyError],
    )
    tagged = service.map_request_effect(lambda r: fx.fail(KeyError()).as_(r)).pipe(
        client.catch_tag(KeyError, lambda _: fx.succeed(response.make(request.get("/"))))
    )
    assert_type(tagged, client.HttpClientService[HttpClientError])
    assert_type(
        service.pipe(client.transform_response(lambda eff: eff.map_error(lambda _: "failed"))),
        client.HttpClientService[str],
    )
    assert_type(
        service.get("/").flat_map(response.schema_body_json(S.Struct(Todo))),
        fx.Effect[Todo, HttpClientError | S.SchemaError, Never],
    )
    assert_type(request.post("/").body_text("x"), request.HttpClientRequest)
    assert_type(request.post("/").compress_body("gzip"), fx.Effect[request.HttpClientRequest])
    assert_type(httpx_client.layer, fx.Layer[client.HttpClient])
    assert_type(TransportError(request.get("/")).request, request.HttpClientRequest)
    request.get("/", method="GET")  # pyright: ignore[reportCallIssue]
    request.make("FETCH", "/")  # pyright: ignore[reportArgumentType]
    request.post("/").compress_body("brotli")  # pyright: ignore[reportArgumentType]


def check_net_socket(
    service: dns.DnsService,
    resolver: address_resolver.AddressResolverService,
    sock: socket_module.SocketService,
    srv: socket_module.server.SocketServerService,
) -> None:
    from ipaddress import IPv4Address, IPv6Address

    assert_type(
        service.lookup("example.com", family="IPv4"),
        fx.Effect[tuple[IPv4Address, ...], dns.DnsError],
    )
    assert_type(
        service.lookup("example.com", family="IPv6"),
        fx.Effect[tuple[IPv6Address, ...], dns.DnsError],
    )
    assert_type(service.resolve("example.com", dns.Mx), fx.Effect[tuple[dns.Mx, ...], dns.DnsError])
    assert_type(
        resolver.resolve("db:5432", family="IPv4"),
        fx.Effect[
            tuple[net_address.InetAddressV4, ...], net_address.NetAddressError | dns.DnsError
        ],
    )
    assert_type(
        socket_module.reader_bytes(sock),
        fx.Effect[
            fx.Effect[tuple[bytes, ...], socket_module.SocketError],
            socket_module.SocketError,
            fx.Scope,
        ],
    )
    assert_type(socket_module.to_stream(sock), Stream[bytes, socket_module.SocketError])
    assert_type(
        srv.run(lambda s: s.reader.as_void()),
        fx.Effect[Never, socket_module.server.SocketServerError, fx.Scope],
    )
    assert_type(
        socket_module.make_web_socket("ws://localhost:8080"),
        fx.Effect[socket_module.SocketService, Never, socket_module.WebSocketConstructor],
    )
    assert_type(
        socket_module.from_web_socket(
            fx.fail(socket_module.SocketError(socket_module.SocketCloseError(1006)))
        ),
        socket_module.SocketService,
    )
    socket_module.from_web_socket(fx.succeed(1))  # pyright: ignore[reportArgumentType]
    service.resolve("example.com", str)  # pyright: ignore[reportArgumentType]
    service.lookup("example.com", family="IPv5")  # pyright: ignore[reportArgumentType, reportCallIssue]


def check_datagram_socket(
    udp: dg.DatagramSocketService, reader: dg.Reader, writer: dg.Writer
) -> None:
    from ipaddress import IPv4Address, IPv6Address

    assert_type(dg.make_udp(), fx.Effect[dg.DatagramSocketService])
    assert_type(udp.reader, fx.Effect[dg.Reader, dg.DatagramSocketError, fx.Scope])
    assert_type(reader.pull, fx.Effect[tuple[dg.Datagram, ...], dg.DatagramSocketError])
    assert_type(writer.write(dg.OutgoingDatagram("hi")), fx.Effect[None, dg.DatagramSocketError])
    assert_type(
        reader.join_multicast(IPv6Address("ff02::1"), interface=2),
        fx.Effect[None, dg.DatagramSocketError, fx.Scope],
    )

    def open_scoped(
        _events: dg.BackingEvents,
    ) -> fx.Effect[dg.BackingSocket, dg.DatagramSocketError, fx.Scope]: ...

    def open_needing_clock(
        _events: dg.BackingEvents,
    ) -> fx.Effect[dg.BackingSocket, dg.DatagramSocketError, fx.Scope | fx.Clock]: ...

    # The reader's Scope is provided by the core; other services remain.
    assert_type(dg.make_from_backing_socket(open_scoped), fx.Effect[dg.DatagramSocketService])
    assert_type(
        dg.make_from_backing_socket(open_needing_clock),
        fx.Effect[dg.DatagramSocketService, Never, fx.Clock],
    )
    # An IPv4 group takes an IPv4 interface address, an IPv6 group an index.
    reader.join_multicast(IPv4Address("239.0.0.1"), interface=2)  # pyright: ignore[reportCallIssue, reportArgumentType]
    reader.join_multicast(IPv6Address("ff02::1"), interface=IPv4Address("127.0.0.1"))  # pyright: ignore[reportCallIssue, reportArgumentType]
    # peer and connect cannot be combined: the remote is one or the other.
    both = (dg.Peer(dg.HostPort("a", 1)), dg.Connect(dg.HostPort("a", 1)))
    dg.Options(remote=both)  # pyright: ignore[reportArgumentType]
    dg.ReceiveBuffer(8, "blocking")  # pyright: ignore[reportArgumentType]


def sql_statements(
    sql: sql_client.SqlClientService, sqlite_sql: sql_sqlite.SqliteClientService, table: str
) -> None:
    """SQL text must be a literal: a runtime string cannot be a template, so
    values cannot be spliced into SQL by accident."""
    from pyfect import schema as S

    statement = sql("SELECT * FROM users WHERE id = {}", 1)
    assert_type(statement, Statement[Row])
    assert_type(statement.values, fx.Effect[list[ValueRow], SqlError])
    assert_type(statement.raw, fx.Effect[object, SqlError])
    assert_type(statement.stream, Stream[Row, SqlError])
    sql(table)  # pyright: ignore[reportArgumentType]
    sql("SELECT * FROM " + table)  # pyright: ignore[reportArgumentType]
    sql.unsafe("SELECT * FROM " + table)
    sql("SELECT * FROM {}", sql.identifier(table))
    # A segment placed in a template is SQL text too, so it takes a literal.
    sql("SELECT {}", SqlLiteral(table))  # pyright: ignore[reportArgumentType]
    Fragment([SqlLiteral("SELECT " + table)])  # pyright: ignore[reportArgumentType]
    sql("SELECT {}", SqlLiteral("1"))

    assert_type(sql.with_transaction(fx.succeed(1)), fx.Effect[int, SqlError])
    assert_type(sql.with_transaction(fx.fail("e")), fx.Effect[Never, str | SqlError])
    assert_type(sql.after_commit(fx.void), fx.Effect[None])
    sql.after_commit(fx.fail("e"))  # pyright: ignore[reportArgumentType]
    assert_type(
        reactivity.mutation(statement, ["users"]),
        fx.Effect[list[Row], SqlError, reactivity.Reactivity],
    )
    assert_type(sqlite_sql.backup("copy.db"), fx.Effect[sql_sqlite.BackupMetadata, SqlError])
    # SQLite has no UPDATE ... FROM (VALUES ...): Effect types updateValues as `never`.
    sqlite_sql.update_values([{"id": 1}], "u")  # pyright: ignore[reportDeprecated]
    assert_type(
        sql_sqlite.layer_config({"filename": fx.config.string("DATABASE_PATH")}),
        fx.Layer[sql_sqlite.SqliteClient | sql_client.SqlClient, fx.ConfigError | SqlError],
    )
    assert_type(
        sql_sqlite.make(sql_sqlite.SqliteClientConfig(filename=":memory:")),
        fx.Effect[sql_sqlite.SqliteClientService, SqlError, fx.Scope | reactivity.Reactivity],
    )

    find = sql_schema.find_one_option(
        request=S.Number, result=S.String, execute=lambda _id: fx.succeed([])
    )
    assert_type(find, Callable[[float], fx.Effect[fx.Option[str], S.SchemaError]])
    ordered = sql_resolver.ordered(request=S.Number, result=S.String, execute=lambda _: statement)
    assert_type(
        sql_resolver.request(1, ordered),
        fx.Effect[str, SqlError | ResultLengthMismatch | S.SchemaError],
    )
    assert_type(
        sql_migrator.make()(loader=sql_migrator.from_record({})),
        fx.Effect[
            list[tuple[int, str]],
            sql_migrator.MigrationError | SqlError,
            sql_client.SqlClient,
        ],
    )


def sql_pg_driver(
    pg_sql: sql_pg.PgClientService,
    pool: sql_pg.PgPoolService,
    conn: sql_pg.PgConnection,
    queue: Dequeue[sql_pg.Notification, SqlError],
) -> None:
    """The PostgreSQL driver's services keep their error and requirement
    types; a listener's queue is read-only."""
    notifications = pg_sql.listen("events")
    assert_type(
        notifications,
        fx.Effect[Dequeue[sql_pg.Notification, SqlError], SqlError, fx.Scope],
    )
    assert_type(pg_sql.notify("events", "hi"), fx.Effect[None, SqlError])
    assert_type(conn.query("SELECT 1"), fx.Effect[sql_pg.Result, SqlError])
    assert_type(conn.pin, fx.Effect[sql_pg.PgConnection, Never, fx.Scope])
    assert_type(pool.get, fx.Effect[sql_pg.PgConnection, SqlError, fx.Scope])
    assert_type(pool.use(lambda c: fx.succeed(c.process_id)), fx.Effect[int, SqlError])
    assert_type(
        sql_pg.make(sql_pg.PgPoolConfig()),
        fx.Effect[sql_pg.PgClientService, SqlError, fx.Scope | reactivity.Reactivity],
    )
    assert_type(
        sql_pg.layer(sql_pg.PgPoolConfig()),
        fx.Layer[sql_pg.PgClient | sql_client.SqlClient, SqlError],
    )
    assert_type(conn.stream("SELECT 1"), Stream[dict[str, Any], SqlError])
    assert_type(conn.query_values("SELECT 1"), fx.Effect[list[tuple[Any, ...]], SqlError])
    assert_type(pool.use(lambda _: fx.fail(KeyError("k"))), fx.Effect[Never, KeyError | SqlError])
    assert_type(
        sql_pg.make_client(sql_pg.PgClientConfig()),
        fx.Effect[sql_pg.PgClientService, SqlError, fx.Scope | reactivity.Reactivity],
    )
    assert_type(
        sql_pg.layer_config({}),
        fx.Layer[sql_pg.PgClient | sql_client.SqlClient, fx.ConfigError | SqlError],
    )
    sql_pg.PgConnectionConfig(port="5432")  # pyright: ignore[reportArgumentType]
    sql_pg.PgConnectionConfig(password="secret")  # pyright: ignore[reportArgumentType]
    queue.offer(sql_pg.Notification(1, "events", ""))  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]


def sql_mysql_driver(mysql_sql: sql_mysql.MysqlClientService) -> None:
    """The MySQL driver's constructors keep their error and requirement
    types; the config takes the password only as ``Redacted`` and the port
    only as an ``int``."""
    from pyfect import redacted

    config = sql_mysql.MysqlClientConfig(url=redacted.make("mysql://u:p@db/app"))
    assert_type(
        sql_mysql.make(config),
        fx.Effect[sql_mysql.MysqlClientService, SqlError, fx.Scope | reactivity.Reactivity],
    )
    assert_type(
        sql_mysql.layer(config), fx.Layer[sql_mysql.MysqlClient | sql_client.SqlClient, SqlError]
    )
    assert_type(
        sql_mysql.layer_config({"url": fx.config.redacted("DATABASE_URL")}),
        fx.Layer[sql_mysql.MysqlClient | sql_client.SqlClient, fx.ConfigError | SqlError],
    )
    assert_type(
        sql_mysql.layer_from(sql_mysql.make(config)),
        fx.Layer[sql_mysql.MysqlClient | sql_client.SqlClient, SqlError],
    )
    assert_type(
        sql_mysql.MysqlClient(),
        TagEffect[sql_mysql.MysqlClientService, sql_mysql.MysqlClient, sql_mysql.MysqlClient],
    )
    assert_type(mysql_sql.config, sql_mysql.MysqlClientConfig)
    assert_type(sql_result.affected_rows(sql_mysql.ResultSetHeader(1, 2)), int)
    sql_mysql.MysqlClientConfig(password="secret")  # pyright: ignore[reportArgumentType]
    sql_mysql.MysqlClientConfig(port="3306")  # pyright: ignore[reportArgumentType]


def sql_d1_driver(
    d1_sql: sql_d1.D1ClientService,
    users: Statement[str],
    counts: Statement[int],
) -> None:
    """The D1 driver needs an ``HttpClient``; ``batch`` types each
    statement's rows by position; ``update_values`` is not supported."""
    from pyfect import redacted
    from pyfect.http.client import HttpClient

    config = sql_d1.D1ClientConfig(account_id="a", database_id="d", api_token=redacted.make("t"))
    assert_type(
        sql_d1.make(config),
        fx.Effect[sql_d1.D1ClientService, Never, fx.Scope | reactivity.Reactivity | HttpClient],
    )
    assert_type(
        sql_d1.layer(config), fx.Layer[sql_d1.D1Client | sql_client.SqlClient, Never, HttpClient]
    )
    assert_type(
        sql_d1.layer_config({"account_id": fx.config.string("ACCOUNT")}),
        fx.Layer[sql_d1.D1Client | sql_client.SqlClient, fx.ConfigError, HttpClient],
    )
    assert_type(d1_sql.batch(()), fx.Effect[tuple[()], sql_error.SqlError])
    assert_type(
        d1_sql.batch((users, counts)),
        fx.Effect[tuple[list[str], list[int]], sql_error.SqlError],
    )
    assert_type(d1_sql.batch([users, users]), fx.Effect[tuple[list[str], ...], sql_error.SqlError])
    assert_type(d1_sql.config, sql_d1.D1ClientConfig)
    sql_d1.D1ClientConfig(account_id="a", database_id="d", api_token="t")  # pyright: ignore[reportArgumentType]
    d1_sql.update_values([], "v")  # pyright: ignore[reportDeprecated]


def sql_clickhouse_driver(
    ch_sql: sql_clickhouse.ClickhouseClientService,
    eff: fx.Effect[int, str, sql_client.SqlClient],
) -> None:
    """The ClickHouse driver's constructors keep their error and requirement
    types; ``as_command``, ``with_query_id`` and ``with_clickhouse_settings``
    keep the effect's; the password takes only a ``Redacted``."""
    from pyfect import redacted
    from pyfect.sql.statement import Fragment

    config = sql_clickhouse.ClickhouseClientConfig(
        url="http://localhost:8123", password=redacted.make("secret")
    )
    assert_type(
        sql_clickhouse.make(config),
        fx.Effect[
            sql_clickhouse.ClickhouseClientService,
            sql_error.SqlError,
            fx.Scope | reactivity.Reactivity,
        ],
    )
    assert_type(
        sql_clickhouse.layer(config),
        fx.Layer[sql_clickhouse.ClickhouseClient | sql_client.SqlClient, sql_error.SqlError],
    )
    assert_type(
        sql_clickhouse.layer_config({"url": fx.config.string("CLICKHOUSE_URL")}),
        fx.Layer[
            sql_clickhouse.ClickhouseClient | sql_client.SqlClient,
            fx.ConfigError | sql_error.SqlError,
        ],
    )
    rows = ch_sql("SELECT 1")
    assert_type(ch_sql.as_command(eff), fx.Effect[int, str, sql_client.SqlClient])
    assert_type(ch_sql.with_query_id(eff, "id"), fx.Effect[int, str, sql_client.SqlClient])
    assert_type(
        ch_sql.with_clickhouse_settings(eff, {"max_threads": 2}),
        fx.Effect[int, str, sql_client.SqlClient],
    )
    assert_type(
        ch_sql.insert_query(table="t", values=[{"a": 1}]),
        fx.Effect[sql_clickhouse.InsertResult, sql_error.SqlError],
    )
    assert_type(ch_sql.param("Int32", 1), Fragment)
    assert_type(ch_sql.client, sql_clickhouse.ClickhouseDriver)
    assert_type(
        ch_sql.client.query("SELECT 1", format="JSONEachRow"),
        fx.Effect[sql_clickhouse.ResultSet, sql_clickhouse.ClickhouseError | HttpClientError],
    )
    assert_type(rows.raw, fx.Effect[object, sql_error.SqlError])
    sql_clickhouse.ClickhouseClientConfig(password="secret")  # pyright: ignore[reportArgumentType]
    ch_sql.with_clickhouse_settings(eff, {"max_threads": object()})  # pyright: ignore[reportArgumentType]


def sql_libsql_driver(libsql_sql: sql_libsql.LibsqlClientService) -> None:
    """The libSQL driver opens without a typed error (a database that cannot
    be opened is a defect, as in Effect); the token takes only a
    ``Redacted``, and a live client must be a ``LibsqlSdk``."""
    from pyfect import redacted

    config = sql_libsql.LibsqlClientConfig(
        url="libsql://db.turso.io", auth_token=redacted.make("token")
    )
    assert_type(
        sql_libsql.make(config),
        fx.Effect[sql_libsql.LibsqlClientService, Never, fx.Scope | reactivity.Reactivity],
    )
    assert_type(sql_libsql.layer(config), fx.Layer[sql_libsql.LibsqlClient | sql_client.SqlClient])
    assert_type(
        sql_libsql.layer_config({"url": fx.config.string("LIBSQL_URL")}),
        fx.Layer[sql_libsql.LibsqlClient | sql_client.SqlClient, fx.ConfigError],
    )
    assert_type(
        sql_libsql.LibsqlClient(),
        TagEffect[sql_libsql.LibsqlClientService, sql_libsql.LibsqlClient, sql_libsql.LibsqlClient],
    )
    assert_type(libsql_sql.config, sql_libsql.LibsqlClientConfig | sql_libsql.LibsqlLiveConfig)
    assert_type(libsql_sql.sdk, sql_libsql.LibsqlSdk)
    assert_type(
        sql_libsql.LibsqlLiveConfig(live_client=libsql_sql.sdk).live_client, sql_libsql.LibsqlSdk
    )
    sql_libsql.LibsqlClientConfig(url=":memory:", auth_token="secret")  # pyright: ignore[reportArgumentType]
    sql_libsql.LibsqlLiveConfig(live_client=object())  # pyright: ignore[reportArgumentType]


def sql_mssql_driver(mssql_sql: sql_mssql.MssqlClientService) -> None:
    """The SQL Server driver's constructors keep their error and requirement
    types; a procedure's rows and output parameters keep theirs, and an
    input takes only its parameter's type."""
    from typing import TypedDict

    from pyfect import redacted
    from pyfect.sql.connection import Row
    from pyfect.sql.mssql import TYPES, Parameter, procedure

    class Greeting(TypedDict):
        greeting: str

    config = sql_mssql.MssqlClientConfig(server="db", password=redacted.make("secret"))
    assert_type(
        sql_mssql.make(config),
        fx.Effect[sql_mssql.MssqlClientService, SqlError, fx.Scope | reactivity.Reactivity],
    )
    assert_type(
        sql_mssql.layer(config), fx.Layer[sql_mssql.MssqlClient | sql_client.SqlClient, SqlError]
    )
    assert_type(
        sql_mssql.layer_config({"server": fx.config.string("MSSQL_SERVER")}),
        fx.Layer[sql_mssql.MssqlClient | sql_client.SqlClient, fx.ConfigError | SqlError],
    )
    assert_type(
        sql_mssql.layer_from(sql_mssql.make(config)),
        fx.Layer[sql_mssql.MssqlClient | sql_client.SqlClient, SqlError],
    )
    assert_type(
        sql_mssql.MssqlClient(),
        TagEffect[sql_mssql.MssqlClientService, sql_mssql.MssqlClient, sql_mssql.MssqlClient],
    )
    assert_type(mssql_sql.config, sql_mssql.MssqlClientConfig)

    name = Parameter[str]("name", TYPES.NVarChar)
    answer = Parameter[int]("answer", TYPES.Int)
    greet = procedure.make("greet").param(name).output_param(answer)
    assert_type(
        mssql_sql.call(greet.compile(name("Tim"))), fx.Effect[procedure.Result[Row], SqlError]
    )
    typed = greet.with_rows(Greeting).compile(name("Tim"))
    assert_type(mssql_sql.call(typed), fx.Effect[procedure.Result[Greeting], SqlError])

    def read(result: procedure.Result[Greeting]) -> None:
        assert_type(result.output[answer], int)
        assert_type(result.output["answer"], object)
        assert_type(result.rows[0]["greeting"], str)

    del read
    name(1)  # pyright: ignore[reportArgumentType]
    sql_mssql.MssqlClientConfig(server="db", password="secret")  # pyright: ignore[reportArgumentType]
    sql_mssql.MssqlClientConfig(server="db", port="1433")  # pyright: ignore[reportArgumentType]


# --- cli ---


class CliUsers(Tag[str]): ...


class CliDatabase(Config):
    host = Flag.string("db-host")
    port = Flag.integer("db-port")


class CliDeploy(Config):
    service = Argument.string("service")
    files = Argument.string("files").variadic()
    retries = Flag.integer("retries").optional()
    branch = Flag.string("branch").with_default("main")
    database = nested(CliDatabase)


def cli_read(config: CliDeploy) -> None:
    assert_type(config.service, str)
    assert_type(config.files, tuple[str, ...])
    assert_type(config.retries, int | None)
    assert_type(config.branch, str)
    assert_type(config.database.port, int)
    assert_type(CliDeploy.branch, Flag[str])
    assert_type(Flag.literals("format", ("text", "json")), Flag[Literal["text", "json"]])
    assert_type(Argument.literals("env", ("dev", "prod")), Argument[Literal["dev", "prod"]])


def check_cli_defaults_keep_literals(models: tuple[Literal["haiku", "sonnet"], ...]) -> None:
    # DOGFOOD atlas #5: a default that is one of the literals keeps the literal type.
    model = Flag.literals("model", models)
    assert_type(model.with_default(models[0]), Flag[Literal["haiku", "sonnet"]])
    assert_type(model.with_default("haiku"), Flag[Literal["haiku", "sonnet"]])
    assert_type(model.with_default(fx.succeed(models[0])), Flag[Literal["haiku", "sonnet"]])
    assert_type(model.optional().with_default("haiku"), Flag[Literal["haiku", "sonnet"] | None])
    assert_type(model.with_default(None), Flag[Literal["haiku", "sonnet"] | None])
    assert_type(Flag.integer("n").with_default("auto"), Flag[int | str])
    env = Argument.literals("env", ("dev", "prod"))
    assert_type(env.with_default("dev"), Argument[Literal["dev", "prod"]])
    assert_type(env.with_default(None), Argument[Literal["dev", "prod"] | None])


class CliShared(Config):
    verbose = Flag.boolean("verbose")


class CliClone(Config):
    repository = Argument.string("repository")


class CliNotFound(TaggedError): ...


cli_root = command.make("git").with_shared_flags(CliShared)
assert_type(cli_root, Command[CliShared, CliShared])


def cli_clone_handler(config: CliClone):
    @fx.gen
    def body():
        shared = yield from cli_root
        assert_type(shared, CliShared)
        users = yield from CliUsers()
        level = yield from LogLevel()
        if shared.verbose and level and users:
            yield from fx.fail(CliNotFound())

    return body


cli_clone = command.make("clone", CliClone, cli_clone_handler)
assert_type(cli_clone, Command[CliClone, Config, CliNotFound, CommandContext[CliShared] | CliUsers])


def cli_status_handler():
    shared = yield from cli_root
    return shared


cli_status = command.make("status", Config, lambda _: fx.gen(cli_status_handler))
assert_type(cli_status, Command[Config, Config, Never, CommandContext[CliShared]])

cli_app = cli_root.with_subcommands(cli_clone, cli_status)
assert_type(cli_app, Command[CliShared, CliShared, CliNotFound, CliUsers])

cli_grouped = cli_root.with_subcommands(group("Remote", cli_clone), cli_status)
assert_type(cli_grouped, Command[CliShared, CliShared, CliNotFound, CliUsers])

cli_only_context = cli_root.with_subcommands(cli_status)
assert_type(cli_only_context, Command[CliShared, CliShared, Never, Never])

cli_handled = command.make("plain", CliClone).with_handler(lambda c: fx.succeed(c.repository))
assert_type(cli_handled, Command[CliClone, Config, Never, Never])


class CliTool(CliShared):
    model = Flag.string("model")


cli_tool = command.make("tool", CliTool).with_shared_flags(CliShared)
assert_type(cli_tool, Command[CliTool, CliShared])


class CliRegion(Setting[str]):
    flag = Flag.string("region").with_default("us-east-1")


def cli_region_handler(_: Config):
    return CliRegion().as_void()


cli_regional = command.make("deploy", Config, cli_region_handler)
assert_type(cli_regional, Command[Config, Config, Never, CliRegion])
assert_type(
    cli_regional.pipe(command.with_global_flags(CliRegion)), Command[Config, Config, Never, Never]
)
assert_type(
    command.make("users", Config, lambda _: CliUsers().map(len).as_void()).pipe(
        command.provide_sync(CliUsers, "ada")
    ),
    Command[Config, Config, Never, Never],
)
assert_type(
    command.run_with(cli_app, version="1.0.0"),
    Callable[[Sequence[str]], fx.Effect[None, CliNotFound | CliError, CliUsers | CliEnvironment]],
)
command.make("bad", CliClone, lambda c: fx.succeed(c.missing))  # pyright: ignore[reportAttributeAccessIssue, reportUnknownArgumentType, reportUnknownLambdaType, reportUnknownMemberType]


class CliDb(Tag[str]): ...


def cli_db_layer(config: CliClone) -> fx.Layer[CliDb]:
    return layer.succeed(CliDb, config.repository)


def cli_db_from_deploy(config: CliDeploy) -> fx.Layer[CliDb]:
    return layer.succeed(CliDb, config.service)


cli_needs_db = command.make("db", CliClone, lambda _: CliDb().as_void())
assert_type(cli_needs_db, Command[CliClone, Config, Never, CliDb])
assert_type(
    cli_needs_db.pipe(command.provide(cli_db_layer)), Command[CliClone, Config, Never, Never]
)
cli_needs_db.pipe(command.provide(cli_db_from_deploy))  # pyright: ignore[reportArgumentType]


# --- HttpRouter: route handler errors and requirements flow into the app -------------


class RouteDb(Tag[str]): ...


class RouteCache(Tag[int]): ...


class RouteNotAllowed(Exception): ...


class RouteMissing(Exception): ...


def route_db_handler(
    request: ServerRequest,
) -> fx.Effect[HttpServerResponse, RouteNotAllowed, RouteDb]:
    return RouteDb().map(lambda name: http_server_response.text(name + request.url))


def route_cache_effect() -> fx.Effect[
    HttpServerResponse, RouteMissing, RouteCache | HttpServerRequest
]: ...


route_cache_handler = route_cache_effect()

# The services the router provides (the request, scope, params) are removed.
assert_type(
    http_router.add("GET", "/db", route_db_handler),
    fx.Layer[Never, Never, HttpRouter | Requires[RouteDb] | Raises[RouteNotAllowed]],
)
assert_type(
    http_router.add("GET", "/cache", route_cache_handler),
    fx.Layer[Never, Never, HttpRouter | Requires[RouteCache] | Raises[RouteMissing]],
)
# A handler needing nothing adds nothing.
assert_type(
    http_router.add("GET", "/", http_server_response.text("ok")),
    fx.Layer[Never, Never, HttpRouter],
)
assert_type(
    http_router.route("GET", "/db", route_db_handler),
    http_router.Route[RouteNotAllowed, RouteDb],
)

route_app = http_router.use(
    lambda r: r.add("GET", "/db", route_db_handler).and_then(
        r.add("GET", "/cache", route_cache_handler)
    )
)
assert_type(
    route_app,
    fx.Layer[
        Never,
        Never,
        HttpRouter
        | Requires[RouteDb]
        | Raises[RouteNotAllowed]
        | Requires[RouteCache]
        | Raises[RouteMissing],
    ],
)
assert_type(
    http_router.to_http_effect(route_app),
    fx.Effect[
        fx.Effect[
            HttpServerResponse,
            RouteNotAllowed | RouteMissing | HttpServerError,
            Scope | HttpServerRequest | RouteDb | RouteCache,
        ],
        Never,
        Scope,
    ],
)
# Served, the handlers' requirements are the server layer's.
assert_type(
    http_router.serve(route_app).pipe(layer.provide(layer.succeed(RouteDb, "db"))),
    fx.Layer[Never, Never, HttpServer | RouteCache],
)
assert_type(
    http_router.serve(http_router.add("GET", "/", http_server_response.text("ok"))),
    fx.Layer[Never, Never, HttpServer],
)
assert_type(
    http_router.use(lambda r: r.add("GET", "/db", route_db_handler)),
    fx.Layer[Never, Never, HttpRouter | Requires[RouteDb] | Raises[RouteNotAllowed]],
)


assert_type(
    rpc_server.layer_protocol_stdio,
    layer.Layer[rpc_server.ServerProtocol, Never, fx.Stdio | RpcSerialization],
)
assert_type(
    http_prometheus.layer_http(prefix="app"), layer.Layer[Never, Never, http_router.HttpRouter]
)

# In memory, a route's requirements are the client's; its errors are defects.
assert_type(
    http_router.in_memory_client(route_app),
    fx.Effect[
        fx.http.HttpClientService[fx.http.HttpClientError, RouteDb | RouteCache], Never, Scope
    ],
)
assert_type(
    http_router.in_memory_client(http_router.add("GET", "/", http_server_response.text("ok"))),
    fx.Effect[fx.http.HttpClientService[fx.http.HttpClientError], Never, Scope],
)
assert_type(
    http_router.layer_in_memory_client(http_router.add("GET", "/", fx.fail(RouteNotAllowed()))),
    fx.Layer[fx.http.HttpClient, Never, Never],
)
# A route needing services has no `HttpClient` layer: its client needs them.
http_router.layer_in_memory_client(route_app)  # pyright: ignore[reportArgumentType]


# The routes layer's other requirements pass through `serve` and `to_http_effect`
# (Effect's `Exclude<R, HttpRouter>`, DOGFOOD beacon 5).
class RouteStore(Tag[str]): ...


class RouteGroup(Tag[int]): ...


def check_serve_passes_requirements_through(
    plain: fx.Layer[Never, Never, HttpRouter | RouteStore],
    routes: fx.Layer[
        Never,
        Never,
        HttpRouter
        | Requires[RouteDb]
        | Raises[RouteNotAllowed]
        | Requires[RouteCache]
        | Raises[RouteMissing]
        | RouteStore,
    ],
    groups: fx.Layer[Never, RouteMissing, HttpRouter | RouteGroup | RouteStore],
) -> None:
    assert_type(http_router.serve(plain), fx.Layer[Never, Never, HttpServer | RouteStore])
    assert_type(
        http_router.serve(routes),
        fx.Layer[Never, Never, HttpServer | RouteDb | RouteCache | RouteStore],
    )
    assert_type(
        http_router.serve(groups),
        fx.Layer[Never, RouteMissing, HttpServer | RouteGroup | RouteStore],
    )
    assert_type(
        http_router.serve(routes, middleware=http_middleware.logger),
        fx.Layer[Never, Never, HttpServer | RouteDb | RouteCache | RouteStore],
    )
    assert_type(
        http_router.serve(plain, middleware=http_middleware.compression()),
        fx.Layer[Never, Never, HttpServer | HttpPlatform | RouteStore],
    )
    assert_type(
        http_router.to_http_effect(routes),
        fx.Effect[
            fx.Effect[
                HttpServerResponse,
                RouteNotAllowed | RouteMissing | HttpServerError,
                Scope | HttpServerRequest | RouteDb | RouteCache,
            ],
            Never,
            Scope | RouteStore,
        ],
    )
    # Provided afterwards, the requirement is gone.
    assert_type(
        http_router.serve(plain).pipe(layer.provide(layer.succeed(RouteStore, "s"))),
        fx.Layer[Never, Never, HttpServer],
    )


def check_serve_passes_markers_through(
    toolkit: fx.Layer[Never, Never, HttpRouter | ai_toolkit.Handlers[Literal["Weather"]]],
    for_client: "fx.Layer[Never, Never, HttpRouter | rpc.middleware.ForClient[RpcAuth]]",
) -> None:
    # Requirements that are markers rather than tags (an RPC group's
    # handlers, a toolkit's, a middleware's client side) pass through too,
    # as everything but HttpRouter does in Effect (DOGFOOD trawl 7).
    served = http_router.serve(rpc_server.layer_http(RpcOther, path="/rpc"))
    assert_type(
        served, fx.Layer[Never, Never, HttpServer | RpcSerialization | rpc.HandlersFor[RpcOther]]
    )
    other_handlers = RpcOther.to_layer(
        RpcOther.handlers().handle(RpcOther.pong)(lambda _r: fx.succeed(None))
    )
    assert_type(
        served.pipe(layer.provide(other_handlers)),
        fx.Layer[Never, Never, HttpServer | RpcSerialization],
    )
    assert_type(
        http_router.to_http_effect(rpc_server.layer_http(RpcOther, path="/rpc")),
        fx.Effect[
            fx.Effect[HttpServerResponse, HttpServerError, Scope | HttpServerRequest],
            Never,
            Scope | RpcSerialization | rpc.HandlersFor[RpcOther],
        ],
    )
    assert_type(
        http_router.serve(toolkit),
        fx.Layer[Never, Never, HttpServer | ai_toolkit.Handlers[Literal["Weather"]]],
    )
    assert_type(
        http_router.serve(for_client),
        fx.Layer[Never, Never, HttpServer | rpc.middleware.ForClient[RpcAuth]],
    )


# Router middleware: what it adds to the routes' errors and requirements, and
# nothing (not Unknown) when it adds nothing.
type _RouteIn = fx.Effect[HttpServerResponse, http_router.Unhandled]


def mw_plain(
    h: _RouteIn,
) -> fx.Effect[HttpServerResponse, http_router.Unhandled, HttpServerRequest]: ...
def mw_none(h: _RouteIn) -> fx.Effect[HttpServerResponse, http_router.Unhandled]: ...
def mw_fails(
    h: _RouteIn,
) -> fx.Effect[HttpServerResponse, http_router.Unhandled | RouteNotAllowed, Scope]: ...
def mw_needs(
    h: _RouteIn,
) -> fx.Effect[HttpServerResponse, http_router.Unhandled, HttpServerRequest | RouteDb]: ...
def mw_both(
    h: _RouteIn,
) -> fx.Effect[HttpServerResponse, http_router.Unhandled | RouteNotAllowed, RouteDb]: ...


assert_type(http_router.middleware(mw_plain), http_router.Middleware[Never, Never])
assert_type(http_router.middleware(mw_none), http_router.Middleware[Never, Never])
assert_type(http_router.middleware(mw_fails), http_router.Middleware[RouteNotAllowed, Never])
assert_type(http_router.middleware(mw_needs), http_router.Middleware[Never, RouteDb])
assert_type(http_router.middleware(mw_both), http_router.Middleware[RouteNotAllowed, RouteDb])
assert_type(http_router.middleware(fx.succeed(mw_plain)), http_router.Middleware[Never, Never])
assert_type(
    http_router.middleware(mw_plain).layer,
    fx.Layer[Never, Never, Requires[Never] | Raises[Never]],
)
assert_type(
    http_router.middleware(mw_plain, global_=True),
    fx.Layer[Never, Never, HttpRouter | GlobalRaises[Never]],
)
assert_type(
    http_router.middleware(mw_none, global_=True),
    fx.Layer[Never, Never, HttpRouter | GlobalRaises[Never]],
)
assert_type(
    http_router.middleware(mw_needs, global_=True),
    fx.Layer[Never, Never, HttpRouter | GlobalRequires[RouteDb] | GlobalRaises[Never]],
)
assert_type(
    http_router.middleware(mw_fails, global_=True),
    fx.Layer[Never, Never, HttpRouter | GlobalRaises[RouteNotAllowed]],
)
assert_type(
    http_router.serve(
        http_router.add("GET", "/", http_server_response.text("ok")).pipe(
            layer.provide_merge(http_router.middleware(mw_plain, global_=True))
        )
    ),
    fx.Layer[Never, Never, HttpServer],
)


# --- HttpServer.serve: middleware keeps the app's requirements -----------------------


def served_app() -> fx.Effect[HttpServerResponse, RouteNotAllowed, RouteDb | HttpServerRequest]: ...


def served_plain() -> fx.Effect[HttpServerResponse, RouteNotAllowed, HttpServerRequest]: ...


assert_type(http_server.serve(served_app()), fx.Layer[Never, Never, HttpServer | RouteDb])
assert_type(
    http_server.serve(served_app(), http_middleware.logger),
    fx.Layer[Never, Never, HttpServer | RouteDb],
)
assert_type(
    http_server.serve(served_app(), http_middleware.cors()),
    fx.Layer[Never, Never, HttpServer | RouteDb],
)
# A middleware's own requirements join the app's.
assert_type(
    http_server.serve(served_app(), http_middleware.compression()),
    fx.Layer[Never, Never, HttpServer | RouteDb | HttpPlatform],
)
assert_type(
    http_server.serve(served_plain(), http_middleware.decompression()),
    fx.Layer[Never, Never, HttpServer],
)
assert_type(
    http_server.serve_effect(served_app(), http_middleware.tracer),
    fx.Effect[None, Never, Scope | HttpServer | RouteDb],
)
assert_type(
    http_router.serve(route_app, middleware=http_middleware.cors()),
    fx.Layer[Never, Never, HttpServer | RouteDb | RouteCache],
)
assert_type(
    http_router.serve(route_app, middleware=http_middleware.logger),
    fx.Layer[Never, Never, HttpServer | RouteDb | RouteCache],
)
assert_type(
    http_router.serve(
        http_router.add("GET", "/", http_server_response.text("ok")),
        middleware=http_middleware.compression(),
    ),
    fx.Layer[Never, Never, HttpServer | HttpPlatform],
)
assert_type(
    http_router.serve(
        http_router.add("GET", "/", http_server_response.text("ok")),
        middleware=http_middleware.logger,
    ),
    fx.Layer[Never, Never, HttpServer],
)


# --- ASGI ------------------------------------------------------------------------------


def check_asgi(
    needs_port: fx.Effect[HttpServerResponse, HttpServerError, Port | HttpServerRequest | Scope],
    plain: fx.Effect[HttpServerResponse, HttpServerError, HttpServerRequest],
    host: fx.http.asgi.AsgiApplication,
) -> None:
    from pyfect.http import asgi, uvicorn_server
    from pyfect.http.client import HttpClient
    from pyfect.http.etag import Generator
    from pyfect.path import Path
    from pyfect.socket.server import SocketServerError

    assert_type(asgi.to_asgi(plain), asgi.AsgiApp)
    assert_type(asgi.to_asgi(needs_port, port_live), asgi.AsgiApp)
    # A layer building more than the app needs is fine.
    assert_type(asgi.to_asgi(needs_port, layer.merge(port_live, primary_live)), asgi.AsgiApp)
    # The app's services must come from the layer.
    asgi.to_asgi(needs_port)  # pyright: ignore[reportArgumentType]
    asgi.to_asgi(needs_port, primary_live)  # pyright: ignore[reportArgumentType]
    assert_type(
        asgi.from_asgi(host),
        fx.Effect[HttpServerResponse, HttpServerError, HttpServerRequest],
    )
    assert_type(asgi.lifespan(host), fx.Effect[dict[str, Any], asgi.AsgiLifespanError, Scope])
    assert_type(
        uvicorn_server.layer_test(),
        fx.Layer[
            HttpServer | Path | HttpPlatform | fx.FileSystem | Generator | HttpClient,
            SocketServerError,
        ],
    )
    assert_type(uvicorn_server.layer_server(port=8080), fx.Layer[HttpServer, SocketServerError])


# --- HttpApi ---------------------------------------------------------------------------
# research/typing/httpapi_1_endpoint.py, httpapi_2_middleware.py


class ApiUser(fx.schema.Class, identifier="ApiUser"):
    id: int
    name: str


class ApiUserParams(TypedDict):
    id: int


class ApiNewUser(TypedDict):
    name: str


class ApiCurrentUser(Tag[ApiUser]): ...


class ApiDb(Tag[int]): ...


class ApiAuth(HttpApiMiddleware[ApiCurrentUser, api_error.Unauthorized]):
    error = api_error.Unauthorized


api_get_user = api_endpoint.get(
    "getUser",
    "/users/:id",
    params=fx.schema.Struct(ApiUserParams),
    success=ApiUser,
    error=api_error.NotFound,
)
api_create_user = api_endpoint.post(
    "createUser", "/users", payload=fx.schema.Struct(ApiNewUser), success=ApiUser
)
api_health = api_endpoint.get("health", "/health")
api_guarded = api_get_user.middleware(ApiAuth)


class ApiUsers(HttpApiGroup, identifier="users"):
    get_user = api_get_user
    create_user = api_create_user
    health = api_health
    guarded = api_guarded


class ApiAdmin(HttpApiGroup[ApiAuth], identifier="admin"):
    get_user = api_get_user


type ApiClientErrors = HttpClientError | SchemaError


def check_http_api(
    users: ApiUsers,
    admin: ApiAdmin,
    find: Callable[
        [HttpApiRequest[ApiUserParams, None, None, None]],
        fx.Effect[ApiUser, api_error.NotFound, ApiCurrentUser | ApiDb],
    ],
) -> None:
    from pyfect.http_api import builder as api_builder
    from pyfect.http_api import client as api_client
    from pyfect.http_api._handlers import GroupHandlers

    assert_type(
        api_get_user,
        HttpApiEndpoint[
            ApiUserParams, None, None, None, None, ApiUser, ApiUser, api_error.NotFound, Never
        ],
    )
    assert_type(
        api_guarded,
        HttpApiEndpoint[
            ApiUserParams,
            None,
            None,
            None,
            None,
            ApiUser,
            ApiUser,
            api_error.NotFound,
            ApiAuth,
            ApiAuth,
        ],
    )
    # On a client's group, an endpoint is its client method, typed by its declaration.
    assert_type(
        users.get_user(params={"id": 1}),
        fx.Effect[ApiUser, api_error.NotFound | ApiClientErrors],
    )
    assert_type(users.create_user(payload={"name": "a"}), fx.Effect[ApiUser, ApiClientErrors])
    assert_type(users.health(), fx.Effect[None, ApiClientErrors])
    # The middleware's errors are the client's too, on the endpoint or on its group.
    assert_type(
        users.guarded(params={"id": 1}),
        fx.Effect[ApiUser, api_error.NotFound | api_error.Unauthorized | ApiClientErrors],
    )
    assert_type(
        admin.get_user(params={"id": 1}),
        fx.Effect[ApiUser, api_error.NotFound | api_error.Unauthorized | ApiClientErrors],
    )
    users.get_user()  # pyright: ignore[reportCallIssue]
    users.get_user(params={"id": "1"})  # pyright: ignore[reportArgumentType]
    users.health(params={"id": 1})  # pyright: ignore[reportArgumentType]

    handlers: GroupHandlers[ApiUsers] = GroupHandlers(ApiUsers)
    admin_handlers: GroupHandlers[ApiAdmin] = GroupHandlers(ApiAdmin)
    # A handler's requirements are the group layer's; what its middleware
    # provides is not, the middleware is.
    assert_type(
        handlers.handle(ApiUsers.get_user)(find), Handlers[Never, Never, ApiCurrentUser | ApiDb]
    )
    assert_type(handlers.handle(ApiUsers.guarded)(find), Handlers[Never, Never, ApiAuth | ApiDb])
    assert_type(
        admin_handlers.handle(ApiAdmin.get_user)(find),
        Handlers[ApiCurrentUser, api_error.Unauthorized, ApiAuth | ApiDb],
    )
    assert_type(
        handlers.handle(ApiUsers.health)(lambda _request: fx.succeed(None)),
        Handlers[Never, Never, Never],
    )
    # An undeclared error or success is rejected.
    handlers.handle(ApiUsers.get_user)(  # pyright: ignore[reportCallIssue]
        lambda _request: fx.fail(api_error.Unauthorized())  # pyright: ignore[reportArgumentType]
    )
    handlers.handle(ApiUsers.health)(  # pyright: ignore[reportCallIssue]
        lambda _request: fx.succeed(1)  # pyright: ignore[reportArgumentType]
    )

    # builder.handler returns its callback, typed by the endpoint, for a later handle.
    assert_type(
        api_builder.handler(ApiUsers.get_user, find),
        Callable[
            [HttpApiRequest[ApiUserParams, None, None, None]],
            fx.Effect[
                ApiUser | HttpServerResponse,
                api_error.NotFound
                | api_error.HttpApiSchemaError
                | api_error.HttpApiPayloadTooLarge,
                ApiCurrentUser | ApiDb,
            ],
        ],
    )
    created = api_builder.handler(
        ApiUsers.create_user, lambda r: fx.succeed(ApiUser(id=1, name=r.payload["name"]))
    )
    assert_type(handlers.handle(ApiUsers.create_user)(created), Handlers[Never, Never, Never])
    assert_type(
        handlers.handle(ApiUsers.guarded)(api_builder.handler(ApiUsers.guarded, find)),
        Handlers[Never, Never, ApiAuth | ApiDb],
    )
    api_builder.handler(  # pyright: ignore[reportCallIssue]
        ApiUsers.health,
        lambda _r: fx.succeed(1),  # pyright: ignore[reportArgumentType]
    )

    api = HttpApi.make("api").add(ApiUsers, ApiAdmin)
    assert_type(api, HttpApi[ApiUsers | ApiAdmin])
    assert_type(
        api_builder.group(
            api,
            ApiUsers,
            lambda h: (
                h.handle(ApiUsers.get_user)(find)
                .handle(ApiUsers.create_user)(
                    lambda r: fx.succeed(ApiUser(id=1, name=r.payload["name"]))
                )
                .handle(ApiUsers.health)(lambda _r: fx.succeed(None))
                .handle(ApiUsers.guarded)(find)
            ),
        ),
        fx.Layer[ApiUsers, Never, ApiCurrentUser | ApiDb | ApiAuth],
    )
    assert_type(api_builder.layer(api), fx.Layer[Never, Never, HttpRouter | ApiUsers | ApiAdmin])
    assert_type(
        api_client.make(api), fx.Effect[api_client.Client[ApiUsers | ApiAdmin], Never, HttpClient]
    )
    # A group the api lacks is a type error for the builder and the client (QA types 5).
    users_only = HttpApi.make("users").add(ApiUsers)
    api_builder.group(users_only, ApiAdmin, lambda h: h)  # pyright: ignore[reportCallIssue, reportArgumentType]
    assert_type(api_builder.group(api, ApiAdmin, lambda h: h), fx.Layer[ApiAdmin])

    # Handlers made by an effect that needs nothing need nothing (two solved
    # `Never` requirements joined as `R | RX` come out Unknown).
    def health(h: GroupHandlers[ApiUsers]) -> Handlers[Any, Any, Never]:
        return h.handle(ApiUsers.health)(lambda _r: fx.succeed(None))

    assert_type(
        api_builder.group(api, ApiUsers, lambda h: fx.succeed(health(h))),
        fx.Layer[ApiUsers, Never, Never],
    )
    assert_type(
        api_builder.group(api, ApiUsers, lambda h: ApiDb().map(lambda _: health(h))),
        fx.Layer[ApiUsers, Never, ApiDb],
    )

    def admin_client(http: fx.http.HttpClientService[Any, Any]) -> None:
        api_client.group(users_only, ApiAdmin, http_client=http)  # pyright: ignore[reportArgumentType]
        assert_type(api_client.group(api, ApiAdmin, http_client=http), fx.Effect[ApiAdmin])

    del admin_client


def check_http_api_clients() -> None:
    from pyfect.http_api import builder as api_builder
    from pyfect.http_api import client as api_client
    from pyfect.http_api import get_group
    from pyfect.http_api import test as api_test

    api = HttpApi.make("api").add(ApiUsers, ApiAdmin)
    users_only = HttpApi.make("users").add(ApiUsers)

    # A group of a two-group client is that group, not the union (DOGFOOD beacon 8):
    # `get_group` is a function because pyright solves a method's type variables
    # from `self` first. `client[Group]` is deprecated and typed to reject any group.
    def two_groups(
        both: api_client.Client[ApiUsers | ApiAdmin], users: api_client.Client[ApiUsers]
    ) -> None:
        assert_type(get_group(both, ApiUsers), ApiUsers)
        assert_type(get_group(both, ApiAdmin), ApiAdmin)
        get_group(users, ApiAdmin)  # pyright: ignore[reportArgumentType]
        both[ApiUsers]  # pyright: ignore[reportArgumentType]

        def pick[G: HttpApiGroup[Any, Any]](client: api_client.Client[G], group: type[G]) -> G:
            return get_group(client, group)

        assert_type(pick(both, ApiAdmin), ApiAdmin)
        pick(users, ApiAdmin)  # pyright: ignore[reportArgumentType]

    del two_groups

    # The in-memory client needs the served groups' layers and a Scope (DOGFOOD
    # beacon 10); given `layer`, it needs what the layer needs.
    assert_type(
        api_test.groups(api, (ApiUsers,)),
        fx.Effect[api_client.Client[ApiUsers | ApiAdmin], Never, ApiUsers | Scope],
    )
    assert_type(
        api_test.groups(api, (ApiUsers, ApiAdmin)),
        fx.Effect[api_client.Client[ApiUsers | ApiAdmin], Never, ApiUsers | ApiAdmin | Scope],
    )
    api_test.groups(users_only, (ApiAdmin,))  # pyright: ignore[reportArgumentType]

    def with_layer(
        users_live: fx.Layer[ApiUsers, api_error.NotFound, ApiDb],
        both_live: fx.Layer[ApiUsers | ApiAdmin, Never, ApiDb | ApiAuth],
    ) -> None:
        assert_type(
            api_test.groups(api, (ApiUsers,), layer=users_live),
            fx.Effect[api_client.Client[ApiUsers | ApiAdmin], api_error.NotFound, ApiDb | Scope],
        )
        assert_type(
            api_test.groups(api, (ApiUsers,), layer=both_live),
            fx.Effect[api_client.Client[ApiUsers | ApiAdmin], Never, ApiDb | ApiAuth | Scope],
        )
        # A layer that lacks a served group is rejected.
        api_test.groups(api, (ApiUsers, ApiAdmin), layer=users_live)  # pyright: ignore[reportArgumentType]
        # Served, the groups' requirements are the server's (DOGFOOD beacon 5).
        assert_type(
            http_router.serve(api_builder.layer(api).pipe(layer.provide(both_live))),
            fx.Layer[Never, Never, HttpServer | ApiDb | ApiAuth],
        )

    del with_layer


# --- rpc ---------------------------------------------------------------------------


class RpcUser(fx.schema.Class, identifier="RpcUser"):
    id: str


class RpcCurrentUser(Tag[RpcUser]): ...


class RpcUnauthorized(fx.schema.TaggedError): ...


class RpcAuth(rpc.RpcMiddleware[RpcCurrentUser, RpcUnauthorized]):
    error = RpcUnauthorized


class RpcDb(Tag[int]): ...


class RpcNotFound(fx.schema.TaggedError): ...


class RpcOther(rpc.RpcGroup):
    pong = rpc.make("Pong")


class RpcUsers(rpc.RpcGroup):
    get = rpc.make("Get", payload=fx.schema.String, success=RpcUser, error=RpcNotFound)
    ping = rpc.make("Ping")
    stream = rpc.make("Stream", success=fx.schema.Number, stream=True)
    me = rpc.make("Me", success=RpcUser).middleware(RpcAuth)
    never_fails = rpc.make(
        "NeverFails", success=rpc.rpc_schema.Stream(fx.schema.String, fx.schema.Never)
    )
    both_fail = rpc.make(
        "BothFail",
        success=rpc.rpc_schema.Stream(fx.schema.String, fx.schema.Number),
        error=fx.schema.String,
    )


def check_rpc(users: RpcUsers) -> None:
    # a stream schema's error and the RPC's error share one TypeVar, so a
    # `Never` stream error stays `Never` instead of widening to Unknown
    assert_type(RpcUsers.never_fails, rpc.StreamRpc[None, str, Never])
    assert_type(RpcUsers.both_fail, rpc.StreamRpc[None, str, float | str])
    assert_type(RpcUsers.get, rpc.Rpc[str, RpcUser, RpcNotFound])
    assert_type(RpcUsers.ping, rpc.Rpc[None, None, Never])
    assert_type(RpcUsers.stream, rpc.StreamRpc[None, float, Never])
    assert_type(RpcUsers.me, rpc.Rpc[None, RpcUser, Never, RpcAuth, RpcAuth])
    # A client method fails with the RPC's error, its middleware's, or the client's.
    assert_type(users.get("1"), fx.Effect[RpcUser, RpcNotFound | rpc.RpcClientError])
    assert_type(users.ping(), fx.Effect[None, rpc.RpcClientError])
    assert_type(users.me(), fx.Effect[RpcUser, RpcUnauthorized | rpc.RpcClientError])
    assert_type(users.stream(), Stream[float, rpc.RpcClientError])
    assert_type(users.get.discard("1"), fx.Effect[None, rpc.RpcClientError])
    assert_type(users.ping.discard(), fx.Effect[None, rpc.RpcClientError])
    # A stream RPC without a payload can be read as a queue too.
    assert_type(
        users.stream(as_queue=True),
        fx.Effect[Dequeue[float, rpc.RpcClientError | fx.Done], Never, Scope],
    )
    users.get(1)  # pyright: ignore[reportArgumentType]
    # Handlers need their services; a middleware's are provided, the middleware is needed.
    handlers = (
        RpcUsers.handlers()
        .handle(RpcUsers.get)(lambda r: RpcDb().map(lambda _: RpcUser(id=r.payload)))
        .handle(RpcUsers.ping)(lambda _r: fx.succeed(None))
        .handle(RpcUsers.stream)(lambda _r: fx.stream.make(1.0, 2.0))
        .handle(RpcUsers.me)(lambda _r: RpcCurrentUser())
    )
    assert_type(
        RpcUsers.to_layer(handlers), fx.Layer[rpc.HandlersFor[RpcUsers], Never, RpcDb | RpcAuth]
    )
    assert_type(
        RpcUsers.to_layer_effect(fx.succeed(handlers)),
        fx.Layer[rpc.HandlersFor[RpcUsers], Never, RpcDb | RpcAuth],
    )
    assert_type(
        RpcUsers.to_layer_effect(RpcCurrentUser().map(lambda _: handlers)),
        fx.Layer[rpc.HandlersFor[RpcUsers], Never, RpcDb | RpcAuth | RpcCurrentUser],
    )

    def pass_through(
        options: rpc.middleware.ClientMiddlewareOptions,
    ) -> fx.Effect[rpc.middleware.SuccessValue, rpc.middleware.Unhandled]:
        return options.next(options.request)

    assert_type(
        rpc.middleware.layer_client_effect(RpcAuth, fx.succeed(pass_through)),
        fx.Layer[rpc.middleware.ForClient[RpcAuth], Never, Never],
    )
    assert_type(
        rpc.middleware.layer_client_effect(RpcAuth, RpcDb().map(lambda _: pass_through)),
        fx.Layer[rpc.middleware.ForClient[RpcAuth], Never, RpcDb],
    )
    pinged = RpcUsers.handlers().handle(RpcUsers.ping)(lambda _r: fx.succeed(None))
    assert_type(
        RpcUsers.to_layer_effect(fx.succeed(pinged)),
        fx.Layer[rpc.HandlersFor[RpcUsers], Never, Never],
    )
    RpcUsers.handlers().handle(RpcUsers.get)(lambda _r: fx.succeed(1))  # pyright: ignore[reportCallIssue, reportArgumentType]
    assert_type(
        rpc_test.make_client(RpcUsers),
        fx.Effect[RpcUsers, Never, Scope | rpc.HandlersFor[RpcUsers]],
    )
    assert_type(
        rpc_client.make(RpcUsers), fx.Effect[RpcUsers, Never, Scope | rpc_client.ClientProtocol]
    )
    # layer= builds the handlers or protocol into the caller's scope (DOGFOOD trawl 1, 2).
    users_handlers = RpcUsers.to_layer(handlers)
    assert_type(
        rpc_test.make_client(RpcUsers, layer=users_handlers),
        fx.Effect[RpcUsers, Never, RpcDb | RpcAuth | Scope],
    )
    other_handlers = RpcOther.to_layer(
        RpcOther.handlers().handle(RpcOther.pong)(lambda _r: fx.succeed(None))
    )
    rpc_test.make_client(RpcUsers, layer=other_handlers)  # pyright: ignore[reportArgumentType]
    http_protocol = rpc_client.layer_protocol_http("http://localhost/rpc")
    assert_type(
        rpc_client.make(RpcUsers, layer=http_protocol),
        fx.Effect[RpcUsers, Never, rpc.serialization.RpcSerialization | HttpClient | Scope],
    )
    rpc_client.make(RpcUsers, layer=users_handlers)  # pyright: ignore[reportArgumentType]


# --- persistence -------------------------------------------------------------------------


class PersistedUser(S.Class):
    id: int
    name: str


@dataclass(frozen=True)
class GetPersistedUser(persistable.Class(success=PersistedUser, error=S.String)):
    id: int

    def primary_key(self) -> str:
        return f"GetPersistedUser:{self.id}"


@dataclass(frozen=True)
class PingPersisted(persistable.Class()):
    def primary_key(self) -> str:
        return "ping"


@dataclass(frozen=True)
class NoPrimaryKey(persistable.Class(success=S.String)):
    id: int


class PersistedLookup(Tag[str]): ...


def check_persisted_cache(
    cache: persisted_cache.PersistedCache[GetPersistedUser, PersistedLookup],
) -> None:
    assert_type(
        cache.get(GetPersistedUser(1)),
        fx.Effect[PersistedUser, str | PersistenceError | S.SchemaError, PersistedLookup],
    )
    assert_type(cache.invalidate(GetPersistedUser(1)), fx.Effect[None, PersistenceError])


def check_persistence(
    kv: kvs.KeyValueStoreService,
    store: persistence_module.PersistenceStore,
    users: fx.RequestResolver[GetPersistedUser],
) -> None:
    # The request's success and error come from its schemas.
    assert_type(
        fx.request(GetPersistedUser(1), fx.RequestResolver[GetPersistedUser].never()),
        fx.Effect[PersistedUser, str | PersistenceError | S.SchemaError],
    )
    assert_type(
        fx.request(PingPersisted(), fx.RequestResolver[PingPersisted].never()),
        fx.Effect[None, PersistenceError | S.SchemaError],
    )
    NoPrimaryKey(1)  # pyright: ignore[reportAbstractUsage]

    persisted = users.persisted(store_id="users", time_to_live=lambda _exit, _req: 60)
    assert_type(
        persisted,
        fx.Effect[
            fx.RequestResolver[GetPersistedUser, PersistenceError | S.SchemaError],
            Never,
            persistence_module.Persistence | fx.Scope,
        ],
    )

    def lookup(req: GetPersistedUser) -> fx.Effect[PersistedUser, str]: ...

    def needs_service(req: GetPersistedUser) -> fx.Effect[PersistedUser, str, PersistedLookup]: ...

    made = persisted_cache.make(lookup, store_id="users", time_to_live=lambda _e, _r: 60)
    assert_type(
        made,
        fx.Effect[
            persisted_cache.PersistedCache[GetPersistedUser, Never, PersistedUser, str],
            Never,
            persistence_module.Persistence | fx.Scope,
        ],
    )
    assert_type(
        persisted_cache.make(needs_service, store_id="users", time_to_live=lambda _e, _r: 60),
        fx.Effect[
            persisted_cache.PersistedCache[GetPersistedUser, Never, PersistedUser, str],
            Never,
            PersistedLookup | persistence_module.Persistence | fx.Scope,
        ],
    )
    at_lookup = persisted_cache.make(
        needs_service,
        store_id="users",
        time_to_live=lambda _e, _r: 60,
        require_services_at="lookup",
    )
    assert_type(
        at_lookup,
        fx.Effect[
            persisted_cache.PersistedCache[GetPersistedUser, PersistedLookup, PersistedUser, str],
            Never,
            persistence_module.Persistence | fx.Scope,
        ],
    )

    assert_type(
        store.get(GetPersistedUser(1)),
        fx.Effect[fx.Exit[PersistedUser, str] | None, PersistenceError | S.SchemaError],
    )
    assert_type(
        store.get_many([GetPersistedUser(1)]),
        fx.Effect[list[fx.Exit[PersistedUser, str] | None], PersistenceError | S.SchemaError],
    )
    assert_type(
        persistable.serialize_exit(GetPersistedUser(1), fx.exit.fail("missing")),
        fx.Effect[JsonValue, S.SchemaError],
    )

    assert_type(kv.get("k"), fx.Effect[str | None, kvs.KeyValueStoreError])
    assert_type(kv.get_bytes("k"), fx.Effect[bytes | None, kvs.KeyValueStoreError])
    assert_type(kv.prefix("p/"), kvs.KeyValueStoreService)
    users_store = kv.to_schema_store(PersistedUser)
    assert_type(
        users_store.get("k"),
        fx.Effect[Option[PersistedUser], kvs.KeyValueStoreError | S.SchemaError],
    )
    users_store.set("k", "not a user")  # pyright: ignore[reportArgumentType]

    assert_type(kvs.layer_memory, fx.Layer[kvs.KeyValueStore])
    assert_type(kvs.layer_sql(), fx.Layer[kvs.KeyValueStore, Never, SqlClient])
    assert_type(
        kvs.layer_file_system("/tmp/store"),
        fx.Layer[kvs.KeyValueStore, fx.PlatformError, fx.FileSystem | fx.Path],
    )
    assert_type(persistence_module.layer_memory, fx.Layer[persistence_module.Persistence])
    assert_type(
        persistence_module.layer_sql,
        fx.Layer[persistence_module.Persistence, Never, SqlClient],
    )
    assert_type(
        persistence_module.layer_kvs,
        fx.Layer[persistence_module.Persistence, Never, kvs.KeyValueStore],
    )
    assert_type(user_directories.make().config("app"), fx.Effect[str, fx.PlatformError])


def check_persisted_cache_lookup_types(
    narrow: persisted_cache.PersistedCache[GetPersistedUser, Never, PersistedUser, Never],
    wrong_success: persisted_cache.PersistedCache[GetPersistedUser, Never, int, str],
    wrong_error: persisted_cache.PersistedCache[GetPersistedUser, Never, PersistedUser, int],
) -> None:
    # The lookup gives Persistable.Success<K> / Error<K> (trawl T3): a lookup
    # that never fails fits, one giving another success or error is an error.
    assert_type(
        narrow.get(GetPersistedUser(1)),
        fx.Effect[PersistedUser, str | PersistenceError | S.SchemaError],
    )
    wrong_success.get(GetPersistedUser(1))  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    wrong_error.get(GetPersistedUser(1))  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

    def returns_int(req: GetPersistedUser) -> fx.Effect[int]: ...

    def ttl_by_exit(exit: fx.Exit[PersistedUser, str], req: GetPersistedUser) -> float:
        return 60 if isinstance(exit, fx.Success) else 1

    def ttl_wide(
        exit: fx.Exit[PersistedUser, str | PersistenceError | S.SchemaError],
        req: GetPersistedUser,
    ) -> float:
        return 1

    @fx.fn
    def program():
        cache = yield from persisted_cache.make(
            returns_int, store_id="users", time_to_live=lambda _e, _r: 60
        )
        return (yield from cache.get(GetPersistedUser(1)))  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]

    del program
    # The TTL functions see the lookup's Exit; the in-memory one also the
    # store's failures.
    persisted_cache.make(
        lookup_user,
        store_id="users",
        time_to_live=ttl_by_exit,
        in_memory_ttl=ttl_wide,
    )
    persisted_cache.make(
        lookup_user,
        store_id="users",
        time_to_live=ttl_wide,
        in_memory_ttl=ttl_by_exit,  # pyright: ignore[reportArgumentType]
    )


def lookup_user(req: GetPersistedUser) -> fx.Effect[PersistedUser, str]: ...


def _key_param(key: str) -> list[str | float]:
    return [key]


def check_resilience(
    limiter: rl.RateLimiterService,
    breaker: cb.CircuitBreakerService,
    redis: redis_module.RedisService,
    call: fx.Effect[int, str, PersistedLookup],
) -> None:
    assert_type(
        limiter.consume(key="k", limit=5, window=60),
        fx.Effect[rl.ConsumeResult, rl.RateLimiterError],
    )
    limiter.consume(key="k", limit=5, window=60, algorithm="sliding")  # pyright: ignore[reportArgumentType]
    assert_type(rl.sleep(limiter), rl.Sleep)
    assert_type(
        rl.sleep(limiter, key="k", limit=5, window=60),
        fx.Effect[rl.ConsumeResult, rl.RateLimiterError],
    )
    assert_type(rl.make, fx.Effect[rl.RateLimiterService, Never, rl.RateLimiterStore])
    assert_type(rl.layer_store_memory, fx.Layer[rl.RateLimiterStore])
    assert_type(rl.layer_store_redis(), fx.Layer[rl.RateLimiterStore, Never, redis_module.Redis])
    assert_type(rl.make_with_rate_limiter, fx.Effect[rl.WithRateLimiter, Never, rl.RateLimiter])
    with_limit = rl.WithRateLimiter(limiter)(key="k", limit=5, window=60)
    assert_type(call.pipe(with_limit), fx.Effect[int, str | rl.RateLimiterError, PersistedLookup])

    # execute adds CircuitBreakerError, directly or for .pipe.
    assert_type(
        breaker.execute(call, key="k"),
        fx.Effect[int, str | cb.CircuitBreakerError, PersistedLookup],
    )
    assert_type(
        call.pipe(breaker.execute(key="k")),
        fx.Effect[int, str | cb.CircuitBreakerError, PersistedLookup],
    )
    assert_type(breaker.state("k"), fx.Effect[cb.State, cb.CircuitBreakerError])
    assert_type(breaker.transitions, fx.Stream[cb.Transition])
    assert_type(
        cb.make(trip_policy=cb.consecutive(3), open_duration=fx.schedule.exponential(1)),
        fx.Effect[cb.CircuitBreakerService, Never, cb.CircuitBreakerStore | fx.Scope],
    )
    cb.make(trip_policy=cb.consecutive(3), open_duration=60, on_store_error="retry")  # pyright: ignore[reportArgumentType]
    assert_type(cb.layer_store_memory(), fx.Layer[cb.CircuitBreakerStore])
    assert_type(cb.layer_store_redis(), fx.Layer[cb.CircuitBreakerStore, Never, redis_module.Redis])

    # A script's arguments are its params function's; its result its decoder's.
    key_script = redis_module.script(_key_param, lua="return KEYS[1]", number_of_keys=1, decode=str)
    assert_type(redis.eval(key_script)("k"), fx.Effect[str, redis_module.RedisError])
    redis.eval(key_script)(1)  # pyright: ignore[reportArgumentType]
    assert_type(redis.send("GET", "k"), fx.Effect[redis_module.RedisReply, redis_module.RedisError])
    assert_type(
        redis_py.layer("redis://localhost"),
        fx.Layer[redis_module.Redis | redis_py.RedisPy, redis_module.RedisError],
    )
    assert_type(
        persistence_module.layer_redis,
        fx.Layer[persistence_module.Persistence, Never, redis_module.Redis],
    )


def _classify_response(
    exit: fx.Exit[fx.http.HttpClientResponse, HttpClientError],
) -> fx.Effect[cb.Outcome, Never, PersistedLookup]:
    return fx.succeed(cb.success)


def check_http_client_resilience(
    service: fx.http.HttpClientService[HttpClientError],
    limiter: rl.RateLimiterService,
    breaker: cb.CircuitBreakerService,
) -> None:
    from pyfect.http import client

    # with_rate_limiter adds RateLimiterError; with_circuit_breaker adds
    # CircuitBreakerError and the classifier's services.
    assert_type(
        service.with_rate_limiter(limiter=limiter, key="k", limit=5, window=60),
        client.HttpClientService[HttpClientError | rl.RateLimiterError],
    )
    service.with_rate_limiter(limiter=limiter, key="k", limit=5, window=60, algorithm="sliding")  # pyright: ignore[reportArgumentType]
    service.with_rate_limiter(
        limiter=limiter,
        key="k",
        limit=5,
        window=60,
        response_headers={"limits": "x-limit"},  # pyright: ignore[reportArgumentType]
    )
    assert_type(
        service.with_circuit_breaker(breaker=breaker),
        client.HttpClientService[HttpClientError | cb.CircuitBreakerError],
    )
    assert_type(
        service.with_circuit_breaker(breaker=breaker, classify=_classify_response),
        client.HttpClientService[HttpClientError | cb.CircuitBreakerError, PersistedLookup],
    )
    assert_type(
        client.circuit_breaker_classifier(
            fx.exit.succeed(fx.http.response.make(fx.http.request.get("/")))
        ),
        fx.Effect[cb.Outcome],
    )


def check_persisted_queue(
    queue: pq.PersistedQueue[int],
    service_schema: S.Codec[str, str, PersistedLookup, PersistedLookup],
) -> None:
    # A queue's values are its schema's; its services the schema's.
    assert_type(
        pq.make(name="q", schema=S.Int),
        fx.Effect[pq.PersistedQueue[int], Never, pq.PersistedQueueFactory],
    )
    assert_type(
        pq.make(name="q", schema=service_schema),
        fx.Effect[pq.PersistedQueue[str, PersistedLookup], Never, pq.PersistedQueueFactory],
    )
    assert_type(queue.offer(1), fx.Effect[str, pq.PersistedQueueError | S.SchemaError])
    queue.offer("one")  # pyright: ignore[reportArgumentType]

    # take adds PersistedQueueError to the handler's errors.
    def handle(value: int, meta: pq.Metadata) -> fx.Effect[str, ValueError, PersistedLookup]:
        return fx.fail(ValueError(meta.id))

    assert_type(
        queue.take(handle),
        fx.Effect[str, ValueError | pq.PersistedQueueError, PersistedLookup],
    )

    def shout(value: str, _meta: pq.Metadata) -> fx.Effect[str]:
        return fx.succeed(value.upper())

    queue.take(shout)  # pyright: ignore[reportArgumentType]

    assert_type(pq.layer, fx.Layer[pq.PersistedQueueFactory, Never, pq.PersistedQueueStore])
    assert_type(pq.layer_cleanup(), fx.Layer[Never, Never, pq.PersistedQueueStore])
    assert_type(pq.layer_store_memory, fx.Layer[pq.PersistedQueueStore])
    assert_type(pq.layer_store_redis(), fx.Layer[pq.PersistedQueueStore, Never, redis_module.Redis])
    assert_type(
        pq.layer_store_sql(),
        fx.Layer[pq.PersistedQueueStore, sql_error.SqlError, sql_client.SqlClient],
    )
    assert_type(
        pq.make_store_sql(),
        fx.Effect[
            pq.PersistedQueueStoreService, sql_error.SqlError, sql_client.SqlClient | fx.Scope
        ],
    )
    pq.make(name="q", schema=S.Int, max_attempts="10")  # pyright: ignore[reportArgumentType]
    # an error's cause is the exception the backend raised, not a Cause
    pq.PersistedQueueError(message="m", cause=fx.cause.die(ValueError()))  # pyright: ignore[reportArgumentType]


def check_workers(worker: Worker[int, str], runner: WorkerRunner[int, str]) -> None:
    # A worker sends I and handles O; run adds WorkerError to the handler's.
    assert_type(worker.send("hi"), fx.Effect[None, WorkerError])
    worker.send(1)  # pyright: ignore[reportArgumentType]

    def handle(reply: int) -> fx.Effect[None, ValueError, PersistedLookup]:
        return fx.fail(ValueError(reply))

    assert_type(worker.run(handle), fx.Effect[Never, ValueError | WorkerError, PersistedLookup])

    def shout(reply: str) -> fx.Effect[None]:
        return fx.void

    worker.run(shout)  # pyright: ignore[reportArgumentType]

    # A runner handles I and sends O.
    def serve(port: int, message: str) -> fx.Effect[None, Never, PersistedLookup]:
        return runner.send(port, len(message))

    assert_type(runner.run(serve), fx.Effect[None, WorkerError, PersistedLookup])
    runner.send(0, "no")  # pyright: ignore[reportArgumentType]

    assert_type(
        python_worker.layer(lambda _: ThreadWorker(lambda: None)),
        fx.Layer[WorkerPlatform | Spawner],
    )
    assert_type(python_worker_runner.layer, fx.Layer[WorkerRunnerPlatform])
    assert_type(
        rpc_client.layer_protocol_worker(size=2),
        fx.Layer[rpc_client.ClientProtocol, WorkerError, WorkerPlatform | Spawner],
    )
    rpc_client.layer_protocol_worker(size=2, min_size=1)  # pyright: ignore[reportCallIssue]
    assert_type(
        rpc_server.layer_protocol_worker_runner,
        fx.Layer[rpc_server.ServerProtocol, WorkerError, WorkerRunnerPlatform],
    )


# --- workflow ------------------------------------------------------------------------------


class WorkflowOrder(TypedDict):
    id: str
    amount: float


def check_workflow() -> None:
    # Payload, success and error come from the schemas.
    order = workflow.make(
        "Order",
        payload=S.Struct(WorkflowOrder),
        success=S.String,
        error=S.Number,
        idempotency_key=lambda o: o["id"],
    )
    assert_type(order, Workflow[WorkflowOrder, str, float])
    assert_type(
        workflow.make("Void", payload=S.Struct(WorkflowOrder), idempotency_key=lambda o: o["id"]),
        Workflow[WorkflowOrder, None, Never],
    )
    assert_type(order.execute({"id": "a", "amount": 1}), fx.Effect[str, float, WorkflowEngine])
    assert_type(
        order.execute({"id": "a", "amount": 1}, discard=True), fx.Effect[str, Never, WorkflowEngine]
    )
    assert_type(
        order.poll("id"),
        fx.Effect[Complete[str, float] | Suspended | None, Never, WorkflowEngine],
    )
    order.execute({"id": "a"})  # pyright: ignore[reportArgumentType]

    # to_layer keeps only the handler's own requirements.
    assert_type(
        order.to_layer(lambda o, _id: fx.succeed(o["id"])), fx.Layer[Never, Never, WorkflowEngine]
    )
    assert_type(
        order.to_layer(lambda o, _id: PersistedLookup().map(lambda s: s + o["id"])),
        fx.Layer[Never, Never, PersistedLookup | WorkflowEngine],
    )

    def wrong_success(o: WorkflowOrder, _id: str) -> fx.Effect[float]:
        return fx.succeed(o["amount"])

    order.to_layer(wrong_success)  # pyright: ignore[reportCallIssue, reportArgumentType]

    # An activity's execute must match its schemas.
    assert_type(
        activity.make(name="charge", execute=fx.succeed("ch_1"), success=S.String),
        Activity[str, Never, Never],
    )
    assert_type(
        activity.make(name="note", execute=PersistedLookup().as_void()),
        Activity[None, Never, PersistedLookup],
    )
    activity.make(name="charge", execute=fx.succeed(1), success=S.String)  # pyright: ignore[reportArgumentType, reportCallIssue]
    activity.make(name="charge", success=S.String, execute=fx.succeed(1))  # pyright: ignore[reportArgumentType, reportCallIssue]
    # Omitted, success is None and error none (QA ai-workflow WF-1).
    assert_type(activity.make(name="void", execute=fx.void), Activity[None, Never, Never])
    assert_type(
        activity.make(name="fails", execute=fx.fail("no"), error=S.String),
        Activity[None, str, Never],
    )
    activity.make(name="v", execute=fx.succeed(5))  # pyright: ignore[reportArgumentType, reportCallIssue]
    activity.make(name="e", execute=fx.fail("nope"))  # pyright: ignore[reportArgumentType, reportCallIssue]
    activity.make(name="e", execute=fx.fail("nope"), success=S.Null)  # pyright: ignore[reportArgumentType, reportCallIssue]

    # Compensation sees the step's value and the workflow's cause.
    charged = activity.make(name="charge", execute=fx.succeed("ch_1"), success=S.String)
    assert_type(
        order.with_compensation(charged, lambda charge_id, cause: fx.void),
        fx.Effect[str, Never, WorkflowEngine | WorkflowInstance | fx.Scope],
    )

    gate = durable_deferred.make("gate", success=S.Number, error=S.String)
    assert_type(gate, DurableDeferred[float, str])
    assert_type(gate.wait(), fx.Effect[float, str, WorkflowEngine | WorkflowInstance])
    assert_type(
        durable_clock.sleep(name="wait", duration=60),
        fx.Effect[None, Never, WorkflowEngine | WorkflowInstance],
    )

    emails = durable_queue.make(
        name="emails",
        payload=S.Struct(WorkflowOrder),
        success=S.String,
        idempotency_key=lambda o: o["id"],
    )
    assert_type(
        emails.worker(lambda o: PersistedLookup().map(lambda s: s + o["id"])),
        fx.Layer[Never, Never, WorkflowEngine | pq.PersistedQueueFactory | PersistedLookup],
    )
    emails.worker(lambda o: fx.succeed(o["amount"]))  # pyright: ignore[reportArgumentType]

    # Running a body that needs nothing but its scope leaves no Unknown requirement.
    assert_type(
        workflow.into_result(fx.succeed(1)),
        fx.Effect[Complete[int, Never] | Suspended, Never, WorkflowInstance],
    )
    assert_type(
        workflow.into_result(PersistedLookup()),
        fx.Effect[Complete[str, Never] | Suspended, Never, PersistedLookup | WorkflowInstance],
    )
    assert_type(workflow.provide_scope(fx.succeed(1)), fx.Effect[int, Never, WorkflowInstance])
    assert_type(
        workflow.provide_scope(PersistedLookup()),
        fx.Effect[str, Never, PersistedLookup | WorkflowInstance],
    )


def check_workflow_proxy_typed_operations() -> None:
    """``workflow_proxy.rpcs`` / ``http_endpoints`` declared in a group type
    the client's methods by the workflow (DOGFOOD outlay #7)."""
    from pyfect.http_api import HttpApi, get_group
    from pyfect.http_api import test as api_test
    from pyfect.http_api.group import HttpApiGroup
    from pyfect.rpc import RpcClientError
    from pyfect.rpc.group import RpcGroup
    from pyfect.schema import SchemaError
    from pyfect.workflow import workflow_proxy

    order = workflow.make(
        "Order",
        payload=S.Struct(WorkflowOrder),
        success=S.String,
        error=S.Number,
        idempotency_key=lambda o: o["id"],
    )

    class OrderRpcs(RpcGroup):
        place, place_discard, place_resume = workflow_proxy.rpcs(order)

    class Orders(HttpApiGroup, identifier="orders"):
        place, place_discard, place_resume = workflow_proxy.http_endpoints(order)

    payload: WorkflowOrder = {"id": "o", "amount": 1}

    def rpc_client():
        client = yield from rpc_test.make_client(OrderRpcs)
        assert_type(client.place(payload), fx.Effect[str, float | RpcClientError])
        assert_type(client.place_discard(payload), fx.Effect[str, RpcClientError])
        assert_type(client.place_resume({"executionId": "e"}), fx.Effect[None, RpcClientError])

    def http_client():
        api = HttpApi.make("api").add(Orders)
        client = get_group((yield from api_test.groups(api, [Orders])), Orders)
        assert_type(
            client.place(payload=payload), fx.Effect[str, float | HttpClientError | SchemaError]
        )
        assert_type(
            client.place_discard(payload=payload), fx.Effect[str, HttpClientError | SchemaError]
        )

    _ = (rpc_client, http_client)


def check_workflow_deferred_state(instance: WorkflowInstanceService) -> None:
    state = workflow_engine.DeferredState()
    assert_type(state.track_run(instance, fx.succeed(1)), fx.Effect[int, Never, Never])
    assert_type(
        state.track_run(instance, PersistedLookup()), fx.Effect[str, Never, PersistedLookup]
    )


# AI: a toolkit's tool names, results and failures flow into responses ----------------


class AiWeatherParams(TypedDict):
    city: str


class AiWeather(TypedDict):
    degrees: float


class AiDb(Tag[int]):
    pass


class AiOther(Tag[int]):
    pass


type AiResults = (
    ai_response.ToolResultSuccess[Literal["Weather"], AiWeather]
    | ai_response.ToolResultFailure[Literal["Weather"], str | AiError]
    | ai_response.ToolResultSuccess[Literal["Clock"], int]
    | ai_response.ToolResultFailure[Literal["Clock"], int | AiError]
)


def check_ai_toolkit() -> None:
    weather = ai_tool.make(
        "Weather",
        parameters=S.Struct(AiWeatherParams),
        success=S.Struct(AiWeather),
        failure=S.String,
    )
    clock = ai_tool.make(
        "Clock", success=S.Int, failure=S.Int, failure_mode="return", dependencies=[AiDb]
    )
    assert_type(
        weather,
        ai_tool.Tool[Literal["Weather"], AiWeatherParams, AiWeather, str, str, Never],
    )
    assert_type(clock, ai_tool.Tool[Literal["Clock"], dict[str, Never], int, int, Never, AiDb])

    # A handler is checked against its tool's types.
    ok = weather.handler(lambda params, _: fx.succeed(AiWeather(degrees=len(params["city"]))))
    assert_type(ok, ai_tool.Handler[Literal["Weather"]])
    weather.handler(lambda _, __: fx.succeed(1))  # pyright: ignore[reportArgumentType]
    weather.handler(lambda _, __: fx.fail(1))  # pyright: ignore[reportArgumentType]
    clock.handler(lambda _, __: AiDb())
    clock.handler(lambda _, __: AiOther())  # pyright: ignore[reportArgumentType]

    kit = ai_toolkit.make(weather, clock)
    assert_type(
        kit,
        ai_toolkit.Toolkit[Literal["Weather", "Clock"], AiResults, str, AiDb],
    )
    assert_type(kit.to_layer(ok), fx.Layer[ai_toolkit.Handlers[Literal["Weather", "Clock"]]])

    text = lm.generate_text("hi", toolkit=kit)
    assert_type(
        text,
        fx.Effect[
            lm.GenerateTextResponse[Literal["Weather", "Clock"], AiResults],
            AiError | str,
            lm.LanguageModel | AiDb | ai_toolkit.Handlers[Literal["Weather", "Clock"]],
        ],
    )
    assert_type(
        lm.generate_text("hi"),
        fx.Effect[lm.GenerateTextResponse[Never, Never], AiError, lm.LanguageModel],
    )
    assert_type(
        lm.generate_object("hi", schema=S.Struct(AiWeather)),
        fx.Effect[lm.GenerateObjectResponse[Never, Never, AiWeather], AiError, lm.LanguageModel],
    )
    assert_type(
        lm.stream_text("hi", toolkit=kit),
        Stream[
            ai_response.StreamPart[Literal["Weather", "Clock"], AiResults],
            AiError | str,
            lm.LanguageModel | AiDb | ai_toolkit.Handlers[Literal["Weather", "Clock"]],
        ],
    )


def check_ai_chat(chat: ai_chat.Service, persisted: ai_chat.PersistenceService) -> None:
    from pyfect.persistence.persistence import BackingPersistence

    weather = ai_tool.make(
        "Weather", parameters=S.Struct(AiWeatherParams), success=S.Struct(AiWeather)
    )
    kit = ai_toolkit.make(weather)
    assert_type(
        chat.generate_text("hi"),
        fx.Effect[lm.GenerateTextResponse[Never, Never], AiError, lm.LanguageModel],
    )
    assert_type(
        chat.generate_text("hi", toolkit=kit),
        fx.Effect[
            lm.GenerateTextResponse[
                Literal["Weather"],
                ai_response.ToolResultPart[Literal["Weather"], AiWeather, AiError],
            ],
            AiError,
            lm.LanguageModel | ai_toolkit.Handlers[Literal["Weather"]],
        ],
    )
    assert_type(
        chat.generate_object("hi", schema=S.Struct(AiWeather)),
        fx.Effect[lm.GenerateObjectResponse[Never, Never, AiWeather], AiError, lm.LanguageModel],
    )
    assert_type(
        chat.stream_text("hi"),
        Stream[ai_response.StreamPart[Never, Never], AiError, lm.LanguageModel],
    )
    assert_type(chat.export_json, fx.Effect[str, AiError])
    # Deferred validation returns calls to any tool name, and needs tool call
    # resolution disabled.
    assert_type(
        lm.generate_text("hi", disable_tool_call_resolution=True, tool_call_validation="deferred"),
        fx.Effect[lm.GenerateTextResponse[str, Never], AiError, lm.LanguageModel],
    )
    assert_type(
        chat.stream_text(
            "hi", toolkit=kit, disable_tool_call_resolution=True, tool_call_validation="deferred"
        ),
        Stream[
            ai_response.StreamPart[
                str,
                ai_response.ToolResultPart[Literal["Weather"], AiWeather, AiError],
            ],
            AiError,
            lm.LanguageModel | ai_toolkit.Handlers[Literal["Weather"]],
        ],
    )
    lm.generate_text("hi", tool_call_validation="deferred")  # pyright: ignore[reportArgumentType]
    assert_type(
        persisted.get("1"),
        fx.Effect[ai_chat.Persisted, ai_chat.ChatNotFoundError | PersistenceError],
    )
    assert_type(
        ai_chat.layer_persisted(store_id="chat"),
        fx.Layer[ai_chat.Persistence, Never, BackingPersistence],
    )
    chat.generate_text(1)  # pyright: ignore[reportArgumentType]


def check_ai_result_narrowing(
    response: lm.GenerateTextResponse[Literal["Weather", "Clock"], AiResults],
) -> None:
    for part in response.tool_results:
        match part:
            case ai_response.ToolResultSuccess(name="Weather"):
                assert_type(part.result, AiWeather)
            case ai_response.ToolResultFailure(name="Clock"):
                assert_type(part.result, int | AiError)
            case _:
                pass


def check_mcp() -> None:
    from pyfect import stdio as mcp_stdio
    from pyfect.ai import mcp_client as mcp_c
    from pyfect.ai import mcp_protocol as mcp_p
    from pyfect.ai import mcp_server as mcp_m
    from pyfect.ai.mcp_client_error import McpClientError as McpErr
    from pyfect.errors import IllegalArgumentError as Illegal
    from pyfect.http.router import HttpRouter as Router
    from pyfect.platform_error import PlatformError as PlatformErr
    from pyfect.process import ChildProcessSpawner as Spawner
    from pyfect.process import make as command
    from pyfect.scope import Scope as McpScope

    weather = ai_tool.make(
        "Weather", parameters=S.Struct(AiWeatherParams), success=S.Struct(AiWeather)
    )
    kit = ai_toolkit.make(weather)
    assert_type(mcp_m.make(), fx.Effect[mcp_m.McpServerService])
    assert_type(
        mcp_m.register_toolkit(kit),
        fx.Effect[None, Never, mcp_m.McpServer | ai_toolkit.Handlers[Literal["Weather"]]],
    )
    assert_type(mcp_m.toolkit(kit), fx.Layer[Never, Never, ai_toolkit.Handlers[Literal["Weather"]]])
    assert_type(
        mcp_m.run_stdio(name="s", version="1", protocols=(mcp_p.v2025_11_25,)),
        fx.Effect[None, Illegal | PlatformErr, mcp_m.McpServer | mcp_stdio.Stdio],
    )
    assert_type(
        mcp_m.layer_http(name="s", version="1", path="/mcp", protocols=(mcp_p.v2025_11_25,)),
        fx.Layer[mcp_m.McpServer, Illegal, Router],
    )
    assert_type(
        mcp_m.layer_http(
            name="s",
            version="1",
            path="/mcp",
            protocols=(mcp_p.v2026_07_28,),
            allow_subscriptions=False,
        ),
        fx.Layer[mcp_m.McpServer, Illegal, Router],
    )
    assert_type(
        mcp_m.layer_http_request_scoped(
            name="s", version="1", path="/mcp", protocols=(mcp_p.v2026_07_28,)
        ),
        fx.Layer[mcp_m.McpServer, Illegal, Router],
    )
    # Sessionful revisions keep state between requests, so a request cannot own them.
    mcp_m.layer_http_request_scoped(
        name="s",
        version="1",
        path="/mcp",
        protocols=(mcp_p.v2025_11_25,),  # pyright: ignore[reportArgumentType]
    )
    mcp_m.layer_http_request_scoped(
        name="s",
        version="1",
        path="/mcp",
        protocols=(mcp_p.v2026_07_28, mcp_p.v2025_11_25),  # pyright: ignore[reportArgumentType]
    )
    mcp_m.layer_http_request_scoped(
        name="s",
        version="1",
        path="/mcp",
        protocols=(mcp_p.v2026_07_28,),
        allow_subscriptions=True,  # pyright: ignore[reportCallIssue]
    )
    mcp_m.layer_http_request_scoped(
        name="s",
        version="1",
        path="/mcp",
        protocols=(mcp_p.v2026_07_28,),
        allow_session_termination=True,  # pyright: ignore[reportCallIssue]
    )
    assert_type(
        mcp_schema_module.McpRequestContext().map(lambda c: c.input_responses),
        fx.Effect[
            Mapping[str, mcp_schema_module.McpInputResponse] | None,
            Never,
            mcp_schema_module.McpRequestContext,
        ],
    )
    assert_type(
        mcp_schema_module.McpRequestContext().map(lambda c: c.request_state),
        fx.Effect[str | None, Never, mcp_schema_module.McpRequestContext],
    )
    # A URL elicitation asked through InputRequired has no elicitationId.
    mcp_schema_module.InputRequired(
        input_requests={
            "go": {
                "method": "elicitation/create",
                "params": {"mode": "url", "message": "m", "url": "https://x"},
            }
        }
    )
    # InputRequired asks for input, or a retry with state; at least one of them.
    mcp_schema_module.InputRequired(request_state="state")
    mcp_schema_module.InputRequired(input_requests={"roots": {"method": "roots/list"}})
    mcp_schema_module.InputRequired()  # pyright: ignore[reportCallIssue]
    assert_type(
        mcp_m.register_resource(uri="demo://a", name="a", content=fx.succeed("text")),
        fx.Effect[None, Never, mcp_m.McpServer],
    )
    template = mcp_m.uri_template("demo://items/", S.Int)
    assert_type(template, mcp_m.UriTemplate[int])
    mcp_m.register_resource_template(
        template, name="item", content=lambda uri, n: fx.succeed(f"{uri}{n + 1}")
    )
    mcp_m.register_resource_template(
        template,
        name="item",
        content=lambda _, n: fx.succeed(n),  # pyright: ignore[reportArgumentType]
    )
    assert_type(
        mcp_m.register_prompt(
            name="p", content=lambda p: fx.succeed(p["city"]), parameters=S.Struct(AiWeatherParams)
        ),
        fx.Effect[None, Never, mcp_m.McpServer],
    )

    client = mcp_c.make(name="c", version="1")
    assert_type(client, fx.Effect[mcp_c.McpClientService, McpErr, mcp_c.Transport | McpScope])
    assert_type(
        mcp_c.layer_stdio(
            name="c", version="1", command=command("server"), protocol=mcp_p.v2025_11_25
        ),
        fx.Layer[mcp_c.McpClient, McpErr, Spawner],
    )
    # The client speaks only the two newest revisions.
    modern: mcp_c.ClientProtocol = mcp_p.v2026_07_28
    assert_type(modern, mcp_p.ProtocolAdapter[Literal["2026-07-28"]])
    _june: mcp_c.ClientProtocol = mcp_p.v2025_06_18  # pyright: ignore[reportAssignmentType]


def check_mcp_client_calls(
    service: mcp_client_module.McpClientService, tool: mcp_schema_module.Tool
) -> None:
    from pyfect.ai.mcp_client_error import McpClientError as McpErr

    assert_type(service.call_tool(tool), fx.Effect[mcp_schema_module.CallToolResult, McpErr])
    assert_type(service.call_tool(tool, schema=S.Struct(AiWeather)), fx.Effect[AiWeather, McpErr])
    assert_type(service.list_tools(), fx.Effect[list[mcp_schema_module.Tool], McpErr])
    # failure_mode="return" gives tool errors to the model, so a call fails with nothing.
    assert_type(
        mcp_client_module.toolkit(service),
        fx.Effect[ai_toolkit.WithHandler[Any, Any, McpErr, Never], McpErr],
    )
    assert_type(
        mcp_client_module.toolkit(service, "docs__", failure_mode="return"),
        fx.Effect[ai_toolkit.WithHandler[Any, Any, Never, Never], McpErr],
    )


def check_ai_providers() -> None:
    # Provider layers need their client; the client layers need an HttpClient.
    key = redact("sk")
    assert_type(
        anthropic_client.layer(api_key=key),
        fx.Layer[anthropic_client.AnthropicClient, Never, HttpClient],
    )
    assert_type(
        anthropic_lm.model("claude-opus-5-5"),
        ai_model.Model[lm.LanguageModel, anthropic_client.AnthropicClient],
    )
    assert_type(
        compat_client.layer(api_key=key, api_url="https://api.example.test/v1"),
        fx.Layer[compat_client.OpenAiClient, Never, HttpClient],
    )
    assert_type(
        compat_lm.model("llama-3.3-70b"),
        ai_model.Model[lm.LanguageModel, compat_client.OpenAiClient],
    )
    assert_type(
        compat_em.model("text-embedding-3-small", dimensions=1536),
        ai_model.Model[
            ai_embedding_model.EmbeddingModel | ai_embedding_model.Dimensions,
            compat_client.OpenAiClient,
        ],
    )

    # A config override keeps the effect's type; a misspelled option is rejected.
    program = lm.generate_text("hi")
    assert_type(
        program.pipe(anthropic_lm.with_config_override({"max_tokens": 10})),
        fx.Effect[lm.GenerateTextResponse[Never, Never], ai_error_module.AiError, lm.LanguageModel],
    )
    anthropic_lm.with_config_override({"max_token": 10})  # pyright: ignore[reportArgumentType]
    compat_lm.with_config_override({"strict_json_schema": "yes"})  # pyright: ignore[reportArgumentType]


def check_ai_provider_client(service: anthropic_client.Service) -> None:
    # The client calls fail only with AiError.
    assert_type(
        service.create_message({"model": "claude-haiku-5-5", "max_tokens": 1, "messages": []}),
        fx.Effect[tuple[anthropic_client.Message, HttpResponse], ai_error_module.AiError],
    )


def check_ai_openai(service: openai_client.Service) -> None:
    key = redact("sk")
    assert_type(
        openai_client.layer(api_key=key),
        fx.Layer[openai_client.OpenAiClient, Never, HttpClient],
    )
    assert_type(
        openai_lm.model("gpt-5"),
        ai_model.Model[lm.LanguageModel, openai_client.OpenAiClient],
    )
    assert_type(
        openai_em.model("text-embedding-3-small", dimensions=1536),
        ai_model.Model[
            ai_embedding_model.EmbeddingModel | ai_embedding_model.Dimensions,
            openai_client.OpenAiClient,
        ],
    )
    # WebSocket mode provides the socket and needs the client and a constructor.
    assert_type(
        openai_client.layer_web_socket_mode(),
        fx.Layer[
            openai_client.OpenAiSocket | ResponseIdTracker,
            Never,
            openai_client.OpenAiClient | WebSocketConstructor,
        ],
    )
    assert_type(
        lm.generate_text("hi").pipe(openai_client.with_web_socket_mode),
        fx.Effect[
            lm.GenerateTextResponse[Never, Never],
            ai_error_module.AiError,
            lm.LanguageModel | openai_client.OpenAiClient | WebSocketConstructor,
        ],
    )
    # The client calls fail only with AiError.
    assert_type(
        service.create_response({"model": "gpt-5", "input": "hi"}),
        fx.Effect[tuple[openai_client.Response, HttpResponse], ai_error_module.AiError],
    )
    # Provider-defined tools carry their name and result types.
    assert_type(
        openai_tool.WebSearch(),
        ai_tool.ProviderDefined[
            Literal["OpenAiWebSearch"],
            openai_tool.WebSearchParameters,
            openai_tool.WebSearchSuccess,
            openai_tool.WebSearchFailure,
            openai_tool.WebSearchFailure,
            Never,
        ],
    )
    openai_lm.with_config_override({"use_item_reference": True})  # pyright: ignore[reportArgumentType]


class _Ticket(TypedDict):
    message: str


def check_ai_decision_model(
    response: ai_dm.DecideResponse, settled: ai_dm.DecideSettledResponse
) -> None:
    # Labels written as literals stay literal; computed ones widen to str.
    team = ai_decision.classify(instructions="Route", criteria={"billing": "b", "tech": "t"})
    severity = ai_decision.rate(instructions="Rate", criteria=["low", "high"])
    urgent = ai_decision.probability(instructions="Urgent?")
    assert_type(team, ai_decision.Classify[Literal["billing", "tech"]])
    assert_type(severity, ai_decision.Rate[Literal["low", "high"]])
    assert_type(
        ai_decision.rate(instructions="Rate", criteria=[str(1), "2"]), ai_decision.Rate[str]
    )
    triage = ai_decision.make(
        input=S.Struct(_Ticket), decisions={"team": team, "severity": severity, "urgent": urgent}
    )
    assert_type(triage, ai_decision.Definition[_Ticket, Never])
    # An answer looked up by its decision carries that decision's labels.
    assert_type(response.answers[team], ai_decision.ClassifyAnswer[Literal["billing", "tech"]])
    assert_type(response.answers[severity].label, Literal["low", "high"])
    assert_type(response.answers[urgent], ai_decision.ProbabilityAnswer)
    assert_type(
        settled.outcomes[team],
        fx.Ok[ai_decision.ClassifyAnswer[Literal["billing", "tech"]]]
        | fx.Err[ai_decision.Unanswered],
    )
    # Deciding needs the DecisionModel and fails only with AiError.
    assert_type(
        ai_dm.decide(triage, input={"message": "hi"}),
        fx.Effect[ai_dm.DecideResponse, AiError, ai_dm.DecisionModel],
    )
    assert_type(
        ai_dm.decide_settled(triage, input={"message": "hi"}),
        fx.Effect[ai_dm.DecideSettledResponse, AiError, ai_dm.DecisionModel],
    )
    ai_dm.decide(triage, input={"message": 1})  # pyright: ignore[reportArgumentType]
    # Providers need their own client.
    assert_type(
        openai_dm.model("gpt-6-luna"),
        ai_model.Model[ai_dm.DecisionModel, openai_client.OpenAiClient],
    )
    assert_type(
        cloudflare_dm.model("clef"),
        ai_model.Model[ai_dm.DecisionModel, cloudflare_client.CloudflareClient],
    )
    assert_type(
        typesafe_dm.model("jev-latest"),
        ai_model.Model[ai_dm.DecisionModel, typesafe_client.TypeSafeClient],
    )
    assert_type(
        cloudflare_client.layer_config(),
        fx.Layer[cloudflare_client.CloudflareClient, fx.config.ConfigError, HttpClient],
    )
    assert_type(
        typesafe_client.layer(), fx.Layer[typesafe_client.TypeSafeClient, Never, HttpClient]
    )
    assert_type(
        typesafe_client.layer_config(),
        fx.Layer[typesafe_client.TypeSafeClient, fx.config.ConfigError, HttpClient],
    )


type _OpenAiGeneratedErrors = HttpClientError | S.SchemaError | openai_generated.OpenAiClientError


def check_ai_openai_client_generated(service: openai_generated.OpenAiClient) -> None:
    key = fx.redacted.make("k")
    assert_type(
        openai_client_generated.layer(api_key=key),
        fx.Layer[openai_client_generated.OpenAiClientGenerated, Never, HttpClient],
    )
    assert_type(
        openai_client_generated.layer_config(),
        fx.Layer[openai_client_generated.OpenAiClientGenerated, fx.config.ConfigError, HttpClient],
    )
    # A JSON operation: path arguments first, the response on request.
    assert_type(
        service.get_assistant("a"),
        fx.Effect[openai_generated_types.GetAssistant200, _OpenAiGeneratedErrors],
    )
    assert_type(
        service.get_assistant("a", include_response=True),
        fx.Effect[
            tuple[openai_generated_types.GetAssistant200, HttpResponse], _OpenAiGeneratedErrors
        ],
    )
    # Exact-status successes are a union; a binary body is bytes; a stream is a stream.
    assert_type(
        service.invite_user(payload={"email": "a@b.c", "role": "reader"}),
        fx.Effect[
            openai_generated_types.InviteUser200 | openai_generated_types.InviteUser201,
            _OpenAiGeneratedErrors,
        ],
    )
    assert_type(
        service.create_speech(payload={"model": "tts-1", "input": "Hi", "voice": "alloy"}),
        fx.Effect[bytes, _OpenAiGeneratedErrors],
    )
    assert_type(service.download_file_stream("f"), fx.Stream[bytes, HttpClientError])
    assert_type(
        service.create_response_sse(payload={"model": "m", "input": "x"}),
        fx.Stream[
            sse.DataEvent[openai_generated_types.CreateResponse200Sse],
            HttpClientError | S.SchemaError | sse.Retry | sse.SseError,
        ],
    )
    # A multipart file is a form's file part, not raw bytes.
    assert_type(
        service.create_file(payload={"file": HttpFile(b"x"), "purpose": "batch"}),
        fx.Effect[openai_generated_types.CreateFile200, _OpenAiGeneratedErrors],
    )
    service.create_file(payload={"file": b"x", "purpose": "batch"})  # pyright: ignore[reportArgumentType]


def check_ai_openrouter(service: openrouter_client.Service) -> None:
    key = redact("sk")
    assert_type(
        openrouter_client.layer(api_key=key),
        fx.Layer[openrouter_client.OpenRouterClient, Never, HttpClient],
    )
    assert_type(
        openrouter_client.layer_config(),
        fx.Layer[openrouter_client.OpenRouterClient, fx.config.ConfigError, HttpClient],
    )
    assert_type(
        openrouter_lm.model("openai/gpt-4o-mini"),
        ai_model.Model[lm.LanguageModel, openrouter_client.OpenRouterClient],
    )
    assert_type(
        openrouter_dm.model("openai/gpt-4o-mini"),
        ai_model.Model[ai_dm.DecisionModel, openrouter_client.OpenRouterClient],
    )
    request: openrouter_client.ChatRequest = {"model": "openai/gpt-4o-mini", "messages": []}
    # The client calls fail only with AiError.
    assert_type(
        service.create_chat_completion(request),
        fx.Effect[tuple[openrouter_client.ChatResult, HttpResponse], ai_error_module.AiError],
    )
    # The generated operations keep their documented error statuses.
    assert_type(
        service.client.send_chat_completion_request(payload=request),
        fx.Effect[
            openrouter_client.ChatResult,
            HttpClientError | S.SchemaError | openrouter_generated.OpenRouterClientError,
        ],
    )
    openrouter_lm.with_config_override({"temperature": "hot"})  # pyright: ignore[reportArgumentType]
    openrouter_dm.layer(model="m", config={"user": 1})  # pyright: ignore[reportArgumentType]


def check_ai_structured_output() -> None:
    # The codec decodes the schema's Type from any JSON; its services carry over.
    assert_type(to_codec_anthropic(S.FiniteFromString), StructuredOutputCodec[float, Never, Never])
    codec, json_schema = to_codec_openai(S.Tuple(S.String, S.Finite))
    assert_type(codec, S.Codec[tuple[str, float], object, Never, Never])
    assert_type(json_schema, dict[str, object])
    # Each is a provider's codec transformer.
    transformers: list[ai_tool.CodecTransformer] = [to_codec_anthropic, to_codec_openai]
    assert_type(transformers[0](S.String), tuple[S.Top, dict[str, object]])


# --- Model / VariantSchema / SqlModel -----------------------------------------------------


class ModelUserInsert(TypedDict):
    name: str
    created_at: NotRequired[datetime]


class ModelUserUpdate(TypedDict):
    id: int
    name: str


class ModelUser(Model.Class[ModelUserInsert, ModelUserUpdate]):
    id: int = Model.field(Model.field_except(["insert"])(S.Int))
    name: str
    created_at: datetime = Model.field(Model.DateTimeInsert)
    password = Model.Sensitive(S.String)  # not in select: no annotation, no field


class ModelPlain(Model.Class):
    name: str


def check_model() -> None:
    # Each variant is the TypedDict given for it; untyped ones are mappings.
    assert_type(ModelUser.insert, VS.VariantStructSchema[ModelUserInsert])
    assert_type(ModelUser.update, VS.VariantStructSchema[ModelUserUpdate])
    assert_type(ModelUser.json, VS.VariantStructSchema[Mapping[str, object]])
    assert_type(ModelPlain.insert, VS.VariantStructSchema[Mapping[str, object]])
    assert_type(Model.extract(ModelUser, "insert"), VS.VariantStructSchema[ModelUserInsert])
    assert_type(Model.extract(ModelUser, "select"), type[ModelUser])
    assert_type(ModelUser.insert.make({"name": "a"}), ModelUserInsert)
    ModelUser.insert.make({"nam": "a"})  # pyright: ignore[reportArgumentType]
    assert_type(S.decode_unknown_sync(ModelUser.update)({}), ModelUserUpdate)

    # The class is the select variant; a field select lacks is not a parameter.
    ModelUser(id=1, name="a", created_at=datetime.now(UTC))
    ModelUser(id=1, name="a", created_at=datetime.now(UTC), password="x")  # pyright: ignore[reportCallIssue]

    # A variant field's select Type must fit the annotation.
    assert_type(Model.GeneratedByDb(S.Int), VS.Field[int])
    assert_type(Model.FieldOption(S.String), VS.Field[Option[str]])
    assert_type(Model.Field(insert=S.String), VS.Field[Model.NotSelected])
    assert_type(Model.DateTimeInsert, VS.Field[datetime])

    class Wrong(Model.Class):  # pyright: ignore[reportUnusedClass]
        id: str = Model.field(Model.GeneratedByDb(S.Int))  # pyright: ignore[reportAssignmentType]
        hidden: int = Model.field(Model.Field(insert=S.Int))  # pyright: ignore[reportAssignmentType]

    # Variant names are checked; a bare string is not a list of them.
    Model.field_only(["insert", "json_create"])
    Model.field_only(["jsonCreate"])  # pyright: ignore[reportArgumentType]
    Model.field_only("insert")  # pyright: ignore[reportArgumentType]


def check_sql_model() -> None:
    repository = sql_model.make_repository(
        ModelUser, table_name="users", span_prefix="Users", id_column="id"
    )
    assert_type(
        repository,
        fx.Effect[
            sql_model.Repository[ModelUser, ModelUserInsert, ModelUserUpdate], Never, SqlClient
        ],
    )

    def use(repo: sql_model.Repository[ModelUser, ModelUserInsert, ModelUserUpdate]) -> None:
        # insert / update take their variant and return the model.
        assert_type(repo.insert({"name": "a"}), fx.Effect[ModelUser, S.SchemaError | SqlError])
        assert_type(
            repo.update({"id": 1, "name": "b"}), fx.Effect[ModelUser, S.SchemaError | SqlError]
        )
        repo.insert({"id": 1, "name": "a"})  # pyright: ignore[reportArgumentType]
        repo.update({"name": "b"})  # pyright: ignore[reportArgumentType]
        assert_type(
            repo.find_by_id(1),
            fx.Effect[ModelUser, fx.NoSuchElementException | S.SchemaError | SqlError],
        )
        assert_type(repo.delete(1), fx.Effect[None, S.SchemaError | SqlError])

    resolvers = sql_model.make_resolvers(
        ModelUser, table_name="users", span_prefix="Users", id_column="id"
    )
    assert_type(
        resolvers, fx.Effect[sql_model.Resolvers[ModelUser, ModelUserInsert], Never, SqlClient]
    )

    def use_resolvers(r: sql_model.Resolvers[ModelUser, ModelUserInsert]) -> None:
        payload: ModelUserInsert = {"name": "a"}
        assert_type(
            sql_resolver.request(payload, r.insert),
            fx.Effect[ModelUser, ResultLengthMismatch | S.SchemaError | SqlError, Any],
        )

    # Only a model class has variants to make a repository of.
    sql_model.make_repository(ModelPlain, table_name="t", span_prefix="T", id_column="name")
    sql_model.make_repository(S.String, table_name="t", span_prefix="T", id_column="id")  # pyright: ignore[reportArgumentType]
    del use, use_resolvers


# --- graphql ---------------------------------------------------------------------


class GqlLogin(TypedDict):
    login: str


class GqlViewer(TypedDict):
    viewer: GqlLogin


class GqlLoginNodes(TypedDict):
    nodes: Sequence[GqlLogin | None]


def check_graphql_resolver_items(
    nodes: graphql.operation.Method[Sequence[str], GqlLoginNodes, Never, Never],
) -> None:
    # DOGFOOD atlas #6: ``items`` types the lookups with the list's items.
    from pyfect.graphql.client_error import GraphQLClientError

    def ids(keys: Sequence[str]) -> Sequence[str]:
        return keys

    by_position = graphql.resolver.ordered(nodes, variables=ids, items=lambda data: data["nodes"])
    assert_type(
        graphql.resolver.request(by_position),
        Callable[[str], fx.Effect[GqlLogin, GraphQLClientError | fx.NoSuchElementException]],
    )
    by_login = graphql.resolver.find_by_id(
        nodes, variables=ids, items=lambda data: data["nodes"], key=lambda found: found["login"]
    )
    assert_type(
        graphql.resolver.request(by_login),
        Callable[[str], fx.Effect[GqlLogin, GraphQLClientError | fx.NoSuchElementException]],
    )
    graphql.resolver.ordered(nodes, variables=ids, items=lambda data: data["edges"])  # pyright: ignore[reportGeneralTypeIssues, reportUnknownLambdaType]
    graphql.resolver.ordered(nodes, variables=ids)  # pyright: ignore[reportCallIssue]


class GqlIssueId(TypedDict):
    id: str


class GqlTokenExpired(fx.TaggedError): ...


class GqlCurrentUser(fx.Tag[str]): ...


class GqlAuth(graphql.GraphQLMiddleware[GqlTokenExpired, GqlCurrentUser]): ...


def graphql_checks() -> None:
    from pyfect.graphql.client_error import GraphQLClientError as GqlError
    from pyfect.graphql.protocol import GraphQLProtocol as GqlProtocol

    viewer_op = graphql.query(
        "Viewer", document="query Viewer{viewer{login}}", result=S.Struct(GqlViewer)
    )
    assert_type(viewer_op, graphql.Operation[graphql.NoVariables, GqlViewer])
    by_id_op = graphql.query(
        "ById",
        document="query ById($id:ID!){viewer{login}}",
        result=S.Struct(GqlViewer),
        variables=S.Struct(GqlIssueId),
    )
    assert_type(by_id_op, graphql.Operation[GqlIssueId, GqlViewer])
    updated_op = graphql.subscription(
        "Updated", document="subscription Updated{viewer{login}}", result=S.Struct(GqlViewer)
    )
    assert_type(
        viewer_op.middleware(GqlAuth),
        graphql.Operation[graphql.NoVariables, GqlViewer, GqlTokenExpired, GqlCurrentUser],
    )

    class Plain(graphql.GraphQLGroup):
        viewer = viewer_op
        by_id = by_id_op
        updated = updated_op

    class Authed(graphql.GraphQLGroup[GqlAuth]):
        viewer = viewer_op

    class Merged(graphql.GraphQLGroup[Never, GqlAuth]):
        viewer = Authed.viewer

    # Middleware of single operations is declared as the second type argument
    # (a TypeError otherwise), so make() requires it (QA types 4).
    class OpOnly(graphql.GraphQLGroup[Never, GqlAuth]):
        viewer = viewer_op.middleware(GqlAuth)

    assert_type(graphql.make(Plain), fx.Effect[Plain, Never, GqlProtocol])
    assert_type(graphql.make(Authed), fx.Effect[Authed, Never, GqlProtocol | GqlAuth])
    assert_type(graphql.make(Merged), fx.Effect[Merged, Never, GqlProtocol | GqlAuth])
    assert_type(graphql.make(OpOnly), fx.Effect[OpOnly, Never, GqlProtocol | GqlAuth])
    only_protocol = graphql.make(OpOnly).pipe(fx.provide(layer.mock(GqlProtocol)))
    assert_type(only_protocol, fx.Effect[OpOnly, Never, GqlAuth])
    fx.run_sync(only_protocol)  # pyright: ignore[reportArgumentType]

    def use(plain: Plain, authed: Authed, merged: Merged, op_only: OpOnly) -> None:
        assert_type(plain.viewer(), fx.Effect[GqlViewer, GqlError])
        assert_type(
            plain.viewer(partial=True), fx.Effect[graphql.PartialResult[GqlViewer], GqlError]
        )
        assert_type(plain.by_id({"id": "1"}), fx.Effect[GqlViewer, GqlError])
        plain.by_id()  # pyright: ignore[reportCallIssue]
        plain.by_id({"id": 1})  # pyright: ignore[reportArgumentType]
        assert_type(plain.updated(), fx.Stream[GqlViewer, GqlError])
        assert_type(
            authed.viewer(), fx.Effect[GqlViewer, GqlError | GqlTokenExpired, GqlCurrentUser]
        )
        assert_type(
            merged.viewer(), fx.Effect[GqlViewer, GqlError | GqlTokenExpired, GqlCurrentUser]
        )
        assert_type(
            op_only.viewer(), fx.Effect[GqlViewer, GqlError | GqlTokenExpired, GqlCurrentUser]
        )

        # Resolvers: the key type comes from ``variables`` (or, for
        # ``aliased``, is the operation's variables); a miss is a
        # NoSuchElementException.
        def first_id(ids: Sequence[str]) -> GqlIssueId:
            return {"id": ids[0]}

        by_ids = graphql.resolver.ordered(plain.by_id, variables=first_id, path=("viewer",))
        get_one = graphql.resolver.request(by_ids)
        assert_type(get_one, Callable[[str], fx.Effect[Any, GqlError | fx.NoSuchElementException]])
        get_by = graphql.resolver.request(graphql.resolver.aliased(plain.by_id))
        assert_type(get_by, Callable[[GqlIssueId], fx.Effect[GqlViewer, GqlError]])
        get_by({"id": 1})  # pyright: ignore[reportArgumentType]
        authed_get = graphql.resolver.request(graphql.resolver.aliased(authed.viewer))
        assert_type(
            authed_get,
            Callable[
                [graphql.NoVariables],
                fx.Effect[GqlViewer, GqlError | GqlTokenExpired, GqlCurrentUser],
            ],
        )

    del use

    # Transports: subscriptions over graphql-ws add the WebSocket
    # constructor, the scope and the connection params' requirements.
    from pyfect.graphql.protocol import WebSocketOptions, make_http, make_web_socket
    from pyfect.http.client import HttpClient as GqlHttpClient
    from pyfect.socket import WebSocketConstructor as GqlWsConstructor

    assert_type(
        make_http(url="http://localhost/graphql"),
        fx.Effect[graphql.protocol.GraphQLProtocolService, Never, GqlHttpClient],
    )
    params = GqlCurrentUser().map(lambda user: {"token": user})
    assert_type(
        make_http(
            url="http://localhost/graphql",
            web_socket=WebSocketOptions(url="ws://localhost/graphql", connection_params=params),
        ),
        fx.Effect[
            graphql.protocol.GraphQLProtocolService,
            Never,
            GqlHttpClient | GqlWsConstructor | fx.Scope | GqlCurrentUser,
        ],
    )
    assert_type(
        make_web_socket(WebSocketOptions(url="ws://localhost/graphql")),
        fx.Effect[graphql.protocol.GraphQLProtocolService, Never, GqlWsConstructor | fx.Scope],
    )
    ws_options = WebSocketOptions(url="ws://localhost/graphql")
    make_http(url=lambda options: "http://x/graphql", web_socket=ws_options)  # pyright: ignore[reportCallIssue, reportArgumentType]


def eventlog_sql_checks() -> None:
    from pyfect.eventlog import event_journal as ev_journal
    from pyfect.eventlog import event_log_server_encrypted as ev_encrypted
    from pyfect.eventlog import event_log_server_unencrypted as ev_unencrypted
    from pyfect.eventlog import sql_event_journal as ev_sql_journal
    from pyfect.eventlog import sql_event_log_server_encrypted as ev_sql_encrypted
    from pyfect.eventlog import sql_event_log_server_unencrypted as ev_sql_unencrypted
    from pyfect.eventlog.event_log_encryption import EventLogEncryption as EvEncryption
    from pyfect.layer import Layer
    from pyfect.sql.client import SqlClient as EvSqlClient
    from pyfect.sql.error import SqlError as EvSqlError

    # SQL journal and storages: they need a SqlClient (and the encrypted one
    # EventLogEncryption, to hash scope keys); the journal opens its tables
    # once.
    assert_type(
        ev_sql_journal.layer(),
        Layer[ev_journal.EventJournal, EvSqlError, EvSqlClient],
    )
    assert_type(
        ev_sql_encrypted.layer_storage(),
        Layer[ev_encrypted.Storage, EvSqlError, EvSqlClient | EvEncryption],
    )
    assert_type(
        ev_sql_unencrypted.layer_storage(insert_batch_size=50),
        Layer[ev_unencrypted.Storage, EvSqlError, EvSqlClient],
    )


def eventlog_checks() -> None:
    from pyfect.devtools import client as devtools_client
    from pyfect.devtools import schema as devtools_schema
    from pyfect.devtools import server as devtools_server
    from pyfect.eventlog import event as ev_event
    from pyfect.eventlog import event_group as ev_group
    from pyfect.eventlog import event_journal as ev_journal
    from pyfect.eventlog import event_log as ev_log
    from pyfect.eventlog import event_log_server_encrypted as ev_encrypted
    from pyfect.eventlog import event_log_server_unencrypted as ev_unencrypted
    from pyfect.eventlog import event_row as ev_row
    from pyfect.layer import Layer
    from pyfect.socket import Socket as EvSocket
    from pyfect.socket.server import SocketServer as EvSocketServer
    from pyfect.socket.server import SocketServerError as EvSocketServerError

    class EvUser(TypedDict):
        id: str

    user_created = ev_event.make(
        "UserCreated", primary_key=lambda p: p["id"], payload=S.Struct(EvUser)
    )
    assert_type(user_created, ev_event.Event[EvUser, None, Never])
    group = ev_group.empty.add(user_created)
    assert_type(group, ev_group.EventGroup[ev_event.Event[EvUser, None, Never]])

    def use(log: ev_log.EventLogService) -> None:
        assert_type(
            log.write(user_created, {"id": "u1"}), fx.Effect[None, ev_journal.EventJournalError]
        )
        log.write(user_created, {"name": "u1"})  # pyright: ignore[reportCallIssue, reportArgumentType]

    del use

    handlers = ev_log.group(
        group,
        lambda h: h.handle(user_created, lambda i: fx.sync(lambda: i.payload["id"]).as_void()),
    )
    assert_type(handlers, Layer[Never, Never, ev_log.Registry])
    # The log gives its handlers the Registry: it is not passed on (quill #5).
    assert_type(
        ev_log.layer(ev_log.schema(group), handlers),
        Layer[ev_log.EventLog | ev_log.Registry, Never, ev_journal.EventJournal | ev_log.Identity],
    )

    # Rows: the payload is a set / patch / remove of the row's TypedDict.
    class EvGrocery(TypedDict):
        id: str
        name: str

    class EvGroceryPatch(TypedDict, total=False):
        name: str

    grocery = ev_row.make(
        "grocery", key="id", schema=S.Struct(EvGrocery), key_type=str, patch_fields=EvGroceryPatch
    )
    assert_type(grocery, ev_row.EventRow[EvGrocery, str, Never, EvGroceryPatch])
    assert_type(
        grocery.set({"id": "g1", "name": "milk"}),
        ev_event.Write[ev_row.Payload[EvGrocery, str], None, Never],
    )
    grocery.set({"id": "g1"})  # pyright: ignore[reportArgumentType]
    row_handler = ev_row.handler(
        grocery,
        set=lambda row, _key: fx.sync(lambda: row["name"]),
        patch=lambda _key, fields: fx.sync(lambda: fields.get("name")),
        remove=lambda _key: fx.void,
    )
    assert_type(
        row_handler,
        Callable[[ev_log.HandlerInput[ev_row.Payload[EvGrocery, str]]], fx.Effect[None]],
    )
    assert_type(
        ev_row.compaction(ev_group.empty.add(grocery), grocery),
        Layer[Never, Never, ev_log.Registry],
    )

    # Servers over memory storage.
    assert_type(ev_encrypted.layer_storage_memory, Layer[ev_encrypted.Storage])
    assert_type(ev_unencrypted.layer_storage_memory, Layer[ev_unencrypted.Storage])

    # DevTools: the tracer layer needs only a socket; the server needs a
    # socket server.
    assert_type(fx.devtools.layer(), Layer[Never])
    assert_type(fx.devtools.layer_socket, Layer[Never, Never, EvSocket])
    assert_type(
        devtools_client.make,
        fx.Effect[devtools_client.DevToolsClientService, Never, fx.Scope | EvSocket],
    )
    assert_type(
        devtools_server.run(lambda client: client.send({"_tag": "MetricsRequest"})),
        fx.Effect[Never, EvSocketServerError, EvSocketServer],
    )
    pong: devtools_schema.Response = {"_tag": "Pong"}
    del pong


def eventlog_typed_api_checks() -> None:
    """Dogfood quill #2, #3, #4, #5: the eventlog's public signatures carry types."""
    from pyfect.eventlog import event as ev_event
    from pyfect.eventlog import event_group as ev_group
    from pyfect.eventlog import event_journal as ev_journal
    from pyfect.eventlog import event_log as ev_log
    from pyfect.eventlog import event_log_remote as ev_remote
    from pyfect.eventlog import event_log_server_unencrypted as ev_unencrypted
    from pyfect.eventlog import event_row as ev_row
    from pyfect.layer import Layer
    from pyfect.rpc.server import ServerProtocol as EvServerProtocol

    class EvUser(TypedDict):
        id: str

    user_created = ev_event.make(
        "UserCreated", primary_key=lambda p: p["id"], payload=S.Struct(EvUser)
    )
    group = ev_group.empty.add(user_created)
    handlers = ev_log.group(group, lambda h: h.handle(user_created, lambda _i: fx.void))

    class EvDb(fx.Tag[str]): ...

    needs_db = ev_log.group(group, lambda h: h.handle(user_created, lambda _i: EvDb().as_void()))
    assert_type(needs_db, Layer[Never, Never, EvDb | ev_log.Registry])
    assert_type(
        ev_log.layer(ev_log.schema(group), needs_db),
        Layer[
            ev_log.EventLog | ev_log.Registry,
            Never,
            EvDb | ev_journal.EventJournal | ev_log.Identity,
        ],
    )
    assert_type(
        ev_unencrypted.layer(ev_log.schema(group), handlers),
        Layer[
            Never,
            Never,
            ev_unencrypted.EventLogServerAuthorization
            | EvServerProtocol
            | ev_unencrypted.Storage
            | ev_unencrypted.StoreMapping,
        ],
    )

    # A remote's when_authenticated needs the Identity and may fail
    # authenticating (quill #2).
    def remote_use(remote: ev_remote.EventLogRemoteService) -> None:
        assert_type(
            remote.when_authenticated(fx.succeed(1)),
            fx.Effect[int, ev_remote.EventLogRemoteError, ev_log.Identity],
        )
        assert_type(
            remote.when_authenticated(EvDb()),
            fx.Effect[str, ev_remote.EventLogRemoteError, EvDb | ev_log.Identity],
        )

    del remote_use

    write_client = ev_log.make_client(ev_log.schema(group))
    assert_type(write_client, fx.Effect[ev_log.WriteClient, Never, ev_log.EventLog])

    def client_use(client: ev_log.WriteClient) -> None:
        assert_type(
            client(ev_event.Write(user_created, {"id": "u1"})),
            fx.Effect[None, ev_journal.EventJournalError],
        )

    del client_use

    def synced_use(log: ev_log.EventLogService) -> None:
        assert_type(
            log.synced,
            fx.Effect[None, ev_journal.EventJournalError | ev_remote.EventLogRemoteError],
        )

    del synced_use

    class EvGrocery(TypedDict):
        id: str
        name: str

    class EvGroceryPatch(TypedDict, total=False):
        name: str

    grocery = ev_row.make(
        "grocery", key="id", schema=S.Struct(EvGrocery), key_type=str, patch_fields=EvGroceryPatch
    )
    # A patch writes non-key fields of their types, keyed by the key's type (quill #4).
    grocery.patch("g1", {"name": "oat milk"})
    grocery.patch("g1", {"nmae": "oat milk"})  # pyright: ignore[reportArgumentType]
    grocery.patch("g1", {"id": "g2"})  # pyright: ignore[reportArgumentType]
    grocery.patch("g1", {"name": 1})  # pyright: ignore[reportArgumentType]
    grocery.patch(1, {"name": "x"})  # pyright: ignore[reportArgumentType]
    untyped = ev_row.make("grocery", key="id", schema=S.Struct(EvGrocery))
    assert_type(untyped, ev_row.EventRow[EvGrocery, object, Never, Mapping[str, object]])


def cluster_core_types() -> None:
    from pyfect.cluster import cluster_error, runner_storage, shard_id, sharding_config, snowflake
    from pyfect.hash_ring import HashRing

    # Persistence failures of any effect become the cluster's PersistenceError.
    assert_type(
        cluster_error.PersistenceError.refail(fx.fail(ValueError())),
        fx.Effect[Never, cluster_error.PersistenceError],
    )
    # A cluster error's cause is a defect, an exception, as its schema checks
    # when it is made.
    cluster_error.PersistenceError(cause="down")  # pyright: ignore[reportArgumentType]
    cluster_error.MalformedMessage(cause=1)  # pyright: ignore[reportArgumentType]
    cluster_error.MalformedMessage.refail(fx.fail("not an exception"))  # pyright: ignore[reportArgumentType]
    assert_type(
        sharding_config.layer_from_env(), fx.Layer[sharding_config.ShardingConfig, fx.ConfigError]
    )
    assert_type(runner_storage.layer_memory, fx.Layer[runner_storage.RunnerStorage])
    assert_type(snowflake.layer_generator, fx.Layer[snowflake.Generator])
    ring = HashRing[shard_id.ShardId]()
    assert_type(ring.get("x"), shard_id.ShardId | None)
    # A ring holds only nodes with a primary key.
    HashRing[int]()  # pyright: ignore[reportInvalidTypeArguments]


def cluster_storage_types() -> None:
    from pyfect.cluster import (
        k8s_http_client,
        message_storage,
        sql_message_storage,
        sql_runner_storage,
    )
    from pyfect.cluster.runner_storage import RunnerStorage, RunnerStorageService
    from pyfect.cluster.sharding_config import ShardingConfig
    from pyfect.file_system import FileSystem
    from pyfect.http.client import HttpClient
    from pyfect.http.error import HttpClientError
    from pyfect.schema import SchemaError
    from pyfect.sql.client import SqlClient

    assert_type(
        message_storage.layer_memory,
        fx.Layer[message_storage.MessageStorage | message_storage.MemoryDriver],
    )
    # SQL storages need only a client and the sharding configuration.
    assert_type(
        sql_message_storage.layer,
        fx.Layer[message_storage.MessageStorage, Never, SqlClient | ShardingConfig],
    )
    assert_type(
        sql_runner_storage.layer, fx.Layer[RunnerStorage, Never, SqlClient | ShardingConfig]
    )
    assert_type(
        sql_runner_storage.make(prefix="p"),
        fx.Effect[RunnerStorageService, Never, SqlClient | ShardingConfig | fx.Scope],
    )
    assert_type(
        k8s_http_client.layer,
        fx.Layer[k8s_http_client.K8sHttpClient, Never, HttpClient | FileSystem],
    )
    assert_type(
        k8s_http_client.make_get_pods(),
        fx.Effect[
            fx.Effect[dict[str, k8s_http_client.Pod], HttpClientError | SchemaError],
            Never,
            k8s_http_client.K8sHttpClient,
        ],
    )


def cluster_entity_types() -> None:
    from pyfect.cluster import entity_resource, runner_health, runner_server, runners, singleton
    from pyfect.cluster.cluster_error import (
        AlreadyProcessingMessage,
        EntityNotAssignedToRunner,
        MailboxFull,
        PersistenceError,
    )
    from pyfect.cluster.entity import (
        ClusterClientError,
        CurrentAddress,
        Entity,
        EntityHandlers,
        Request,
        make_test_client,
    )
    from pyfect.cluster.message_storage import MessageStorage
    from pyfect.cluster.sharding import Sharding
    from pyfect.cluster.sharding_config import ShardingConfig
    from pyfect.rpc import RpcGroup
    from pyfect.rpc import make as make_rpc
    from pyfect.rpc.client_error import RpcClientError
    from pyfect.rpc.server import ServerProtocol
    from pyfect.stream import Stream

    class Counter(Entity):
        increment = make_rpc("Increment", payload=S.Int, success=S.String, error=S.String)
        watch = make_rpc("Watch", success=S.Int, stream=True)

    class PlainCounter(RpcGroup):
        increment = make_rpc("Increment", payload=S.Int, success=S.String)

    def check(counter: Counter, plain: PlainCounter) -> None:
        # Entity clients carry the cluster's client errors, plain RPC
        # clients the transport's; payload and success come from the RPC.
        assert_type(counter.increment(1), fx.Effect[str, str | ClusterClientError])
        assert_type(counter.watch(), Stream[int, ClusterClientError])
        assert_type(plain.increment(1), fx.Effect[str, RpcClientError])
        counter.increment("one")  # pyright: ignore[reportArgumentType]
        # ClusterClientError is the four errors a cluster send can fail with.
        assert_type(
            counter.increment(1).pipe(fx.catch_tag(MailboxFull, lambda _: fx.succeed("full"))),
            fx.Effect[
                str,
                str | AlreadyProcessingMessage | PersistenceError | EntityNotAssignedToRunner,
            ],
        )

    _ = check

    def increment(request: Request[int]) -> fx.Effect[str, str]:
        return fx.succeed(str(request.payload))

    handlers = (
        Counter.handlers()
        .handle(Counter.increment)(increment)
        .handle(Counter.watch)(lambda _: fx.stream.make(1))
    )
    assert_type(handlers, EntityHandlers[Counter, Never])
    layer = Counter.to_layer(handlers)
    assert_type(layer, fx.Layer[Never, Never, Sharding])
    assert_type(
        make_test_client(Counter, layer),
        fx.Effect[
            Callable[[str], fx.Effect[Counter]],
            Never,
            fx.Scope | ShardingConfig,
        ],
    )
    assert_type(CurrentAddress, type[CurrentAddress])

    assert_type(
        runners.layer_noop, fx.Layer[runners.Runners, Never, ShardingConfig | MessageStorage]
    )
    assert_type(
        runners.layer_rpc,
        fx.Layer[
            runners.Runners, Never, MessageStorage | runners.RpcClientProtocol | ShardingConfig
        ],
    )
    assert_type(
        runner_health.layer_ping, fx.Layer[runner_health.RunnerHealth, Never, runners.Runners]
    )
    assert_type(
        runner_server.layer, fx.Layer[Never, Never, ServerProtocol | Sharding | MessageStorage]
    )
    assert_type(singleton.make("leader", fx.void), fx.Layer[Never, Never, Sharding])
    assert_type(
        entity_resource.make(fx.succeed(1)),
        fx.Effect[
            entity_resource.EntityResource[int, Never],
            Never,
            fx.Scope | Sharding | CurrentAddress,
        ],
    )


def cluster_sharding_types() -> None:
    from pyfect.cluster import (
        entity_proxy,
        entity_proxy_server,
        sharding,
        single_runner,
        test_runner,
    )
    from pyfect.cluster.entity import Entity
    from pyfect.cluster.message_storage import MemoryDriver, MessageStorage
    from pyfect.cluster.runner_health import RunnerHealth
    from pyfect.cluster.runner_storage import RunnerStorage
    from pyfect.cluster.runners import Runners
    from pyfect.cluster.sharding import Sharding, ShardingService
    from pyfect.cluster.sharding_config import ShardingConfig
    from pyfect.cluster.sharding_registration_event import ShardingRegistrationEvent
    from pyfect.config import ConfigError
    from pyfect.http_api.api import HttpApi
    from pyfect.http_api.group import HttpApiGroup
    from pyfect.rpc import RpcGroup
    from pyfect.rpc.group import HandlersFor
    from pyfect.sql.client import SqlClient
    from pyfect.stream import Stream

    assert_type(
        sharding.layer,
        fx.Layer[
            Sharding,
            Never,
            ShardingConfig | Runners | MessageStorage | RunnerStorage | RunnerHealth,
        ],
    )
    assert_type(test_runner.layer, fx.Layer[Sharding | Runners | MessageStorage | MemoryDriver])
    assert_type(
        single_runner.layer(),
        fx.Layer[Sharding | Runners | MessageStorage, ConfigError, SqlClient],
    )

    def events(service: ShardingService) -> None:
        assert_type(service.get_registration_events, Stream[ShardingRegistrationEvent])

    class Counter(Entity):
        pass

    assert_type(entity_proxy.to_rpc_group(Counter), type[RpcGroup])
    assert_type(
        entity_proxy_server.layer_rpc_handlers(Counter),
        fx.Layer[HandlersFor[Any], Never, Sharding],
    )
    proxy_group = entity_proxy.to_http_api_group("counter", Counter)
    assert_type(proxy_group, type[HttpApiGroup[Any]])
    assert_type(
        entity_proxy_server.layer_http_api(
            HttpApi.make("Api").add(proxy_group), proxy_group, Counter
        ),
        fx.Layer[HttpApiGroup[Any], Never, Sharding],
    )
    del events


class ProxyUser(TypedDict):
    id: int


def check_entity_proxy_typed_endpoints() -> None:
    """``entity_proxy.http_endpoints`` declared in a group types the client."""
    from pyfect.cluster import entity_proxy, entity_proxy_server
    from pyfect.cluster.cluster_error import (
        AlreadyProcessingMessage,
        EntityNotAssignedToRunner,
        MailboxFull,
        PersistenceError,
    )
    from pyfect.cluster.entity import Entity
    from pyfect.cluster.sharding import Sharding
    from pyfect.http.error import HttpClientError
    from pyfect.http_api import test as api_test
    from pyfect.http_api.api import HttpApi
    from pyfect.http_api.client import get_group
    from pyfect.http_api.group import HttpApiGroup
    from pyfect.rpc import make as make_rpc
    from pyfect.schema import SchemaError

    class Users(Entity, type="Users"):
        rename = make_rpc("Rename", payload=S.Struct(ProxyUser), success=S.String, error=S.Number)

    class UsersProxy(HttpApiGroup, identifier="users"):
        rename, rename_discard = entity_proxy.http_endpoints(Users.rename)

    api = HttpApi.make("api").add(UsersProxy)
    assert_type(
        entity_proxy_server.layer_http_api(api, UsersProxy, Users),
        fx.Layer[UsersProxy, Never, Sharding],
    )

    def client():
        users = get_group((yield from api_test.groups(api, [UsersProxy])), UsersProxy)
        params: entity_proxy.EntityIdParams = {"entityId": "1"}
        assert_type(
            users.rename(params=params, payload={"id": 1}),
            fx.Effect[
                str,
                float
                | MailboxFull
                | AlreadyProcessingMessage
                | PersistenceError
                | EntityNotAssignedToRunner
                | HttpClientError
                | SchemaError,
            ],
        )
        assert_type(
            users.rename_discard(params=params, payload={"id": 1}),
            fx.Effect[
                None,
                MailboxFull
                | AlreadyProcessingMessage
                | PersistenceError
                | HttpClientError
                | SchemaError,
            ],
        )
        users.rename(payload={"id": 1})  # pyright: ignore[reportCallIssue]
        users.rename(params=params, payload={"id": "1"})  # pyright: ignore[reportArgumentType]

    _ = client


def package_namespace() -> None:
    # fx.<subpackage> is imported lazily at runtime; the type checker still
    # knows each one and rejects a name the package does not have.
    assert_type(fx.http.client.HttpClient, type[HttpClient])
    fx.not_a_module  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]  # noqa: B018
    # import pyfect.context reaches the module; fx.context is the effect.
    assert_type(fx.context(), fx.Effect[fx.Context[Never]])


def cluster_cron_workflow_types() -> None:
    from pyfect.cluster import cluster_cron, cluster_workflow_engine
    from pyfect.cluster.message_storage import MessageStorage
    from pyfect.cluster.sharding import Sharding
    from pyfect.cron import parse_unsafe
    from pyfect.workflow import Result, workflow
    from pyfect.workflow.workflow_engine import WorkflowEngine

    class Mailer(fx.Tag[str], key="Mailer"):
        pass

    # The scheduled time and the run's scope are provided by the cron.
    assert_type(
        cluster_cron.make(
            name="tick",
            cron=parse_unsafe("* * * * *"),
            execute=cluster_cron.CurrentScheduledTime().as_void(),
        ),
        fx.Layer[Never, Never, Sharding],
    )
    # Other services of execute stay required.
    assert_type(
        cluster_cron.make(
            name="mail",
            cron=parse_unsafe("* * * * *"),
            execute=Mailer().as_void(),
        ),
        fx.Layer[Never, Never, Sharding | Mailer],
    )
    assert_type(
        cluster_workflow_engine.layer,
        fx.Layer[WorkflowEngine, Never, Sharding | MessageStorage],
    )
    assert_type(
        workflow.result_schema(success=fx.schema.String, error=fx.schema.Number),
        fx.schema.Bottom[Result[str, float], Mapping[str, object]],
    )


def cluster_runner_layer_types() -> None:
    from pyfect.cluster import cluster_http, cluster_socket, http_runner
    from pyfect.cluster.message_storage import MessageStorage
    from pyfect.cluster.runner_storage import RunnerStorage
    from pyfect.cluster.runners import RpcClientProtocol, Runners
    from pyfect.cluster.sharding import Sharding
    from pyfect.config import ConfigError
    from pyfect.http.client import HttpClient
    from pyfect.rpc.serialization import RpcSerialization
    from pyfect.socket.server import SocketServerError
    from pyfect.sql.client import SqlClient

    # SQL storage (the default) needs a SqlClient; a runner can fail to listen.
    assert_type(
        cluster_socket.layer(),
        fx.Layer[Sharding | Runners | MessageStorage, SocketServerError | ConfigError, SqlClient],
    )
    # Local storage needs nothing; a client never listens.
    assert_type(
        cluster_socket.layer(client_only=True, storage="local"),
        fx.Layer[Sharding | Runners | MessageStorage, ConfigError],
    )
    # Bring-your-own storage leaves both storages required.
    assert_type(
        cluster_http.layer(transport="websocket", storage="byo"),
        fx.Layer[
            Sharding | Runners, SocketServerError | ConfigError, MessageStorage | RunnerStorage
        ],
    )
    assert_type(
        http_runner.layer_client_protocol_http(path="/runner"),
        fx.Layer[RpcClientProtocol, Never, RpcSerialization | HttpClient],
    )


def atom_state_types() -> None:
    from pyfect.reactivity import atom

    # atom.state infers its type from the value; subscripted, it takes the type given
    # (Effect's Atom.make<A>(value)), also through a method (DOGFOOD pulse #3)
    assert_type(atom.state(()), atom.Writable[tuple[()], tuple[()]])
    assert_type(
        atom.state[tuple[str, ...]](()).keep_alive(),
        atom.Writable[tuple[str, ...], tuple[str, ...]],
    )
    assert_type(atom.state[int | None](None), atom.Writable[int | None, int | None])
    atom.state[int](None)  # pyright: ignore[reportArgumentType]


def atom_types() -> None:
    from pyfect.reactivity import async_result, atom, atom_registry
    from pyfect.reactivity.async_result import AsyncResult
    from pyfect.reactivity.atom_registry import AtomRegistry

    counter = atom.make(0)
    assert_type(counter, atom.Writable[int, int])
    doubled = atom.make(lambda get: get(counter) * 2)
    assert_type(doubled, atom.Atom[int])
    assert_type(atom.make(lambda get: get.get(counter) + 1), atom.Atom[int])
    assert_type(atom.make(fx.succeed(1)), atom.Atom[AsyncResult[int, Never]])

    def needs_registry() -> fx.Effect[int, str, AtomRegistry]: ...

    failing = needs_registry()
    assert_type(atom.make(failing), atom.Atom[AsyncResult[int, str]])
    assert_type(atom.make(lambda get: fx.succeed(get(counter))), atom.Atom[AsyncResult[int, Never]])
    assert_type(
        atom.make(fx.stream.make(1, 2)),
        atom.Atom[AsyncResult[int, fx.NoSuchElementException]],
    )

    class Other(fx.Tag[int], key="type_checks/atom/Other"):
        pass

    def needs_other() -> fx.Effect[int, Never, Other]: ...

    other = needs_other()
    atom.make(other)  # pyright: ignore[reportDeprecated]

    # kind-preserving combinators are methods; a writable atom stays writable
    assert_type(counter.keep_alive(), atom.Writable[int, int])
    assert_type(counter.map(str), atom.Writable[str, int])
    assert_type(doubled.map(str), atom.Atom[str])
    results = atom.make(fx.succeed(1))
    assert_type(results.map_result(str), atom.Atom[AsyncResult[str, Never]])
    assert_type(counter.debounce(0.1), atom.Writable[int, int])

    def plus_one(n: int, _get: atom.FnContext) -> fx.Effect[int, str]: ...

    adder = atom.fn(plus_one)
    assert_type(
        adder, atom.Writable[AsyncResult[int, str], int | atom.ResetSignal | atom.InterruptSignal]
    )

    def double(n: int, _get: atom.FnContext) -> int: ...

    assert_type(atom.fn_sync(double), atom.Writable[fx.Option[int], int])
    assert_type(atom.fn_sync(double, initial_value=0), atom.Writable[int, int])
    assert_type(atom.get(counter), fx.Effect[int, Never, AtomRegistry])

    def counter_of(n: int) -> atom.Writable[int, int]:
        return atom.make(n)

    assert_type(atom.family(counter_of), Callable[[int], atom.Writable[int, int]])

    # a runtime carries its layer's services and error into its atoms
    other_layer = fx.layer.effect(Other, fx.fail("no other"))
    runtime = atom.runtime(other_layer)
    assert_type(runtime, atom.AtomRuntime[Other, str])
    assert_type(runtime.atom(other), atom.Atom[AsyncResult[int, str]])

    def uses_other(n: int, _get: atom.FnContext) -> fx.Effect[int, bool, Other]: ...

    assert_type(
        runtime.fn(uses_other),
        atom.Writable[AsyncResult[int, bool | str], int | atom.ResetSignal | atom.InterruptSignal],
    )

    registry = atom_registry.make()
    assert_type(registry.get(doubled), int)
    assert_type(atom_registry.get_result(registry, results), fx.Effect[int, Never, Never])
    assert_type(async_result.success(1), async_result.Success[int, Never])


def atom_rpc_types() -> None:
    from pyfect.reactivity import async_result, atom, atom_rpc, hydration
    from pyfect.reactivity.async_result import AsyncResult
    from pyfect.rpc import RpcClientError, RpcGroup, RpcMiddleware
    from pyfect.rpc import make as make_rpc

    class Failure(fx.TaggedError):
        pass

    class ClientSide(RpcMiddleware[Never, Failure], required_for_client=True):
        pass

    class Group(RpcGroup):
        get_user = make_rpc("getUser", payload=fx.schema.Number, success=fx.schema.String)
        guarded = make_rpc("guarded", success=fx.schema.String).middleware(ClientSide)
        events = make_rpc("events", success=fx.schema.String, stream=True).middleware(ClientSide)

    class Client(fx.Tag[Group], key="type_checks/atom_rpc/Client"):
        pass

    client = atom_rpc.make(Client, group=Group, protocol=fx.layer.empty)
    assert_type(client, atom_rpc.AtomRpcClient[Group, Client])
    assert_type(client.runtime, atom.AtomRuntime[Client, Never])
    assert_type(client.query(Group.get_user, 1), atom.Atom[AsyncResult[str, RpcClientError]])
    # client middleware errors reach the atoms' failures
    assert_type(
        client.mutation(Group.guarded),
        atom.AtomResultFn[atom_rpc.MutationRequest[None], str, Failure | RpcClientError],
    )
    assert_type(
        client.query(Group.guarded, None),
        atom.Atom[AsyncResult[str, Failure | RpcClientError]],
    )
    assert_type(
        client.query(Group.events, None),
        atom.Writable[atom.PullResult[str, Failure | RpcClientError], None],
    )
    assert_type(
        async_result.Schema(success=fx.schema.Number, error=fx.schema.String),
        async_result.AsyncResultSchema[float, str, float, str, Never, Never],
    )
    registry = fx.reactivity.atom_registry.make()
    assert_type(hydration.dehydrate(registry), list[hydration.DehydratedAtom])


def atom_http_api_types() -> None:
    from pyfect.http.response import HttpClientResponse
    from pyfect.http_api import client as api_client
    from pyfect.http_api import endpoint as ep
    from pyfect.http_api.api import HttpApi
    from pyfect.http_api.group import HttpApiGroup
    from pyfect.reactivity import atom, atom_http_api
    from pyfect.reactivity.async_result import AsyncResult

    class Users(HttpApiGroup, identifier="users"):
        create = ep.post("create", "/users", payload=fx.schema.String, success=fx.schema.Number)

    api = HttpApi.make("api").add(Users)

    class Client(fx.Tag[api_client.Client[Users]], key="type_checks/atom_http_api/Client"):
        pass

    client = atom_http_api.make(Client, api=api, http_client=fx.layer.empty)
    assert_type(client, atom_http_api.AtomHttpApiClient[Client, Users])
    assert_type(
        client.query(Users, Users.create, payload="x"), atom.Atom[AsyncResult[float, Never]]
    )
    assert_type(
        client.query(Users, Users.create, payload="x", response_mode="response-only"),
        atom.Atom[AsyncResult[HttpClientResponse, Never]],
    )
    assert_type(
        client.mutation(Users, Users.create),
        atom.AtomResultFn[atom_http_api.MutationRequest[None, None, str, None], float, Never],
    )

    # mutate: the endpoint as a function of its request parts, typed by the endpoint
    # (DOGFOOD pulse #1: a MutationRequest dict literal leaves the parts it lacks unsolved)
    from pyfect.reactivity.atom_registry import AtomRegistry

    class Ids(TypedDict):
        id: int

    class Items(HttpApiGroup, identifier="items"):
        rename = ep.patch(
            "rename",
            "/items/:id",
            params=fx.schema.Struct(Ids, id=fx.schema.Int),
            payload=fx.schema.String,
            success=fx.schema.String,
        )

    items_api = HttpApi.make("items").add(Items)

    class ItemsClient(fx.Tag[api_client.Client[Items]], key="type_checks/atom_http_api/Items"):
        pass

    items = atom_http_api.make(ItemsClient, api=items_api, http_client=fx.layer.empty)
    create = client.mutate(Users, Users.create)
    assert_type(create, atom_http_api.Mutate[None, None, str, None, float, Never])
    assert_type(
        create(payload="x", reactivity_keys=["users"]), fx.Effect[float, Never, AtomRegistry]
    )
    rename = items.mutate(Items, Items.rename)
    assert_type(rename(params={"id": 1}, payload="y"), fx.Effect[str, Never, AtomRegistry])
    assert_type(
        items.mutate(Items, Items.rename, response_mode="response-only")(params={"id": 1}),
        fx.Effect[HttpClientResponse, Never, AtomRegistry],
    )
    rename(params={"id": "1"})  # pyright: ignore[reportArgumentType]
    create(payload=1)  # pyright: ignore[reportArgumentType]
    create(params={"id": 1})  # pyright: ignore[reportArgumentType]
    # query_of: the strict, curried query. The endpoint fixes its parts before they are
    # checked, so a wrong part is an error (query(...) solves them with the endpoint, which
    # is covariant, and so widens to accept them).
    get_item = items.query_of(Items, Items.rename)
    assert_type(get_item, atom_http_api.Query[Ids, None, str, None, str, Never])
    assert_type(get_item(params={"id": 1}, payload="y"), atom.Atom[AsyncResult[str, Never]])
    assert_type(
        items.query_of(Items, Items.rename, response_mode="response-only")(params={"id": 1}),
        atom.Atom[AsyncResult[HttpClientResponse, Never]],
    )
    assert_type(
        items.query_of(Items, Items.rename, response_mode="decoded-and-response")(),
        atom.Atom[AsyncResult[tuple[str, HttpClientResponse], Never]],
    )
    assert_type(
        client.query_of(Users, Users.create)(
            payload="x", reactivity_keys=["users"], time_to_live=60, serialization_key="k"
        ),
        atom.Atom[AsyncResult[float, Never]],
    )
    get_item(params={"id": "1"})  # pyright: ignore[reportArgumentType]
    get_item(payload=1)  # pyright: ignore[reportArgumentType]
    get_item(query={"page": 1})  # pyright: ignore[reportArgumentType]
    client.query_of(Users, Users.create)(params={"id": 1})  # pyright: ignore[reportArgumentType]
    client.query_of(Items, Items.rename)  # pyright: ignore[reportCallIssue, reportArgumentType]
    # The leniency query_of works around: query(...) accepts the wrong part. Pinned so the
    # build fails once pyright rejects it, and query's own pins can be made strict.
    assert_type(
        items.query(Items, Items.rename, params={"id": "1"}), atom.Atom[AsyncResult[str, Never]]
    )
    # The limitation mutate works around; fails the build once pyright solves it.
    atom.set(
        items.mutation(Items, Items.rename),
        {"params": {"id": 1}, "payload": "y"},  # pyright: ignore[reportArgumentType]
    )

    class Admin(HttpApiGroup, identifier="admin"):
        reset = ep.post("reset", "/reset", success=fx.schema.Number)

    # A group the client's api lacks is a type error.
    client.query(Admin, Admin.reset)  # pyright: ignore[reportArgumentType, reportCallIssue]
    client.mutation(Admin, Admin.reset)  # pyright: ignore[reportArgumentType, reportCallIssue]


# --- catch_tag takes any number of classes (trawl T4; Effect's catchTag is variadic) ---


@dataclass
class TagA(fx.TaggedError):
    pass


@dataclass
class TagB(fx.TaggedError):
    pass


@dataclass
class TagC(fx.TaggedError):
    pass


@dataclass
class TagD(fx.TaggedError):
    pass


@dataclass
class TagE(fx.TaggedError):
    pass


@dataclass
class TagF(fx.TaggedError):
    pass


type _SixTags = TagA | TagB | TagC | TagD | TagE | TagF


def handle_tag_f(e: TagF) -> fx.Effect[int]:
    return fx.succeed(0)


def stream_tag_f(e: TagF) -> _St[int]:
    return fx.stream.make(1)


def check_catch_tag_any_number(
    eff: fx.Effect[str, _SixTags],
    st: _St[str, _SixTags],
    ch: _Ch[str, _SixTags, None, object, object, object, Never],
    failing: layer.Layer[Port, _SixTags],
) -> None:
    four = (TagA, TagB, TagC, TagD)
    assert_type(
        eff.pipe(fx.catch_tag(four, lambda e: fx.succeed(len(type(e).__name__)))),
        fx.Effect[str | int, TagE | TagF, Never],
    )
    assert_type(
        eff.pipe(fx.catch_tag((TagA, TagB, TagC, TagD, TagE, TagF), lambda e: fx.succeed(None))),
        fx.Effect[str | None, Never, Never],
    )
    assert_type(
        eff.pipe(
            fx.catch_tag(
                (TagA, TagB, TagC, TagD, TagE), lambda e: fx.succeed(0), or_else=handle_tag_f
            )
        ),
        fx.Effect[str | int, Never, Never],
    )
    assert_type(
        eff.tap_error_tag((TagA, TagB, TagC, TagD, TagE), fx.succeed),
        fx.Effect[str, _SixTags, Never],
    )
    assert_type(
        st.pipe(fx.stream.catch_tag(four, lambda _: fx.stream.make(0))),
        _St[str | int, TagE | TagF],
    )
    assert_type(
        st.pipe(
            fx.stream.catch_tag(
                (TagA, TagB, TagC, TagD, TagE),
                lambda _: fx.stream.make(0),
                or_else=stream_tag_f,
            )
        ),
        _St[str | int, Never],
    )
    assert_type(st.tap_error_tag(four, fx.succeed), _St[str, _SixTags])
    assert_type(
        ch.pipe(fx.channel.catch_tag(four, lambda _: fx.channel.succeed(0))),
        _Ch[str | int, TagE | TagF, None, object, object, object, Never],
    )
    assert_type(
        failing.pipe(layer.catch_tag((TagA, TagB, TagC, TagD, TagE), lambda _: port_live)),
        layer.Layer[Port, TagF],
    )


# --- catch_reasons takes as many cases as there are reasons (Effect's catchReasons record) ---


@dataclass
class Reason1:
    pass


@dataclass
class Reason2:
    pass


@dataclass
class Reason3:
    pass


@dataclass
class Reason4:
    pass


@dataclass
class Reason5:
    pass


@dataclass
class Reason6:
    pass


@dataclass
class Reason7:
    pass


@dataclass
class Reason8:
    pass


@dataclass
class ManyReasons(fx.TaggedError):
    reason: Reason1 | Reason2 | Reason3 | Reason4 | Reason5 | Reason6 | Reason7 | Reason8


def on_reason8(reason: Reason8, error: ManyReasons) -> fx.Effect[bytes]:
    return fx.succeed(b"")


def on_reason8_stream(reason: Reason8, error: ManyReasons) -> Stream[bytes]:
    return stream.succeed(b"")


def on_reason8_channel(reason: Reason8, error: ManyReasons) -> channel.Channel[int]:
    return channel.succeed(0)


def check_catch_reasons_any_number(
    eff: fx.Effect[str, ManyReasons | NotFound],
    s: Stream[str, ManyReasons | NotFound],
    ch: channel.Channel[int, ManyReasons | NotFound, None],
) -> None:
    assert_type(
        eff.pipe(
            fx.catch_reasons(
                ManyReasons,
                (Reason1, lambda r, _: fx.succeed(1)),
                (Reason2, lambda r, _: fx.succeed(2)),
                (Reason3, lambda r, _: fx.succeed(3)),
                (Reason4, lambda r, _: fx.succeed(4)),
                (Reason5, lambda r, _: fx.succeed(5)),
                (Reason6, lambda r, _: fx.succeed(6)),
                (Reason7, lambda r, _: fx.succeed(7)),
                (Reason8, lambda r, _: fx.succeed(None)),
            )
        ),
        fx.Effect[str | int | None, ManyReasons | NotFound, Never],
    )
    assert_type(
        eff.pipe(
            fx.catch_reasons(
                ManyReasons,
                (Reason1, lambda r, _: fx.succeed(1)),
                (Reason2, lambda r, _: fx.succeed(2)),
                (Reason3, lambda r, _: fx.succeed(3)),
                (Reason4, lambda r, _: fx.succeed(4)),
                (Reason5, lambda r, _: fx.succeed(5)),
                (Reason6, lambda r, _: fx.succeed(6)),
                (Reason7, lambda r, _: fx.succeed(7)),
                or_else=on_reason8,
            )
        ),
        fx.Effect[str | int | bytes, NotFound, Never],
    )
    assert_type(
        s.pipe(
            stream.catch_reasons(
                ManyReasons,
                (Reason1, lambda r, _: stream.succeed(1)),
                (Reason2, lambda r, _: stream.succeed(2)),
                (Reason3, lambda r, _: stream.succeed(3)),
                (Reason4, lambda r, _: stream.succeed(4)),
                (Reason5, lambda r, _: stream.succeed(5)),
                (Reason6, lambda r, _: stream.succeed(6)),
                (Reason7, lambda r, _: stream.succeed(7)),
                or_else=on_reason8_stream,
            )
        ),
        Stream[str | int | bytes, NotFound, Never],
    )
    assert_type(
        ch.pipe(
            channel.catch_reasons(
                ManyReasons,
                (Reason1, lambda r, _: channel.succeed(1)),
                (Reason2, lambda r, _: channel.succeed(2)),
                (Reason3, lambda r, _: channel.succeed(3)),
                (Reason4, lambda r, _: channel.succeed(4)),
                (Reason5, lambda r, _: channel.succeed(5)),
                (Reason6, lambda r, _: channel.succeed(6)),
                (Reason7, lambda r, _: channel.succeed(7)),
                or_else=on_reason8_channel,
            )
        ),
        channel.Channel[int, NotFound, None, object, object, object, Never],
    )
    # or_else must still cover the reasons the cases leave.
    eff.pipe(
        fx.catch_reasons(  # pyright: ignore[reportArgumentType]
            ManyReasons,
            (Reason1, lambda r, _: fx.succeed(1)),
            (Reason2, lambda r, _: fx.succeed(2)),
            (Reason3, lambda r, _: fx.succeed(3)),
            (Reason4, lambda r, _: fx.succeed(4)),
            (Reason5, lambda r, _: fx.succeed(5)),
            (Reason6, lambda r, _: fx.succeed(6)),
            or_else=on_reason8,
        )
    )


def collections_and_crypto(
    service: crypto.CryptoService,
    hm: HashMap[str, int],
    trie: Trie[int],
    version: semver.SemVer,
) -> None:
    from pyfect.platform_error import PlatformError as _PlatformError

    assert_type(crypto.layer, layer.Layer[crypto.Crypto])
    assert_type(service.random_bytes(8), fx.Effect[bytes, _PlatformError])
    assert_type(service.random_uuid_v4(), fx.Effect[str, _PlatformError])
    assert_type(service.random_uuid_v7(format="bytes"), fx.Effect[bytes, _PlatformError])
    assert_type(HashMap.make(("a", 1), ("b", 2)), HashMap[str, int])
    assert_type(hm.get("a"), fx.option.Option[int])
    assert_type(hm.set("c", 3), HashMap[str, int])
    assert_type(HashSet.make(1, 2), HashSet[int])
    assert_type(hm.union(HashMap.make((1, "x"))), HashMap[str | int, int | str])
    assert_type(HashSet.make(1).union(HashSet.make("a")), HashSet[int | str])
    assert_type(trie.get("a"), fx.option.Option[int])
    assert_type(trie.longest_prefix_of("abc"), fx.option.Option[tuple[str, int]])
    assert_type(semver.parse("1.2.3"), fx.result.Result[semver.SemVer, semver.SemVerError])
    assert_type(version.difference(version), semver.ReleaseType | None)
    assert_type(semver_range.parse_unsafe("^1").max_satisfying([version]), semver.SemVer | None)
    assert_type(big_decimal.from_string("1.5"), big_decimal.BigDecimal | None)
    assert_type(
        big_decimal.make(1, 0).divide(big_decimal.make(3, 0)), big_decimal.BigDecimal | None
    )
    assert_type(base64.decode("AA=="), fx.result.Result[bytes, EncodingError])
    one = big_decimal.make(1, 0)
    assert_type(one + one, big_decimal.BigDecimal)
    one + 1  # pyright: ignore[reportOperatorIssue, reportUnusedExpression]
    hm.set(1, 2)  # pyright: ignore[reportArgumentType]


# --- Schema leftovers (M11) ------------------------------------------------------------------


def check_schema_template_literals() -> None:
    from pyfect import schema as S

    assert_type(S.TemplateLiteral("a", S.String, 1), S.TemplateLiteralSchema)
    assert_type(S.TemplateLiteral(["a", S.String]), S.TemplateLiteralSchema)
    assert_type(S.decode_unknown_sync(S.TemplateLiteral("a", S.String))(1), str)
    assert_type(
        S.TemplateLiteralParser("a", S.FiniteFromString),
        S.TemplateLiteralParserSchema[Never, Never],
    )
    assert_type(S.decode_sync(S.TemplateLiteralParser("a", S.Int))("a1"), tuple[Any, ...])
    S.TemplateLiteral("a", object())  # pyright: ignore[reportArgumentType]


def check_schema_leftover_values() -> None:
    import re
    from datetime import timedelta
    from ipaddress import IPv4Address, IPv6Network

    from pyfect import big_decimal, semver
    from pyfect.net import dns, host
    from pyfect.net import net_address as na

    big = big_decimal.from_string_unsafe("1.5")
    assert_type(S.decode_unknown_sync(S.BigDecimalFromString)("1.5"), big_decimal.BigDecimal)
    assert_type(S.encode_sync(S.BigDecimalFromString)(big), str)
    S.BigDecimal.check(S.is_between_big_decimal(minimum=big, maximum=big))
    S.BigDecimal.check(S.is_greater_than_big_decimal(1.5))  # pyright: ignore[reportArgumentType]
    assert_type(S.decode_unknown_sync(S.RegExp)(re.compile("a")), re.Pattern[str])
    assert_type(S.decode_unknown_sync(S.DurationFromMillis)(1), timedelta)
    assert_type(S.encode_sync(S.DurationFromNanos)(timedelta(0)), int)
    assert_type(S.decode_unknown_sync(S.SemVerFromString)("1.0.0"), semver.SemVer)
    assert_type(S.decode_unknown_sync(S.BooleanLiterals)("yes"), bool)
    assert_type(S.decode_unknown_sync(S.Ipv4AddressFromString)("1.2.3.4"), IPv4Address)
    assert_type(S.decode_unknown_sync(S.IpAddressFromString)("::1"), na.IpAddress)
    assert_type(S.decode_unknown_sync(S.IpMulticastAddress)(None), na.IpAddress)
    assert_type(S.decode_unknown_sync(S.Ipv6NetworkFromString)("::/0"), IPv6Network)
    assert_type(S.decode_unknown_sync(S.DomainNameFromString)("a.b"), host.DomainName)
    assert_type(S.decode_unknown_sync(S.HostFromString)("a.b"), host.Host)
    assert_type(S.decode_unknown_sync(S.DnsRecord)(None), dns.DnsRecord)
    assert_type(S.decode_unknown_sync(S.DnsMxRecord)(None), dns.Mx)


def check_effectable() -> None:
    from pyfect import effectable

    class Answer(effectable.Class[int, str]):
        def as_effect(self) -> fx.Effect[int, str]:
            return fx.succeed(42)

    class Wrong(effectable.Class[int]):
        def as_effect(self) -> fx.Effect[str]:  # pyright: ignore[reportIncompatibleMethodOverride]
            return fx.succeed("no")

    answer = Answer()
    assert_type(answer.map(lambda n: n + 1), fx.Effect[int, str])
    wide: fx.Effect[int | None, str | ValueError] = answer
    assert_type(Answer().catch_all(lambda _: fx.succeed(0)), fx.Effect[int, Never, Never])
    del wide, Wrong


def check_test_crypto() -> None:
    from pyfect.crypto import Crypto, CryptoService

    assert_type(fx.testing.TestCrypto.make("seed"), fx.Effect[CryptoService, Never, Crypto])
    assert_type(fx.testing.TestCrypto.layer(1), fx.Layer[Crypto, Never, Crypto])


def check_graph() -> None:
    from pyfect import graph
    from pyfect.graph import (
        AllPairsResult,
        Edge,
        Graph,
        MutableGraph,
        PathResult,
        Snapshot,
        Walker,
    )

    def build(m: MutableGraph[str, int]) -> None:
        a, b = m.add_node("A"), m.add_node("B")
        m.add_edge(a, b, 1)

    g = graph.directed(build)
    assert_type(g, Graph[str, int, Literal["directed"]])
    u = graph.undirected(lambda m: None)
    assert_type(graph.directed(), Graph[Never, Never, Literal["directed"]])
    assert_type(graph.make("undirected"), Graph[Never, Never, Literal["undirected"]])
    assert_type(g.begin_mutation(), MutableGraph[str, int, Literal["directed"]])
    assert_type(g.mutate(lambda m: None), Graph[str, int, Literal["directed"]])
    assert_type(g.begin_mutation().end_mutation(), Graph[str, int, Literal["directed"]])
    assert_type(g.get_node(0), fx.option.Option[str])
    assert_type(g.get_edge(0), Edge[int] | None)
    assert_type(g.find_node(lambda n: n == "A"), int | None)
    assert_type(g.dijkstra(source=0, target=1, cost=float), PathResult[int] | None)
    assert_type(g.floyd_warshall(float), AllPairsResult[int])
    assert_type(g.bfs(start=[0]), Walker[int, str])
    assert_type(g.edges(), Walker[int, Edge[int]])
    assert_type(list(g.bfs(start=[0]).values()), list[str])
    assert_type(g.topo(), Walker[int, str])
    assert_type(g.to_snapshot(), Snapshot[str, int, Literal["directed"]])
    assert_type(graph.from_snapshot(g.to_snapshot()), Graph[str, int, Literal["directed"]])
    assert_type(g.transitive_reduction(), Graph[str, int, Literal["directed"]])

    # Covariant: an immutable graph of ``str`` nodes is a graph of objects;
    # a mutable one (``add_node`` takes ``N``) is not.
    wide: Graph[object, object, graph.Kind] = g
    narrow: MutableGraph[object, int] = g.begin_mutation()  # pyright: ignore[reportAssignmentType]

    # Kind-specific methods only exist for their kind.
    g.degree(0)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    u.topo()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    u.successors(0)  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    g.is_bipartite()  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]
    g.compose(u)  # pyright: ignore[reportArgumentType]
    # A callback's result is ignored, as Effect's ``(mutable) => void``.
    assert_type(g.mutate(lambda m: m.add_node("C")), Graph[str, int, Literal["directed"]])
    g.mutate(lambda m: [m.add_node(1)])  # pyright: ignore[reportArgumentType]
    del wide, narrow


def schema_representation_types() -> None:
    from typing import TypedDict as _TypedDict

    from pyfect.schema import representation as R

    document = R.to_representation(S.String)
    assert_type(document, R.Document)
    assert_type(R.to_representations((S.String, S.Number)), R.MultiDocument)
    assert_type(R.to_json(document), R.Json)
    assert_type(R.from_json({}), R.Document)
    # Revived schemas know their node, not their types (Effect's ``Top``).
    revived = R.from_representation(document, revivers=R.BUILTIN_REVIVERS)
    assert_type(revived, R.AnySchema)
    first, *_ = R.from_representations(R.to_multi_document(document), revivers=())
    assert_type(first, R.AnySchema)

    class Minimum(_TypedDict):
        minimum: float

    # A reviver's payload is typed by its payload schema.
    reviver = R.make_reviver_filter(
        "acme/min", S.Struct(Minimum), lambda input: S.is_greater_than(input.payload["minimum"])
    )
    assert_type(reviver, R.FilterReviver[Minimum])
    R.make_reviver_filter(
        "acme/min",
        S.Struct(Minimum),
        lambda input: S.is_greater_than(input.payload["maximum"]),  # pyright: ignore[reportGeneralTypeIssues, reportUnknownArgumentType]
    )
    # A filter reviver returns a filter, not a group.
    R.make_reviver_filter("acme/min", S.Null, lambda _: S.make_filter_group(S.is_int()))  # pyright: ignore[reportArgumentType]
    # Representations are frozen data.
    R.String().checks = ()  # pyright: ignore[reportAttributeAccessIssue]


# --- Schema rest (M11b) -------------------------------------------------------------------------


def schema_rest_types() -> None:
    from datetime import timedelta, timezone
    from typing import TypedDict as _TypedDict

    from pyfect.http import cookies as http_cookies
    from pyfect.http import headers as http_headers
    from pyfect.http import schema as HS
    from pyfect.http import url_params as http_url_params
    from pyfect.option import Option, Some
    from pyfect.schema import getter as G
    from pyfect.schema import issue as I
    from pyfect.schema import transformation as T
    from pyfect.schema._transform import DecodeToSchema

    # A constructor default keeps the schema's types and must match its Type.
    defaulted = S.FiniteFromString.pipe(S.with_constructor_default(fx.succeed(1.0)))
    assert_type(defaulted, S.WithConstructorDefault[float, str, Never, Never])
    S.String.pipe(S.with_constructor_default(fx.succeed(1)))  # pyright: ignore[reportArgumentType]
    assert_type(S.tag("a"), S.WithConstructorDefault[Literal["a"], Literal["a"], Never, Never])

    class _A(_TypedDict):
        a: float

    class _B(_A):
        b: str

    def derive_b(value: _A) -> Option[object]:
        return Some(str(value["a"]))

    renamed = S.Struct(_A).pipe(S.encode_keys({"a": "c"}))
    assert_type(renamed, S.Bottom[_A, Mapping[str, object], Never, Never])
    extended = S.Struct(_A).pipe(S.extend_to(_B, {"b": derive_b}))
    assert_type(extended, DecodeToSchema[_B, Mapping[str, object], Never, Never])
    assert_type(S.Tree(S.Number), S.Bottom[S.TreeValue[float], S.TreeValue[float], Never, Never])

    assert_type(T.duration_from_string, T.Transformation[timedelta, str])
    assert_type(T.time_zone_offset_from_number, T.Transformation[timezone, int])
    entries: list[tuple[str, str]] = [("a", "1")]
    assert_type(G.make_tree_record(entries), dict[str, S.TreeValue[str | None]])

    assert_type(I.make_formatter_standard_schema_v1()(I.InvalidValue({})), I.StandardFailure)
    _hook: I.CheckHook = I.default_check_hook

    assert_type(HS.Headers, S.Bottom[http_headers.Headers])
    assert_type(HS.RecordFromCookies, DecodeToSchema[dict[str, str], http_cookies.Cookies])
    assert_type(HS.UrlParams, S.Bottom[http_url_params.UrlParams])
    assert_type(HS.DateTimeUtcFromHttpDate, DecodeToSchema[datetime, str])


def check_schema_graph() -> None:
    from pyfect import graph

    schema = S.Graph("directed", S.String, S.FiniteFromString)
    assert_type(schema, S.GraphSchema[str, float, str, str, Literal["directed"], Never, Never])
    assert_type(S.decode_unknown_sync(schema)(None), graph.Graph[str, float, Literal["directed"]])
    undirected = S.Graph("undirected", S.String, S.Number)
    assert_type(
        S.encode_sync(undirected)(graph.undirected()),
        graph.Graph[str, float, Literal["undirected"]],
    )
    S.Graph("cyclic", S.String, S.Number)  # pyright: ignore[reportArgumentType]
    S.encode_sync(undirected)(graph.directed())  # pyright: ignore[reportArgumentType]


# --- constructors honour a subscript ------------------------------------------------
# X[T].make(...) makes an X[T]; bare X.make(...) infers T from the arguments
# (tests/test_subscript_constructors.py lists every constructor).

type JobState = Literal["waiting", "running"]


def check_data_constructors_honour_a_subscript() -> None:
    from pyfect.mutable_hash_map import MutableHashMap
    from pyfect.mutable_hash_set import MutableHashSet
    from pyfect.tx_chunk import TxChunk
    from pyfect.tx_hash_map import TxHashMap
    from pyfect.tx_hash_set import TxHashSet

    assert_type(
        TxHashMap[int, JobState].from_iterable([(1, "waiting")]),
        fx.Effect[TxHashMap[int, JobState]],
    )
    assert_type(TxHashMap[int, JobState].make((1, "waiting")), fx.Effect[TxHashMap[int, JobState]])
    assert_type(TxHashMap.make((1, "waiting")), fx.Effect[TxHashMap[int, str]])
    TxHashMap[int, JobState].make((1, "done"))  # pyright: ignore[reportArgumentType]
    assert_type(TxHashSet[JobState].make("waiting"), fx.Effect[TxHashSet[JobState]])
    assert_type(TxHashSet[JobState].from_iterable(["waiting"]), fx.Effect[TxHashSet[JobState]])
    assert_type(
        TxHashSet[int | None].from_hash_set(HashSet.make(1)), fx.Effect[TxHashSet[int | None]]
    )
    assert_type(TxChunk[int | None].make([1]), fx.Effect[TxChunk[int | None]])
    assert_type(TxChunk[int | None].from_iterable([1]), fx.Effect[TxChunk[int | None]])
    assert_type(fx.TxRef[int | None].make(None), fx.Effect[fx.TxRef[int | None]])
    assert_type(fx.TxRef.make(None), fx.Effect[fx.TxRef[None]])
    assert_type(
        fx.TxSubscriptionRef[int | None].make(None), fx.Effect[fx.TxSubscriptionRef[int | None]]
    )
    assert_type(fx.TxPriorityQueue[float].make(1, 2), fx.Effect[fx.TxPriorityQueue[float]])
    assert_type(fx.TxPriorityQueue[float].from_iterable([1]), fx.Effect[fx.TxPriorityQueue[float]])
    assert_type(fx.TxPriorityQueue[float].empty(), fx.Effect[fx.TxPriorityQueue[float]])
    assert_type(
        fx.TxPriorityQueue[bytes | str].make(b"a", key=len),
        fx.Effect[fx.TxPriorityQueue[bytes | str]],
    )
    assert_type(fx.Ref[int | None].make(None), fx.Effect[fx.Ref[int | None]])
    assert_type(fx.Ref.make(None), fx.Effect[fx.Ref[None]])
    fx.Ref[int].make("a")  # pyright: ignore[reportArgumentType]
    assert_type(
        fx.SynchronizedRef[int | None].make(None), fx.Effect[fx.SynchronizedRef[int | None]]
    )
    assert_type(
        fx.SubscriptionRef[int | None].make(None), fx.Effect[fx.SubscriptionRef[int | None]]
    )
    assert_type(
        fx.ScopedRef[int | None].make(lambda: None),
        fx.Effect[fx.ScopedRef[int | None], Never, fx.Scope],
    )
    assert_type(
        fx.ScopedRef[int | None].from_acquire(fx.succeed(None)),
        fx.Effect[fx.ScopedRef[int | None], Never, fx.Scope],
    )
    assert_type(HashMap[int, JobState].make((1, "waiting")), HashMap[int, JobState])
    assert_type(HashMap[int, JobState].from_iterable([(1, "waiting")]), HashMap[int, JobState])
    assert_type(HashSet[JobState].make("waiting"), HashSet[JobState])
    assert_type(HashSet[JobState].from_iterable(["waiting"]), HashSet[JobState])
    assert_type(MutableHashMap[int, JobState].make((1, "waiting")), MutableHashMap[int, JobState])
    assert_type(
        MutableHashMap[int, JobState].from_iterable([(1, "waiting")]),
        MutableHashMap[int, JobState],
    )
    assert_type(MutableHashSet[JobState].make("waiting"), MutableHashSet[JobState])
    assert_type(MutableHashSet[JobState].from_iterable(["waiting"]), MutableHashSet[JobState])
    assert_type(Trie[int | None].make(("a", 1)), Trie[int | None])
    assert_type(Trie[int | None].from_iterable([("a", 1)]), Trie[int | None])
    assert_type(
        fx.PubSub[int | None].make(lambda: Atomic[int | None].bounded(4), "sliding"),
        fx.Effect[fx.PubSub[int | None]],
    )


def check_builders_honour_a_subscript(
    strategy: Strategy[int | None, NotFound | Invalid], parent: fx.CloseableScope
) -> None:
    from pyfect.cluster._resource_map import ResourceMap
    from pyfect.cluster._resource_ref import ResourceRef

    assert_type(
        fx.Cache[str, int | None, NotFound].make(_lookup_port, capacity=2),
        fx.Effect[fx.Cache[str, int | None, NotFound], Never, Port],
    )
    assert_type(
        fx.ScopedCache[str, int | None, NotFound].make(_scoped_port, capacity=2),
        fx.Effect[fx.ScopedCache[str, int | None, NotFound], Never, fx.Scope | Port],
    )
    assert_type(
        fx.RcMap[str, int | None, NotFound].make(_lookup_port),
        fx.Effect[fx.RcMap[str, int | None, NotFound], Never, fx.Scope | Port],
    )
    assert_type(
        fx.RcRef[int | None].make(fx.succeed(1)),
        fx.Effect[fx.RcRef[int | None], Never, fx.Scope],
    )
    assert_type(
        fx.Pool[int | None].make(fx.succeed(1), size=2),
        fx.Effect[fx.Pool[int | None], Never, fx.Scope],
    )
    assert_type(
        fx.Pool[int | None].make_with_ttl(fx.succeed(1), min=0, max=1, time_to_live=1),
        fx.Effect[fx.Pool[int | None], Never, fx.Scope],
    )
    assert_type(
        fx.Pool[int | None, NotFound | Invalid].make_with_strategy(
            fx.succeed(1), min=0, max=1, strategy=strategy
        ),
        fx.Effect[fx.Pool[int | None, NotFound | Invalid], Never, fx.Scope],
    )
    assert_type(
        fx.Resource[int | None].manual(fx.succeed(1)),
        fx.Effect[fx.Resource[int | None], Never, fx.Scope],
    )
    assert_type(
        fx.Resource[int | None].auto(fx.succeed(1), schedule.spaced(1)),
        fx.Effect[fx.Resource[int | None], Never, fx.Scope],
    )
    assert_type(
        fx.LayerMap[str, Port, NotFound | Invalid].make(_port_layer),
        fx.Effect[fx.LayerMap[str, Port, NotFound | Invalid], Never, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerMap[str, Port, NotFound | Invalid].from_record({"a": failing_port_live}),
        fx.Effect[fx.LayerMap[str, Port, NotFound | Invalid], Never, fx.Scope | Primary],
    )
    assert_type(
        fx.LayerRef[Port, NotFound | Invalid].make(failing_port_live),
        fx.Effect[fx.LayerRef[Port, NotFound | Invalid], Never, fx.Scope | Primary],
    )
    assert_type(
        ResourceMap[str, int | None, NotFound].make(_scoped_port),
        fx.Effect[ResourceMap[str, int | None, NotFound], Never, Port | fx.Scope],
    )
    assert_type(
        ResourceRef[int | None].make(parent, lambda _scope: fx.succeed(1)),
        fx.Effect[ResourceRef[int | None]],
    )
    assert_type(fx.Logger[object].make(lambda o: len(o.message)), fx.Logger[object])
    assert_type(
        fx.RequestResolver[GetUser].from_function(lambda entry: entry.request.id),
        fx.RequestResolver[GetUser],
    )
    assert_type(
        fx.RequestResolver[GetUser].from_function_batched(lambda entries: [1 for _ in entries]),
        fx.RequestResolver[GetUser],
    )
    assert_type(
        fx.RequestResolver[GetUser].from_effect(lambda _entry: fx.void),
        fx.RequestResolver[GetUser],
    )
    assert_type(
        fx.RequestResolver[GetUser].make_grouped(
            key=lambda entry: entry.request.id, resolver=lambda _entries, _key: fx.void
        ),
        fx.RequestResolver[GetUser],
    )
    assert_type(
        fx.RequestResolver[GetUser].from_effect_tagged(
            {GetUser: lambda es: fx.succeed(["a"] * len(es))}
        ),
        fx.RequestResolver[GetUser],
    )


def encoding_toml_types() -> None:
    from pyfect.encoding import toml

    assert_type(toml.parse("a = 1"), dict[str, Any])


class _BinaryPoint(TypedDict):
    x: float


_binary_points = S.Struct(_BinaryPoint)
_binary_codec = schema_binary.to_codec(_binary_points)
assert_type(S.encode_sync(_binary_codec)({"x": 1}), bytes)
assert_type(S.decode_sync(_binary_codec)(b""), _BinaryPoint)
assert_type(schema_binary.parser(_binary_points).feed_sync(b""), list[_BinaryPoint])
assert_type(schema_binary.encoder(_binary_points, fingerprint=True).encode({"x": 1}), bytes)
assert_type(schema_binary.encode_unknown_sync(_binary_points)({"x": 1}), bytes)
