"""Reuse cases for ``pyfect.ai`` and ``pyfect.otel``.

Providers run ``generate_text``/``embed`` against a fake ``HttpClient``; the
MCP layers do a client/server round trip in memory (HTTP through the router,
stdio through a fake child process wired to an in-process server); the
OpenTelemetry layers export a span or a log record to a recording processor.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any, TypedDict, cast

from opentelemetry import trace
from opentelemetry.sdk import _logs as sdk_logs
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from oracle import _ai_http, _mcp

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import config, config_provider, metric, otel, sink, stdio, stream
from pyfect import layer as L
from pyfect import schema as S
from pyfect.ai import chat as Chat
from pyfect.ai import embedding_model as em
from pyfect.ai import id_generator
from pyfect.ai import language_model as lm
from pyfect.ai import mcp_client as C
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.anthropic import client as anthropic_client
from pyfect.ai.anthropic import language_model as anthropic_lm
from pyfect.ai.openai_compat import client as openai_client
from pyfect.ai.openai_compat import embedding_model as openai_em
from pyfect.ai.openai_compat import language_model as openai_lm
from pyfect.deferred import Deferred
from pyfect.errors import Done
from pyfect.http.client import HttpClient
from pyfect.http.client import layer_test as http_layer_test
from pyfect.http.request import HttpClientRequest
from pyfect.otel.logger import OtelLoggerProvider
from pyfect.otel.resource import OtelResource
from pyfect.otel.tracer import OtelSpan, OtelTracer, OtelTracerProvider
from pyfect.persistence import persistence
from pyfect.process import ChildProcessHandle, ChildProcessSpawner, ChildProcessSpawnerService
from pyfect.process import make as make_command
from pyfect.queue import Queue
from pyfect.redacted import make as redact
from pyfect.tracer import current_span

_runs = itertools.count(1)


def _check(condition: bool, what: str) -> AnyEffect:
    return fx.void if condition else fx.die(AssertionError(what))


# --- providers over a fake HttpClient ----------------------------------------------------


def _http(body: Callable[[HttpClientRequest], object]) -> AnyLayer:
    return http_layer_test(
        lambda request: fx.succeed(_ai_http.json_response(request, body(request)))
    )


def _anthropic_http() -> AnyLayer:
    return _http(
        lambda _: {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-test",
            "content": [{"type": "text", "text": "Hello from Claude"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


def _openai_http() -> AnyLayer:
    def body(request: HttpClientRequest) -> object:
        if request.url.endswith("/embeddings"):
            return {
                "data": [{"index": 0, "embedding": [1, 2]}],
                "model": "embed-test",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
        return {
            "id": "chatcmpl_1",
            "object": "chat.completion",
            "model": "gpt-test",
            "created": 1,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Hello from OpenAI"},
                }
            ],
        }

    return _http(body)


def _generates(text: str) -> AnyEffect:
    return lm.generate_text("Hello").flat_map(
        lambda response: _check(response.text == text, f"generated {response.text!r}")
    )


def _embeds() -> AnyEffect:
    return (
        em.EmbeddingModel()
        .flat_map(lambda model: model.embed("hello"))
        .flat_map(lambda response: _check(tuple(response.vector) == (1, 2), "embedding"))
    )


def _api_keys() -> AnyLayer:
    return config_provider.layer(
        config_provider.from_unknown({"ANTHROPIC_API_KEY": "sk-a", "OPENAI_API_KEY": "sk-o"})
    )


_ANTHROPIC_MODEL = "claude-test"


def _anthropic_model() -> AnyLayer:
    return anthropic_lm.layer(model=_ANTHROPIC_MODEL)


def _openai_model() -> AnyLayer:
    return openai_lm.layer(model="gpt-test")


def _anthropic_client() -> AnyLayer:
    return anthropic_client.layer(api_key=redact("sk-test")).pipe(
        L.provide_merge(_anthropic_http())
    )


def _openai_client() -> AnyLayer:
    return openai_client.layer(api_key=redact("sk-test")).pipe(L.provide_merge(_openai_http()))


_PROVIDER_CASES: dict[str, Case] = {
    "pyfect.ai.anthropic.client.layer": Case(
        layer=lambda: anthropic_client.layer(api_key=redact("sk-test")),
        needs=_anthropic_http,
        use=lambda: _generates("Hello from Claude").pipe(fx.provide(_anthropic_model())),
    ),
    "pyfect.ai.anthropic.client.layer_config": Case(
        layer=lambda: anthropic_client.layer_config(api_key=config.redacted("ANTHROPIC_API_KEY")),
        needs=lambda: L.merge(_anthropic_http(), _api_keys()),
        use=lambda: _generates("Hello from Claude").pipe(fx.provide(_anthropic_model())),
    ),
    "pyfect.ai.anthropic.language_model.layer": Case(
        layer=_anthropic_model,
        needs=_anthropic_client,
        use=lambda: _generates("Hello from Claude"),
    ),
    "pyfect.ai.openai_compat.client.layer": Case(
        layer=lambda: openai_client.layer(api_key=redact("sk-test")),
        needs=_openai_http,
        use=lambda: _generates("Hello from OpenAI").pipe(fx.provide(_openai_model())),
    ),
    "pyfect.ai.openai_compat.client.layer_config": Case(
        layer=lambda: openai_client.layer_config(api_key=config.redacted("OPENAI_API_KEY")),
        needs=lambda: L.merge(_openai_http(), _api_keys()),
        use=lambda: _generates("Hello from OpenAI").pipe(fx.provide(_openai_model())),
    ),
    "pyfect.ai.openai_compat.language_model.layer": Case(
        layer=_openai_model,
        needs=_openai_client,
        use=lambda: _generates("Hello from OpenAI"),
    ),
    "pyfect.ai.openai_compat.embedding_model.layer": Case(
        layer=lambda: openai_em.layer(model="embed-test"),
        needs=_openai_client,
        use=_embeds,
    ),
}


# --- ids, toolkits, chats ----------------------------------------------------------------


class AddParams(TypedDict):
    a: float
    b: float


class Total(TypedDict):
    total: float


Add = T.make("add", parameters=S.Struct(AddParams), success=S.Struct(Total))
_TOOLS = K.make(Add)


def _handlers() -> AnyLayer:
    return _TOOLS.to_layer(Add.handler(lambda p, _: fx.succeed(Total(total=p["a"] + p["b"]))))


def _handles_add() -> AnyEffect:
    return (
        _TOOLS.flat_map(lambda kit: kit.handle("add", {"a": 2, "b": 3}))
        .flat_map(lambda results: results.run_last())
        .flat_map(
            lambda last: _check(
                last is not None and last.value.result == {"total": 5}, f"toolkit result {last}"
            )
        )
    )


def _fake_model() -> AnyLayer:
    return L.effect(
        lm.LanguageModel,
        lm.make(
            generate_text=lambda _: fx.succeed([{"type": "text", "text": "hi there"}]),
            stream_text=lambda _: stream.empty,
        ),
    )


def _chats() -> AnyEffect:
    @fx.gen
    def run():
        chats = yield from Chat.Persistence()
        chat = yield from chats.get_or_create("1")
        yield from chat.generate_text("hello")
        history = yield from chat.history.get()
        yield from _check(len(history.content) == 2, f"history {history}")
        reopened = yield from chats.get_or_create("1")
        again = yield from reopened.history.get()
        yield from _check(again == history, "reopened history")

    return run


def _generates_id() -> AnyEffect:
    return (
        id_generator.IdGenerator()
        .flat_map(lambda ids: ids.generate_id())
        .flat_map(lambda made: _check(made.startswith("call-") and len(made) == 9, made))
    )


_AI_CASES: dict[str, Case] = {
    "pyfect.ai.id_generator.layer": Case(
        layer=lambda: id_generator.layer(prefix="call", separator="-", size=4),
        use=_generates_id,
    ),
    "pyfect.ai.toolkit.Toolkit.to_layer": Case(layer=_handlers, use=_handles_add),
    "pyfect.ai.chat.layer_persisted": Case(
        layer=lambda: Chat.layer_persisted(store_id="chat"),
        needs=lambda: L.merge(persistence.layer_backing_memory, _fake_model()),
        use=_chats,
    ),
}


# --- MCP ---------------------------------------------------------------------------------

_PROTOCOL = P.v2025_11_25


def _http_server() -> AnyLayer:
    return M.layer_http(name="test-server", version="1.0.0", path="/mcp", protocols=(_PROTOCOL,))


def _stdio_server() -> AnyLayer:
    return M.layer_stdio(name="test-server", version="1.0.0", protocols=(_PROTOCOL,))


def _http_client() -> AnyLayer:
    return C.layer_http(
        name="test-client", version="1.0.0", url=_mcp.MCP_ENDPOINT, protocol=_PROTOCOL
    )


def _stdio_client() -> AnyLayer:
    return C.layer_stdio(
        name="test-client",
        version="1.0.0",
        command=make_command("test-mcp-server"),
        protocol=_PROTOCOL,
    )


def _in_memory_http(app: AnyLayer) -> AnyLayer:
    """An ``HttpClient`` whose requests ``app`` (routes) answers."""
    return L.effect(HttpClient, _mcp.in_memory_http(app))


def _connected_process(server: AnyLayer) -> AnyLayer:
    """A ``ChildProcessSpawner`` whose process is ``server`` (a layer
    serving MCP on ``Stdio``), run in this process."""

    @fx.gen
    def run():
        to_server = Queue[bytes, Done]()
        to_client = Queue[bytes, Done]()
        exit_code = Deferred[int]()

        def output(*, end_on_done: bool = False) -> stdio.Output:
            def write(chunk: str | bytes) -> fx.Effect[None]:
                data = chunk.encode() if isinstance(chunk, str) else chunk
                return to_client.offer(data).as_void()

            return cast("stdio.Output", sink.for_each(write))

        stdio_layer = stdio.layer_test(stdin=stream.from_queue(to_server), stdout=output)
        yield from server.pipe(L.provide(stdio_layer)).build()

        def kill(**_options: object) -> fx.Effect[None]:
            return exit_code.succeed(0).as_void()

        handle = ChildProcessHandle(
            pid=cast("Any", 1),
            exit_code=cast("Any", exit_code.wait()),
            is_running=fx.succeed(True),
            kill=kill,
            stdin=cast(
                "Any",
                sink.for_each(to_server.offer).pipe(lambda s: s.ensuring(exit_code.succeed(0))),
            ),
            stdout=stream.from_queue(to_client),
            stderr=stream.empty,
            all=stream.empty,
            get_input_fd=lambda _: cast("Any", sink.drain),
            get_output_fd=lambda _: stream.empty,
            unref=cast("Any", fx.succeed(fx.succeed(None))),
        )
        return ChildProcessSpawnerService(lambda _: fx.succeed(handle))

    return L.effect(ChildProcessSpawner, run)


def _calls_add() -> AnyEffect:
    """Through the ``McpClient``: list the tools and call ``add``."""

    @fx.gen
    def run():
        client = yield from C.McpClient()
        tools = {tool["name"]: tool for tool in (yield from client.list_tools())}
        total = yield from client.call_tool(tools["add"], {"a": 2, "b": 3}, schema=S.Struct(Total))
        yield from _check(total == {"total": 5}, f"add gave {total}")

    return run


def _tool_app(server: AnyLayer) -> AnyLayer:
    return L.merge(server, M.toolkit(_TOOLS)).pipe(L.provide(_handlers()))


def _over_http(app: AnyLayer, use: Callable[[], AnyEffect]) -> AnyEffect:
    """``use`` with an ``McpClient`` of ``app`` over in-memory HTTP."""
    return use().pipe(fx.provide(_http_client().pipe(L.provide(_in_memory_http(app)))))


def _resource_text(uri: str, text: str) -> AnyEffect:
    @fx.gen
    def run():
        client = yield from C.McpClient()
        result = yield from client.read_resource(uri)
        yield from _check(result["contents"] == [{"uri": uri, "text": text}], f"read {result}")

    return run


def _prompt_text() -> AnyEffect:
    @fx.gen
    def run():
        client = yield from C.McpClient()
        [prompt] = yield from client.list_prompts()
        result = yield from client.get_prompt(prompt)
        [message] = result["messages"]
        yield from _check(message["content"] == {"type": "text", "text": "Explain"}, f"{result}")

    return run


def _own_server_only(value: AnyLayer) -> AnyEffect:
    """A run registers a resource of its own on the ``McpServer``; the
    server lists only that one."""
    uri = f"demo://run{next(_runs)}"

    @fx.gen
    def listed():
        client = yield from C.McpClient()
        resources = yield from client.list_resources()
        yield from _check([r["uri"] for r in resources] == [uri], f"resources {resources}")

    app = L.merge(_http_server(), M.resource(uri=uri, name="r", content=fx.succeed("r")))
    return _over_http(app.pipe(L.provide_merge(value)), lambda: listed)


_GUIDE = "demo://guide"

_MCP_CASES: dict[str, Case] = {
    "pyfect.ai.mcp_server.layer": Case(layer=lambda: M.layer, run=_own_server_only),
    "pyfect.ai.mcp_server.layer_http": Case(
        layer=_http_server, run=lambda value: _over_http(_tool_app(value), _calls_add)
    ),
    "pyfect.ai.mcp_server.layer_stdio": Case(
        layer=_stdio_server,
        run=lambda value: _calls_add().pipe(
            fx.provide(_stdio_client().pipe(L.provide(_connected_process(_tool_app(value)))))
        ),
    ),
    "pyfect.ai.mcp_server.toolkit": Case(
        layer=lambda: M.toolkit(_TOOLS),
        run=lambda value: _over_http(
            L.merge(_http_server(), value).pipe(L.provide(_handlers())), _calls_add
        ),
    ),
    "pyfect.ai.mcp_server.resource": Case(
        layer=lambda: M.resource(uri=_GUIDE, name="guide", content=fx.succeed("Guide")),
        run=lambda value: _over_http(
            L.merge(_http_server(), value), lambda: _resource_text(_GUIDE, "Guide")
        ),
    ),
    "pyfect.ai.mcp_server.resource_template": Case(
        layer=lambda: M.resource_template(
            M.uri_template("demo://docs/", S.String),
            name="doc",
            content=lambda _uri, name: fx.succeed(f"doc {name}"),
        ),
        run=lambda value: _over_http(
            L.merge(_http_server(), value), lambda: _resource_text("demo://docs/a", "doc a")
        ),
    ),
    "pyfect.ai.mcp_server.prompt": Case(
        layer=lambda: M.prompt(name="explain", content=lambda _: fx.succeed("Explain")),
        run=lambda value: _over_http(L.merge(_http_server(), value), _prompt_text),
    ),
    "pyfect.ai.mcp_client.layer_http": Case(
        layer=_http_client,
        needs=lambda: _in_memory_http(_tool_app(_http_server())),
        use=_calls_add,
    ),
    "pyfect.ai.mcp_client.layer_stdio": Case(
        layer=_stdio_client,
        needs=lambda: _connected_process(_tool_app(_stdio_server())),
        use=_calls_add,
    ),
}


# --- OpenTelemetry -----------------------------------------------------------------------


class _Spans(SpanProcessor):
    """Records each ended span. Shutting it down (each run's provider does,
    when released) leaves it recording, as a processor made per build
    would."""

    def __init__(self) -> None:
        self.ended: list[ReadableSpan] = []

    def on_end(self, span: ReadableSpan) -> None:
        self.ended.append(span)

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


class _Logs(sdk_logs.LogRecordProcessor):
    """Records each emitted log record's body and resource (see ``_Spans``)."""

    def __init__(self) -> None:
        self.emitted: list[tuple[object, dict[str, Any]]] = []

    def on_emit(self, log_record: Any) -> None:
        resource = log_record.resource
        self.emitted.append((log_record.log_record.body, dict(resource.attributes)))

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


