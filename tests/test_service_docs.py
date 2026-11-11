"""``help()`` and the API reference show every operation of every public
service, with its signature and docstring.

A service whose operations were dataclass fields holding functions (or
effects) showed none of them: ``help(MacService)`` listed no ``sign`` and
``inspect.signature`` had nothing to read (FINDINGS-vault 10). Every class
named ``*Service`` that a public module exports keeps its operations as
documented methods or properties; a field (or annotated attribute) whose
type is a function, an ``Effect`` or a ``Stream`` is refused here, except on
the services in ``WAITING_FOR_0_6``: turning their fields into methods ends
``dataclasses.replace``, field equality and frozenness, so it waits for
0.6.0. The list may only shrink.
"""

from __future__ import annotations

import builtins
import inspect
import sys
import types
import typing
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from _pyfect_modules import modules

from pyfect.effect import Effect
from pyfect.stream import Stream

_OPERATION_TYPES: tuple[type, ...] = (Effect, Stream)


def _services() -> dict[str, type]:
    found: dict[str, type] = {}
    for module in modules(public=True, skip_missing_extras=True):
        names = getattr(module, "__all__", None)
        if names is None:
            names = [name for name in vars(module) if not name.startswith("_")]
        for name in names:
            value = getattr(module, name, None)
            if (
                isinstance(value, type)
                and value.__name__.endswith("Service")
                and value.__module__.startswith("pyfect")
            ):
                found.setdefault(f"{value.__module__}.{value.__qualname__}", value)
    return dict(sorted(found.items()))


SERVICES = _services()


def _alias_value(alias: typing.TypeAliasType) -> object:
    """What ``alias`` stands for; a name it uses that exists only under
    ``TYPE_CHECKING`` stays a forward reference on 3.14 (on 3.13 the alias
    counts as no operation)."""
    if sys.version_info >= (3, 14):
        annotationlib: Any = __import__("annotationlib")
        return annotationlib.call_evaluate_function(
            alias.evaluate_value,  # pyright: ignore[reportAttributeAccessIssue]
            annotationlib.Format.FORWARDREF,
        )
    try:
        return alias.__value__
    except NameError:
        return None


def _resolve(hint: object) -> object:
    while isinstance(hint, typing.TypeAliasType):
        hint = _alias_value(hint)
    return hint


def _is_operation(hint: object) -> bool:
    """Whether ``hint`` is the type of a function, an effect or a stream
    (alone, or in a union with ``None``)."""
    hint = _resolve(hint)
    origin = _resolve(typing.get_origin(hint))
    if origin is typing.Union or origin is types.UnionType:
        return any(_is_operation(arg) for arg in typing.get_args(hint))
    target = origin if origin is not None else hint
    if target is Callable:
        return True
    if not isinstance(target, type):
        return False
    if issubclass(target, _OPERATION_TYPES):
        return True
    return bool(getattr(target, "_is_protocol", False)) and "__call__" in vars(target)


class _Unresolved:
    """A name an annotation uses that exists only under ``TYPE_CHECKING``."""


class _Names(dict[str, object]):
    """The names a class's annotation strings see: its module's globals and
    builtins; any other name becomes a class of its own, so the rest of the
    annotation still evaluates."""

    def __init__(self, klass: type) -> None:
        super().__init__({t.__name__: t for t in getattr(klass, "__type_params__", ())})
        self.globals: dict[str, Any] = vars(sys.modules[klass.__module__])

    def __missing__(self, name: str) -> object:
        if name in self.globals:
            return self.globals[name]
        if hasattr(builtins, name):
            return getattr(builtins, name)
        return type(name, (_Unresolved,), {})


def _annotations(klass: type) -> dict[str, object]:
    if sys.version_info >= (3, 14):
        annotationlib: Any = __import__("annotationlib")
        return annotationlib.get_annotations(klass, format=annotationlib.Format.STRING)
    return inspect.get_annotations(klass)


def _attributes(service: type) -> Iterator[tuple[str, object]]:
    """Each public annotated attribute (dataclass fields included) of
    ``service`` and the classes it inherits from."""
    for klass in service.__mro__:
        if klass.__module__ in ("builtins", "typing", "abc"):
            continue
        for name, written in _annotations(klass).items():
            hint = eval(written, {}, _Names(klass)) if isinstance(written, str) else written
            if not name.startswith("_") and typing.get_origin(hint) is not typing.ClassVar:
                yield name, hint


