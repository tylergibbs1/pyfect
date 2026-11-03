"""pyfect: Effect for Python.

    import pyfect as fx

Constructors and run functions live at the top level. Data types and
their modules: ``fx.cause``, ``fx.option``, ``fx.result``, ``fx.exit``, ``fx.filters``,
``fx.layer``,
``fx.clock``, ``fx.config`` (``fx.Config``, ``fx.ConfigError``), ``fx.config_provider``,
``fx.console``, ``fx.cron``, ``fx.date_time``, ``fx.random``, ``fx.redacted``
(``fx.Redacted``), ``fx.byte_size``, ``fx.brand``, ``fx.case`` (case
conversion), ``fx.big_decimal``, ``fx.semver``, ``fx.semver_range``, ``fx.trie``,
``fx.graph`` (directed and undirected graphs),
``fx.hash_map``, ``fx.hash_set``, ``fx.mutable_hash_map``, ``fx.mutable_hash_set``,
``fx.schema`` (schemas: decode, validate, encode), ``fx.json_schema``
(JSON Schema dialects), ``fx.json_pointer``, ``fx.json_patch``, ``fx.schedule``,
``fx.scheduler``,
``fx.Queue``, ``fx.PubSub``, ``fx.Pool``, ``fx.Cache``, ``fx.ScopedCache``, ``fx.Ref``,
``fx.SynchronizedRef``, ``fx.SubscriptionRef``, ``fx.Deferred``,
``fx.Semaphore``, ``fx.PartitionedSemaphore``, ``fx.Latch``, ``fx.FiberSet``,
``fx.FiberMap``, ``fx.FiberHandle``, ``fx.RcRef``, ``fx.RcMap``, ``fx.ScopedRef``,
``fx.Resource``, ``fx.LayerRef``, ``fx.LayerMap``, ``fx.testing``. Transactions:
``fx.tx``, ``fx.tx_retry``, ``fx.Transaction`` (metadata types in ``fx.transaction``),
``fx.TxRef``, ``fx.TxChunk``, ``fx.TxHashMap``, ``fx.TxHashSet``, ``fx.TxQueue``
(views ``fx.TxEnqueue`` / ``fx.TxDequeue``), ``fx.TxDeferred``, ``fx.TxSemaphore``,
``fx.TxReentrantLock``, ``fx.TxPriorityQueue``, ``fx.TxPubSub``, ``fx.TxSubscriptionRef``. Logging:
``fx.log`` and its levels, ``fx.LogLevel``, ``fx.Logger`` (formatters and layers in
``fx.logger``). Tracing: ``eff.with_span``, ``fx.fn("name")``, ``fx.use_span``,
``fx.current_span`` and the rest; spans and tracers in ``fx.tracer``. Metrics:
``fx.metric`` (``counter``, ``gauge``, ``histogram``, ``summary``, ``frequency``,
``timer``, ``snapshot``, ``prometheus_format``) and ``eff.track*``. Request batching:
``fx.Request``, ``fx.RequestResolver``, ``fx.request`` (``Entry`` and the rest in
``fx.batching``). Error reporting: ``eff.with_error_reporting()``, ``fx.ErrorReporter``
(``make``, ``layer``, ``report`` in ``fx.error_reporter``). Streaming
building blocks: ``fx.Stream`` (constructors in ``fx.stream``), ``fx.Sink``
(constructors in ``fx.sink``), ``fx.Channel``
(constructors in ``fx.channel``), ``fx.Pull`` (helpers in ``fx.pull``), ``fx.Take``
(``fx.take``); framers (NDJSON, JSON arrays, Server-Sent Events) in ``fx.encoding``;
channels decoding and encoding chunks with a schema in ``fx.channel_schema``.
Platform: ``fx.FileSystem`` (``fx.file_system``), ``fx.Path`` (``fx.path``),
``fx.Stdio`` (``fx.stdio``), ``fx.Crypto`` (``fx.crypto``), ``fx.Terminal``
(``fx.terminal``), child processes (``fx.process``: ``make``,
``ChildProcessSpawner``), ``fx.PlatformError`` (``fx.platform_error``) and all
six live services in ``fx.platform.layer``.
Command-line apps in ``fx.cli`` (``Command``, ``Flag``, ``Argument``, prompts,
help and shell completions).
HTTP clients in ``fx.http`` (``HttpClient``, requests, responses, headers,
cookies, URLs).
Durable workflows in ``fx.workflow`` (``Workflow``, activities, durable
deferreds, clocks and queues, ``WorkflowEngine`` and its in-memory layer).
AI services in ``fx.ai`` (prompts, responses, tools, toolkits and the
provider-neutral ``LanguageModel``).
Optional adapters, each behind its extra and never imported here: pydantic
(``pyfect.pydantic``, ``pyfect-dev[pydantic]``), msgspec (``pyfect.msgspec``,
``pyfect-dev[msgspec]``) and the httpx HTTP client (``pyfect.http.httpx_client``,
``pyfect-dev[httpx]``).
"""