_SPANS = _Spans()
_LOGS = _Logs()
_READERS: list[InMemoryMetricReader] = []


def _reader() -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    _READERS.append(reader)
    return reader


def _service() -> AnyLayer:
    return otel.resource.layer(service_name="svc")


def _tracer_provider() -> TracerProvider:
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(_SPANS)
    return provider


def _logger_provider() -> sdk_logs.LoggerProvider:
    provider = sdk_logs.LoggerProvider(shutdown_on_exit=False)
    provider.add_log_record_processor(_LOGS)
    return provider


def _sdk_tracer_provider() -> AnyLayer:
    return L.sync(OtelTracerProvider, _tracer_provider)


def _sdk_logger_provider() -> AnyLayer:
    return L.sync(OtelLoggerProvider, _logger_provider)


def _exports_span(service: str | None = None) -> AnyEffect:
    """A pyfect span ends up, exported, at ``_SPANS``."""
    name = f"span-{next(_runs)}"

    def exported() -> AnyEffect:
        if not _SPANS.ended:
            return _check(False, f"exported nothing for {name}")
        span = _SPANS.ended[-1]
        ok = span.name == name and (
            service is None or span.resource.attributes.get("service.name") == service
        )
        return _check(ok, f"exported {span} for {name}")

    return (
        current_span()
        .flat_map(lambda span: _check(isinstance(span, OtelSpan), f"{span} is an OtelSpan"))
        .with_span(name)
        .and_then(fx.suspend(exported))
    )


