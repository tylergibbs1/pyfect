"""Ports of Effect's ``Logger.test.ts``.

Each test's docstring is the Effect test title. ``@testing.effect`` runs
each test with a ``TestConsole``, as ``it.effect`` does. Fiber ids are global in pyfect, so
``(#1)`` is matched as ``(#\\d+)``. ``String(options.message)`` of a
one-item message is the item, ``" ".join(...)`` here. Durations are
seconds.
"""

import json
import math
import re
from collections.abc import Mapping, Sequence

import pyfect as fx
from pyfect import logger, testing

_HEADER = re.compile(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\]\sINFO\s\(#\d+\)")
_DONE = fx.Success(None)


def _text(message: Sequence[object]) -> str:
    return " ".join(str(m) for m in message)


def _collecting(
    sink: list[dict[str, object]],
) -> fx.Logger[None]:
    """A logger recording the annotations each entry sees."""

    def record(options: logger.Options) -> None:
        sink.append(dict(options.fiber.get_ref(fx.CurrentLogAnnotations)))

    return fx.Logger.make(record)


@testing.effect
def test_should_output_logs():
    """should output logs"""
    yield from fx.log_info("info", "message").annotate_logs("key", "value").with_log_span("span")
    result = yield from testing.log_lines
    assert re.match(_HEADER.pattern + r"\sspan=\dms:", str(result[0]))
    assert result[1] == "info"
    assert result[2] == "message"
    assert result[3] == {"key": "value"}


@testing.effect
def test_replace_loggers():
    """replace loggers"""
    result: list[str] = []
    context = yield from logger.layer([logger.format_json.map(result.append)]).build()
    yield from fx.log_info("info", "message").pipe(fx.provide_context(context))
    assert len(result) == 1


@testing.effect
def test_format_log_fmt_does_not_double_quote_string_messages_or_annotations():
    """formatLogFmt does not double quote string messages or annotations"""
    result: list[str] = []
    yield from (
        fx.log_info("Welcome to the Effect Playground!")
        .annotate_logs({"annotation1": "first", "annotation2": "second", "annotation3": '"omg"'})
        .pipe(fx.provide(logger.layer([logger.format_logfmt.map(result.append)])))
    )
    assert len(result) == 1
    output = result[0]
    assert 'message="Welcome to the Effect Playground!"' in output
    assert "annotation1=first" in output
    assert "annotation2=second" in output
    assert 'annotation3="\\"omg\\""' in output
    assert 'message="\\"Welcome to the Effect Playground!\\""' not in output
    assert 'annotation1="\\"first\\""' not in output


@testing.effect
def test_format_simple_does_not_double_quote_string_messages_or_annotations():
    """formatSimple does not double quote string messages or annotations"""
    result: list[str] = []
    yield from (
        fx.log_info("hello world")
        .annotate_logs("annotation", "value with spaces")
        .pipe(fx.provide(logger.layer([logger.format_simple.map(result.append)])))
    )
    assert len(result) == 1
    output = result[0]
    assert 'message="hello world"' in output
    assert 'annotation="value with spaces"' in output
    assert 'message="\\"hello world\\""' not in output
    assert 'annotation="\\"value with spaces\\""' not in output


@testing.effect
def test_formats_big_int_messages_consistently():
    """formats BigInt messages consistently

    Python's ints are all arbitrary-precision and JSON numbers, so they are
    written as numbers everywhere (Effect writes a ``bigint`` as ``123n``)."""
    simple: list[str] = []
    log_fmt: list[str] = []
    structured: list[logger.StructuredLog] = []
    parsed: list[dict[str, object]] = []
    loggers = [
        logger.format_simple.map(simple.append),
        logger.format_logfmt.map(log_fmt.append),
        logger.format_structured.map(structured.append),
        logger.format_json.map(lambda output: parsed.append(json.loads(output))),
    ]
    yield from fx.log_info(123, {"value": 123}).pipe(fx.provide(logger.layer(loggers)))
    assert " level=INFO fiber=" in simple[0]
    assert 'message=123 message="{\\"value\\":123}"' in simple[0]
    assert " level=INFO fiber=" in log_fmt[0]
    assert 'message=123 message="{\\"value\\":123}"' in log_fmt[0]
    assert structured[0]["message"] == [123, {"value": 123}]
    assert structured[0]["level"] == "INFO"
    assert parsed[0]["message"] == [123, {"value": 123}]
    assert parsed[0]["level"] == "INFO"


@testing.effect
def test_format_json_includes_the_message_of_plain_errors():
    """formatJson includes the message of plain Errors"""
    parsed: list[dict[str, object]] = []
    json_logger = logger.format_json.map(lambda output: parsed.append(json.loads(output)))
    yield from (
        fx.fail(Exception("boom"))
        .tap_error(fx.log_error)
        .ignore()
        .pipe(fx.provide(logger.layer([json_logger])))
    )
    assert len(parsed) == 1
    assert parsed[0]["message"] == {"name": "Exception", "message": "boom"}
    assert parsed[0]["level"] == "ERROR"


@testing.effect
def test_annotate_logs_scoped_applies_annotations_only_while_scoped():
    """annotateLogsScoped applies annotations only while scoped"""
    annotations: list[dict[str, object]] = []

    @fx.gen
    def inside():
        yield from fx.annotate_logs_scoped("requestId", "req-123")
        yield from fx.log("inside")

    @fx.gen
    def program():
        yield from fx.log("before")
        yield from fx.scoped(inside)
        yield from fx.log("after")

    yield from program.pipe(fx.provide(logger.layer([_collecting(annotations)])))
    assert annotations == [{}, {"requestId": "req-123"}, {}]


@testing.effect
def test_annotate_logs_scoped_restores_previous_annotations():
    """annotateLogsScoped restores previous annotations"""
    annotations: list[dict[str, object]] = []
    scope = fx.CloseableScope()

    @fx.gen
    def program():
        yield from fx.log("before")
        yield from fx.annotate_logs_scoped("inner", "scope")
        yield from fx.log("after")

    yield from (
        program.annotate_logs("outer", "program")
        .ensuring(scope.close(_DONE))
        .and_then(fx.log("outside"))
        .pipe(fx.provide(logger.layer([_collecting(annotations)])))
    )
    assert annotations == [{"outer": "program"}, {"outer": "program", "inner": "scope"}, {}]


def _nan_annotation_run(initial: Mapping[str, object]):
    annotations: list[dict[str, object]] = []
    scope = fx.CloseableScope()
    nan = math.nan

    @fx.gen
    def program():
        yield from fx.annotate_logs_scoped("measurement", nan)
        yield from fx.log("inside")
        yield from scope.close(_DONE)
        yield from fx.log("after close")

    yield from (
        program.pipe(fx.provide_service(fx.Scope, scope))
        .annotate_logs(initial)
        .pipe(fx.provide(logger.layer([_collecting(annotations)])))
        .ensuring(scope.close(_DONE))
    )
    assert annotations == [{"measurement": nan}, dict(initial)]


@testing.effect
def test_annotate_logs_scoped_removes_nan_annotations():
    """annotateLogsScoped removes NaN annotations"""
    yield from _nan_annotation_run({})


@testing.effect
def test_annotate_logs_scoped_restores_nan_annotations():
    """annotateLogsScoped restores NaN annotations"""
    yield from _nan_annotation_run({"measurement": "previous"})


@testing.effect
def test_default_logger_preserves_message_item_order_when_logging_a_cause():
    """default logger preserves message item order when logging a cause"""
    yield from fx.log("first", fx.cause.fail("boom"), "second")
    result = yield from testing.log_lines
    assert re.match(_HEADER.pattern + ":", str(result[0]))
    assert result[1] == "first"
    assert result[2] == "second"
    assert "boom" in str(result[3])


@testing.effect
def test_batched_final_flush_uses_the_construction_context():
    """batched final flush uses the construction context"""
    output: list[str] = []
    construction = fx.Logger.make(lambda o: output.append(f"construction:{_text(o.message)}"))
    closing = fx.Logger.make(lambda o: output.append(f"closing:{_text(o.message)}"))
    scope = fx.CloseableScope()
    batched = (
        yield from fx.Logger.make(lambda o: _text(o.message))
        .batched(window="1 hour", flush=lambda batch: fx.log(",".join(batch)))
        .pipe(fx.provide_service(fx.Scope, scope))
        .pipe(fx.provide(logger.layer([construction])))
    )
    yield from fx.log("buffered").pipe(fx.provide(logger.layer([batched])))
    yield from scope.close(_DONE).pipe(fx.provide(logger.layer([closing])))
    assert output == ["construction:buffered"]


@testing.effect
def test_batched_finishes_an_in_flight_flush_before_flushing_remaining_entries_on_scope_close():
    """batched finishes an in-flight flush before flushing remaining entries on scope close"""
    events: list[str] = []
    started = yield from fx.Deferred[None].make()
    scope = fx.CloseableScope()

    def flush(batch: Sequence[str]) -> fx.Effect[None]:
        @fx.gen
        def run():
            events.append(f"start:{','.join(batch)}")
            if batch[0] == "first":
                yield from started.succeed(None)
                yield from fx.sleep("50 millis")
            events.append(f"end:{','.join(batch)}")

        return run

    batched = yield from (
        fx.Logger.make(lambda o: _text(o.message))
        .batched(window="1 millis", flush=flush)
        .pipe(fx.provide_service(fx.Scope, scope))
    )
    yield from fx.log("first").pipe(fx.provide(logger.layer([batched])))
    yield from testing.adjust("1 millis")
    yield from started.wait()
    yield from fx.log("second").pipe(fx.provide(logger.layer([batched])))
    closing = yield from scope.close(_DONE).fork(start_immediately=True)
    yield from testing.adjust("50 millis")
    yield from closing.join()
    assert events == ["start:first", "end:first", "start:second", "end:second"]