import importlib as _importlib
import typing as _typing
from types import ModuleType as _ModuleType

from pyfect._all import all, all_dict
from pyfect._concurrency import Concurrency, for_each, race_all, race_all_first
from pyfect._context_managers import acquire_async_context, acquire_context
from pyfect._core import Effect, Restore, interruptible_mask, uninterruptible_mask
from pyfect._fiber import Fiber
from pyfect._iterables import (
    filter,
    filter_map,
    filter_map_effect,
    find_first,
    find_first_filter,
    first_success_of,
    partition,
    reduce,
    validate,
)
from pyfect._public import publish
from pyfect._reasons import HasReason
from pyfect._root import NoRunError
from pyfect.batching import Request, RequestResolver, request, request_unsafe
from pyfect.cache import Cache, ScopedCache
from pyfect.cause import Cause, EmptyCauseError, Interrupted, UnhandledError
from pyfect.channel import Channel
from pyfect.clock import Clock, sleep
from pyfect.config import Config, ConfigError
from pyfect.config_provider import ConfigProvider, CurrentConfigProvider
from pyfect.context import Context, MissingServiceError, Reference, Tag
from pyfect.crypto import Crypto
from pyfect.deferred import Deferred
from pyfect.duration import Duration
from pyfect.effect import (
    AsyncioRequiredError,
    Gen,
    blocking,
    callback,
    catch_all,
    catch_if,
    catch_no_such_element,
    catch_reason,
    catch_reasons,
    catch_tag,
    current_fiber,
    die,
    fail,
    fail_cause,
    fail_cause_sync,
    fail_sync,
    fiber_id,
    fn,
    fn_untraced,
    from_async,
    from_exit,
    from_option,
    from_optional,
    from_result,
    gen,
    interrupt,
    never,
    provide_context,
    provide_service,
    provide_service_effect,
    service_option,
    set_context,
    succeed,
    succeed_none,
    succeed_some,
    suspend,
    sync,
    transpose_option,
    try_,
    try_async,
    try_blocking,
    unwrap_reason,
    update_context,
    update_service_scoped,
    void,
    with_fiber,
    with_fiber_succeed,
    yield_now,
)
from pyfect.error_reporter import ErrorReporter
from pyfect.errors import (
    Done,
    ExceededCapacityError,
    IllegalArgumentError,
    NoSuchElementException,
    TaggedError,
    TimeoutException,
    UnknownError,
)
from pyfect.execution_plan import ExecutionPlan, with_execution_plan
from pyfect.exit import Exit, Failure, Success
from pyfect.fiber_handle import FiberHandle
from pyfect.fiber_map import FiberMap
from pyfect.fiber_set import FiberSet
from pyfect.file_system import FileSystem
from pyfect.latch import Latch
from pyfect.layer import Layer, provide
from pyfect.layer_map import LayerMap, LayerMapService
from pyfect.layer_ref import LayerRef, LayerRefService
from pyfect.logger import (
    CurrentLogAnnotations,
    CurrentLoggers,
    CurrentLogLevel,
    CurrentLogSpans,
    Logger,
    LogLevel,
    LogToStderr,
    MinimumLogLevel,
    UnhandledLogLevel,
    annotate_logs_scoped,
    log,
    log_debug,
    log_error,
    log_fatal,
    log_info,
    log_trace,
    log_warning,
    log_with_level,
)
from pyfect.managed_runtime import ManagedRuntime
from pyfect.metric import Metric
from pyfect.option import Option, Some
from pyfect.partitioned_semaphore import PartitionedSemaphore
from pyfect.path import Path
from pyfect.platform_error import PlatformError
from pyfect.pool import Pool
from pyfect.pubsub import PubSub
from pyfect.pull import Pull
from pyfect.queue import Dequeue, Enqueue, Queue
from pyfect.random import Random
from pyfect.rc_map import RcMap
from pyfect.rc_ref import RcRef
from pyfect.redacted import Redacted
from pyfect.ref import Ref
from pyfect.resource import Resource
from pyfect.result import Err, Ok, Result
from pyfect.run import (
    Interruptor,
    Teardown,
    default_teardown,
    run_async,
    run_async_exit,
    run_callback,
    run_fork,
    run_main,
    run_sync,
    run_sync_exit,
)
from pyfect.schedule import Schedule
from pyfect.scheduler import CurrentScheduler, MaxOpsBeforeYield, PreventSchedulerYield
from pyfect.scope import (
    CloseableScope,
    Scope,
    acquire_release,
    acquire_use_release,
    add_finalizer,
    scoped,
    scoped_with,
)
from pyfect.scoped_ref import ScopedRef
from pyfect.semaphore import Semaphore
from pyfect.sink import Sink
from pyfect.stdio import Stdio
from pyfect.stream import Stream
from pyfect.subscription_ref import SubscriptionRef
from pyfect.synchronized_ref import SynchronizedRef
from pyfect.take import Take
from pyfect.terminal import Terminal
from pyfect.tracer import (
    annotate_current_span,
    current_parent_span,
    current_span,
    make_span,
    make_span_scoped,
    use_span,
)
from pyfect.transaction import Transaction, tx, tx_retry
from pyfect.tx_chunk import TxChunk
from pyfect.tx_deferred import TxDeferred
from pyfect.tx_hash_map import TxHashMap
from pyfect.tx_hash_set import TxHashSet
from pyfect.tx_priority_queue import TxPriorityQueue
from pyfect.tx_pubsub import TxPubSub
from pyfect.tx_queue import TxDequeue, TxEnqueue, TxQueue
from pyfect.tx_reentrant_lock import TxReentrantLock
from pyfect.tx_ref import TxRef
from pyfect.tx_semaphore import TxSemaphore
from pyfect.tx_subscription_ref import TxSubscriptionRef