def _otel_tracer_exports() -> AnyEffect:
    """The ``OtelTracer`` starts spans the provider exports."""
    name = f"otel-{next(_runs)}"

    def start(tracer: trace.Tracer) -> AnyEffect:
        tracer.start_span(name).end()
        return _check(_SPANS.ended[-1].name == name, "exported the OTel span")

    return OtelTracer().flat_map(start)


def _bridged_span() -> AnyEffect:
    """With the global provider (no SDK installed here), spans are still
    the bridge's ``OtelSpan``s."""
    return (
        current_span()
        .flat_map(lambda span: _check(isinstance(span, OtelSpan), f"{span} is an OtelSpan"))
        .with_span(f"global-{next(_runs)}")
    )


def _logs_record(service: str | None = None) -> AnyEffect:
    message = f"log-{next(_runs)}"

    def emitted() -> AnyEffect:
        body, attributes = _LOGS.emitted[-1] if _LOGS.emitted else (None, {})
        ok = body == message and (service is None or attributes.get("service.name") == service)
        return _check(ok, f"emitted {body!r} {attributes} for {message}")

    return fx.log_info(message).and_then(fx.suspend(emitted))


def _counts(metric_name: str) -> AnyEffect:
    """Updating a counter shows in the collection of one of the newest
    readers (two runs may be at once)."""

    def collected() -> AnyEffect:
        names = [
            m.name
            for reader in _READERS[-2:]
            for data in [reader.get_metrics_data()]
            for rm in (data.resource_metrics if data is not None else [])
            for sm in rm.scope_metrics
            for m in sm.metrics
        ]
        return _check(metric_name in names, f"collected {names}")

    return metric.counter(metric_name).update(1).and_then(fx.suspend(collected))