def _operations(service: type) -> list[str]:
    """Each public method or property ``help(service)`` lists from pyfect."""
    names: list[str] = []
    for name in dir(service):
        if name.startswith("_"):
            continue
        member: object = inspect.getattr_static(service, name)
        if isinstance(member, (staticmethod, classmethod)):
            member = typing.cast("staticmethod[..., object]", member).__func__
        function = member.fget if isinstance(member, property) else member
        if inspect.isfunction(function) and function.__module__.startswith("pyfect"):
            names.append(name)
    return names


def test_services_are_found() -> None:
    assert "pyfect.crypto.mac.MacService" in SERVICES
    assert len(SERVICES) > 50


WAITING_FOR_0_6 = frozenset(
    {
        "pyfect.ai._mcp.client_transport.TransportService",
        "pyfect.ai.anthropic.client.Service",
        "pyfect.ai.cloudflare.client.Service",
        "pyfect.ai.id_generator.Service",
        "pyfect.ai.language_model.Service",
        "pyfect.ai.openai._web_socket.SocketService",
        "pyfect.ai.openai.client.Service",
        "pyfect.ai.openai_compat.client.Service",
        "pyfect.ai.openrouter.client.Service",
        "pyfect.ai.typesafe.client.Service",
        "pyfect.cluster.runner_health.RunnerHealthService",
        "pyfect.cluster.runner_storage.RunnerStorageService",
        "pyfect.cluster.runners._service.RpcClientProtocolService",
        "pyfect.eventlog.event_log_remote.EventLogRemoteService",
        "pyfect.graphql._types.GraphQLProtocolService",
        "pyfect.http.platform.HttpPlatformService",
        "pyfect.http.server.HttpServerService",
        "pyfect.observability.otlp_exporter.FlusherService",
        "pyfect.observability.otlp_serialization.OtlpSerializationService",
        "pyfect.persistence.circuit_breaker._store.CircuitBreakerStoreService",
        "pyfect.persistence.key_value_store._store.KeyValueStoreService",
        "pyfect.persistence.persisted_queue._store.PersistedQueueStoreService",
        "pyfect.persistence.persistence._service.BackingPersistenceService",
        "pyfect.persistence.user_directories.UserDirectoriesService",
        "pyfect.process._spawner.ChildProcessSpawnerService",
        "pyfect.rpc.client._protocol.ClientProtocolService",
        "pyfect.rpc.client._transports.ConnectionHooksService",
        "pyfect.rpc.serialization.RpcSerializationService",
        "pyfect.rpc.server._protocol.ServerProtocolService",
        "pyfect.socket._socket.SocketService",
        "pyfect.socket.datagram._model.DatagramSocketService",
        "pyfect.sql.clickhouse.client.ClickhouseClientService",
        "pyfect.sql.client._client.SqlClientService",
        "pyfect.sql.d1.client.D1ClientService",
        "pyfect.sql.libsql.client.LibsqlClientService",
        "pyfect.sql.mssql.client.MssqlClientService",
        "pyfect.sql.mysql.client.MysqlClientService",
        "pyfect.sql.pg.client.PgClientService",
        "pyfect.sql.sqlite.client.SqliteClientService",
        "pyfect.stdio.StdioService",
        "pyfect.terminal._service.TerminalService",
        "pyfect.workers.worker.WorkerPlatformService",
        "pyfect.workers.worker_runner.WorkerRunnerPlatformService",
        "pyfect.workflow._services.WorkflowEngineService",
    }
)
"""Services that still hold operations in fields; each becomes a class with
documented methods in 0.6.0 (a behaviour change under docs/VERSIONING.md)."""


def _operation_fields(service: type) -> list[str]:
    return [name for name, hint in _attributes(service) if _is_operation(hint)]


@pytest.mark.parametrize("service", SERVICES.values(), ids=list(SERVICES))
def test_no_operation_is_a_bare_field(service: type) -> None:
    name = f"{service.__module__}.{service.__qualname__}"
    if name in WAITING_FOR_0_6:
        assert _operation_fields(service), f"{name} is converted: drop it from WAITING_FOR_0_6"
    else:
        assert _operation_fields(service) == [], "operations held in fields"


def test_every_waiting_service_still_exists() -> None:
    assert sorted(WAITING_FOR_0_6 - SERVICES.keys()) == []


@pytest.mark.parametrize("service", SERVICES.values(), ids=list(SERVICES))
def test_every_operation_is_documented(service: type) -> None:
    undocumented = [
        name for name in _operations(service) if not inspect.getdoc(getattr(service, name))
    ]
    assert undocumented == []


def test_a_function_field_is_caught() -> None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class FakeService:
        op: Callable[[int], Effect[int]]
        value: Effect[int] | None
        label: str

    assert [name for name, hint in _attributes(FakeService) if _is_operation(hint)] == [
        "op",
        "value",
    ]