_SUBMODULES = frozenset(
    (
        "ai",
        "batching",
        "big_decimal",
        "brand",
        "byte_size",
        "case",
        "cause",
        "channel",
        "channel_schema",
        "cli",
        "clock",
        "config",
        "config_provider",
        "console",
        "cron",
        "crypto",
        "date_time",
        "devtools",
        "duration",
        "effectable",
        "encoding",
        "error_reporter",
        "execution_plan",
        "exit",
        "file_system",
        "filters",
        "graph",
        "graphql",
        "hash_map",
        "hash_set",
        "http",
        "json_patch",
        "json_pointer",
        "json_schema",
        "layer",
        "logger",
        "metric",
        "mutable_hash_map",
        "mutable_hash_set",
        "optic",
        "option",
        "path",
        "persistence",
        "platform",
        "platform_error",
        "process",
        "pull",
        "random",
        "reactivity",
        "redacted",
        "result",
        "schedule",
        "scheduler",
        "schema",
        "scope",
        "semver",
        "semver_range",
        "sink",
        "sql",
        "stdio",
        "stream",
        "take",
        "terminal",
        "testing",
        "tracer",
        "transaction",
        "trie",
        "workers",
        "workflow",
    )
)
"""The subpackages ``fx.<name>`` reaches, imported when first used so that
``import pyfect`` (and the pytest plugin) stays fast."""