def _resource_named(service: str | None) -> AnyEffect:
    return OtelResource().flat_map(
        lambda resource: _check(
            resource.attributes.get("service.name") == service, f"resource {resource.attributes}"
        )
    )


def _sdk_config() -> otel.sdk.Configuration:
    return otel.sdk.Configuration(
        resource=otel.sdk.ResourceConfig(service_name="sdk-svc"),
        span_processor=_SPANS,
        log_record_processor=_LOGS,
        metric_reader=_reader(),
    )


def _fresh_registry() -> AnyLayer:
    return L.sync(metric.MetricRegistry, dict)


def _sdk_use() -> AnyEffect:
    return (
        _exports_span("sdk-svc")
        .and_then(_logs_record("sdk-svc"))
        .and_then(_counts(f"sdk_counter_{next(_runs)}"))
    )


_OTEL_CASES: dict[str, Case] = {
    "pyfect.otel.resource.layer": Case(layer=_service, use=lambda: _resource_named("svc")),
    "pyfect.otel.resource.layer_empty": Case(
        layer=lambda: otel.resource.layer_empty,
        use=lambda: OtelResource().flat_map(
            lambda r: _check(dict(r.attributes) == {}, "empty resource")
        ),
    ),
    "pyfect.otel.resource.layer_from_env": Case(
        layer=lambda: otel.resource.layer_from_env({"extra": "x"}),
        needs=lambda: config_provider.layer(
            config_provider.from_unknown({"OTEL_SERVICE_NAME": "env-svc"})
        ),
        use=lambda: _resource_named("env-svc"),
    ),
    "pyfect.otel.sdk.layer": Case(
        layer=lambda: otel.sdk.layer(_sdk_config), needs=_fresh_registry, use=_sdk_use
    ),
    "pyfect.otel.sdk.layer_tracer_provider": Case(
        layer=lambda: otel.sdk.layer_tracer_provider(_SPANS),
        needs=_service,
        use=lambda: _exports_span("svc").pipe(fx.provide(otel.tracer.layer)),
    ),
    "pyfect.otel.logger.layer_logger_provider": Case(
        layer=lambda: otel.logger.layer_logger_provider(_LOGS),
        needs=_service,
        use=lambda: _logs_record("svc").pipe(fx.provide(otel.logger.layer())),
    ),
    "pyfect.otel.logger.layer": Case(
        layer=otel.logger.layer, needs=_sdk_logger_provider, use=_logs_record
    ),
    "pyfect.otel.metrics.layer": Case(
        layer=lambda: otel.metrics.layer(_reader),
        needs=lambda: L.merge(_service(), _fresh_registry()),
        use=lambda: _counts(f"counter_{next(_runs)}"),
    ),
    "pyfect.otel.tracer.layer": Case(
        layer=lambda: otel.tracer.layer, needs=_sdk_tracer_provider, use=_exports_span
    ),
    "pyfect.otel.tracer.layer_tracer": Case(
        layer=lambda: otel.tracer.layer_tracer,
        needs=_sdk_tracer_provider,
        use=_otel_tracer_exports,
    ),
    "pyfect.otel.tracer.layer_without_otel_tracer": Case(
        layer=lambda: otel.tracer.layer_without_otel_tracer,
        needs=lambda: otel.tracer.layer_tracer.pipe(L.provide(_sdk_tracer_provider())),
        use=_exports_span,
    ),
    "pyfect.otel.tracer.layer_global_provider": Case(
        layer=lambda: otel.tracer.layer_global_provider,
        use=lambda: OtelTracerProvider().flat_map(
            lambda p: _check(p is trace.get_tracer_provider(), "the global provider")
        ),
    ),
    "pyfect.otel.tracer.layer_global_tracer": Case(
        layer=lambda: otel.tracer.layer_global_tracer,
        use=lambda: _bridged_span().pipe(fx.provide(otel.tracer.layer_without_otel_tracer)),
    ),
    "pyfect.otel.tracer.layer_global": Case(
        layer=lambda: otel.tracer.layer_global, use=_bridged_span
    ),
}

CASES: dict[str, Case] = {**_PROVIDER_CASES, **_AI_CASES, **_MCP_CASES, **_OTEL_CASES}
SKIPPED: dict[str, str] = {}