if _typing.TYPE_CHECKING:
    from pyfect import (
        ai,
        batching,
        big_decimal,
        brand,
        byte_size,
        case,
        cause,
        channel,
        channel_schema,
        cli,
        clock,
        config,
        config_provider,
        console,
        cron,
        crypto,
        date_time,
        devtools,
        duration,
        effectable,
        encoding,
        error_reporter,
        execution_plan,
        exit,
        file_system,
        filters,
        graph,
        graphql,
        hash_map,
        hash_set,
        http,
        json_patch,
        json_pointer,
        json_schema,
        layer,
        logger,
        metric,
        mutable_hash_map,
        mutable_hash_set,
        optic,
        option,
        path,
        persistence,
        platform,
        platform_error,
        process,
        pull,
        random,
        reactivity,
        redacted,
        result,
        schedule,
        scheduler,
        schema,
        scope,
        semver,
        semver_range,
        sink,
        sql,
        stdio,
        stream,
        take,
        terminal,
        testing,
        tracer,
        transaction,
        trie,
        workers,
        workflow,
    )


if not _typing.TYPE_CHECKING:  # pyright would accept any ``fx.<name>`` through it

    def __getattr__(name: str) -> _ModuleType:
        if name in _SUBMODULES:
            return _importlib.import_module(f"pyfect.{name}")
        raise AttributeError(f"module 'pyfect' has no attribute {name!r}")


if _typing.TYPE_CHECKING:
    from pyfect._context_effects import context
else:
    # ``pyfect.context`` is both the module and the effect ``fx.context(...)``
    # (Effect's ``Context`` and ``Effect.context``): the module is made
    # callable, so neither shadows the other (tests/test_package_namespace.py).
    from pyfect._context_effects import context as _context_effect

    class _ContextModule(_ModuleType):
        def __call__(self, *tags: _typing.Any) -> _typing.Any:
            return _context_effect(*tags)

    context.__class__ = _ContextModule

__all__ = [
    "AsyncioRequiredError",
    "Cache",
    "Cause",
    "Channel",
    "Clock",
    "CloseableScope",
    "Concurrency",
    "Config",
    "ConfigError",
    "ConfigProvider",
    "Context",
    "Crypto",
    "CurrentConfigProvider",
    "CurrentLogAnnotations",
    "CurrentLogLevel",
    "CurrentLogSpans",
    "CurrentLoggers",
    "CurrentScheduler",
    "Deferred",
    "Dequeue",
    "Done",
    "Duration",
    "Effect",
    "EmptyCauseError",
    "Enqueue",
    "Err",
    "ErrorReporter",
    "ExceededCapacityError",
    "ExecutionPlan",
    "Exit",
    "Failure",
    "Fiber",
    "FiberHandle",
    "FiberMap",
    "FiberSet",
    "FileSystem",
    "Gen",
    "HasReason",
    "IllegalArgumentError",
    "Interrupted",
    "Interruptor",
    "Latch",
    "Layer",
    "LayerMap",
    "LayerMapService",
    "LayerRef",
    "LayerRefService",
    "LogLevel",
    "LogToStderr",
    "Logger",
    "ManagedRuntime",
    "MaxOpsBeforeYield",
    "Metric",
    "MinimumLogLevel",
    "MissingServiceError",
    "NoRunError",
    "NoSuchElementException",
    "Ok",
    "Option",
    "PartitionedSemaphore",
    "Path",
    "PlatformError",
    "Pool",
    "PreventSchedulerYield",
    "PubSub",
    "Pull",
    "Queue",
    "Random",
    "RcMap",
    "RcRef",
    "Redacted",
    "Ref",
    "Reference",
    "Request",
    "RequestResolver",
    "Resource",
    "Restore",
    "Result",
    "Schedule",
    "Scope",
    "ScopedCache",
    "ScopedRef",
    "Semaphore",
    "Sink",
    "Some",
    "Stdio",
    "Stream",
    "SubscriptionRef",
    "Success",
    "SynchronizedRef",
    "Tag",
    "TaggedError",
    "Take",
    "Teardown",
    "Terminal",
    "TimeoutException",
    "Transaction",
    "TxChunk",
    "TxDeferred",
    "TxDequeue",
    "TxEnqueue",
    "TxHashMap",
    "TxHashSet",
    "TxPriorityQueue",
    "TxPubSub",
    "TxQueue",
    "TxReentrantLock",
    "TxRef",
    "TxSemaphore",
    "TxSubscriptionRef",
    "UnhandledError",
    "UnhandledLogLevel",
    "UnknownError",
    "acquire_async_context",
    "acquire_context",
    "acquire_release",
    "acquire_use_release",
    "add_finalizer",
    "ai",
    "all",
    "all_dict",
    "annotate_current_span",
    "annotate_logs_scoped",
    "batching",
    "big_decimal",
    "blocking",
    "brand",
    "byte_size",
    "callback",
    "case",
    "catch_all",
    "catch_if",
    "catch_no_such_element",
    "catch_reason",
    "catch_reasons",
    "catch_tag",
    "cause",
    "channel",
    "channel_schema",
    "cli",
    "clock",
    "config",
    "config_provider",
    "console",
    "context",
    "cron",
    "crypto",
    "current_fiber",
    "current_parent_span",
    "current_span",
    "date_time",
    "default_teardown",
    "devtools",
    "die",
    "duration",
    "effectable",
    "encoding",
    "error_reporter",
    "execution_plan",
    "exit",
    "fail",
    "fail_cause",
    "fail_cause_sync",
    "fail_sync",
    "fiber_id",
    "file_system",
    "filter",
    "filter_map",
    "filter_map_effect",
    "filters",
    "find_first",
    "find_first_filter",
    "first_success_of",
    "fn",
    "fn_untraced",
    "for_each",
    "from_async",
    "from_exit",
    "from_option",
    "from_optional",
    "from_result",
    "gen",
    "graph",
    "graphql",
    "hash_map",
    "hash_set",
    "http",
    "interrupt",
    "interruptible_mask",
    "json_patch",
    "json_pointer",
    "json_schema",
    "layer",
    "log",
    "log_debug",
    "log_error",
    "log_fatal",
    "log_info",
    "log_trace",
    "log_warning",
    "log_with_level",
    "logger",
    "make_span",
    "make_span_scoped",
    "metric",
    "mutable_hash_map",
    "mutable_hash_set",
    "never",
    "optic",
    "option",
    "partition",
    "path",
    "persistence",
    "platform",
    "platform_error",
    "process",
    "provide",
    "provide_context",
    "provide_service",
    "provide_service_effect",
    "pull",
    "race_all",
    "race_all_first",
    "random",
    "reactivity",
    "redacted",
    "reduce",
    "request",
    "request_unsafe",
    "result",
    "run_async",
    "run_async_exit",
    "run_callback",
    "run_fork",
    "run_main",
    "run_sync",
    "run_sync_exit",
    "schedule",
    "scheduler",
    "schema",
    "scope",
    "scoped",
    "scoped_with",
    "semver",
    "semver_range",
    "service_option",
    "set_context",
    "sink",
    "sleep",
    "sql",
    "stdio",
    "stream",
    "succeed",
    "succeed_none",
    "succeed_some",
    "suspend",
    "sync",
    "take",
    "terminal",
    "testing",
    "tracer",
    "transaction",
    "transpose_option",
    "trie",
    "try_",
    "try_async",
    "try_blocking",
    "tx",
    "tx_retry",
    "uninterruptible_mask",
    "unwrap_reason",
    "update_context",
    "update_service_scoped",
    "use_span",
    "validate",
    "void",
    "with_execution_plan",
    "with_fiber",
    "with_fiber_succeed",
    "workers",
    "workflow",
    "yield_now",
]

publish(globals())
