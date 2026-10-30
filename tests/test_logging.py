"""Logging behavior beyond Effect's own tests: level filtering, logger
installation, the console loggers, the ``logging`` bridge, and failures
reported at ``UnhandledLogLevel``."""

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import logger, testing
from pyfect.console import CurrentConsole, LiveConsole
from pyfect.logger._text import format_unknown, json_text


def _capture() -> tuple[list[logger.Options], fx.Logger[None]]:
    entries: list[logger.Options] = []
    return entries, fx.Logger.make(entries.append)


def _messages(entries: list[logger.Options]) -> list[tuple[object, ...]]:
    return [e.message for e in entries]


# --- levels -----------------------------------------------------------------


def test_levels_order_as_effects_and_match_the_standard_library():
    assert list(fx.LogLevel) == [
        fx.LogLevel.ALL,
        fx.LogLevel.FATAL,
        fx.LogLevel.ERROR,
        fx.LogLevel.WARN,
        fx.LogLevel.INFO,
        fx.LogLevel.DEBUG,
        fx.LogLevel.TRACE,
        fx.LogLevel.NONE,
    ]
    assert fx.LogLevel.ALL < fx.LogLevel.TRACE < fx.LogLevel.DEBUG < fx.LogLevel.FATAL
    assert fx.LogLevel.FATAL < fx.LogLevel.NONE
    assert fx.LogLevel.WARN == logging.WARNING
    assert fx.LogLevel.FATAL == logging.CRITICAL


@testing.effect
def test_logs_below_the_minimum_level_are_dropped():
    entries, capture = _capture()

    @fx.gen
    def program():
        yield from fx.log_debug("hidden")
        yield from fx.log_info("shown")

    yield from program.with_logger(capture)
    assert _messages(entries) == [("shown",)]
    entries.clear()
    yield from program.with_logger(capture).pipe(
        fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ALL)
    )
    assert _messages(entries) == [("hidden",), ("shown",)]
    entries.clear()
    yield from program.with_logger(capture).pipe(
        fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.NONE)
    )
    assert entries == []


@testing.effect
def test_log_writes_at_the_current_log_level():
    entries, capture = _capture()
    yield from (
        fx.log("x")
        .with_logger(capture)
        .pipe(fx.provide_service(fx.CurrentLogLevel, fx.LogLevel.ERROR))
    )
    assert [e.log_level for e in entries] == [fx.LogLevel.ERROR]


@testing.effect
def test_each_level_function_logs_at_its_level():
    entries, capture = _capture()
    yield from (
        fx.all(
            fx.log_fatal(),
            fx.log_error(),
            fx.log_warning(),
            fx.log_info(),
            fx.log_debug(),
            fx.log_trace(),
        )
        .as_void()
        .with_logger(capture)
        .pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ALL))
    )
    assert [e.log_level.name for e in entries] == [
        "FATAL",
        "ERROR",
        "WARN",
        "INFO",
        "DEBUG",
        "TRACE",
    ]


# --- entries ----------------------------------------------------------------


@testing.effect
def test_causes_are_taken_out_of_the_message_and_merged():
    entries, capture = _capture()
    yield from fx.log(fx.cause.fail("a"), "text", fx.cause.die(ValueError("b"))).with_logger(
        capture
    )
    (entry,) = entries
    assert entry.message == ("text",)
    assert entry.cause.failures == ("a",)
    assert isinstance(entry.cause.find_defect(), ValueError)


@testing.effect
def test_the_entry_time_comes_from_the_clock_and_spans_measure_from_their_start():
    lines: list[str] = []

    @fx.gen
    def program():
        yield from testing.adjust(0.25)
        yield from fx.log("tick")

    yield from (
        program.with_log_span("outer")
        .pipe(fx.provide(logger.layer([logger.format_logfmt.map(lines.append)])))
        .pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ALL))
    )
    assert lines[0].startswith("timestamp=1970-01-01T00:00:00.250Z level=INFO fiber=#")
    assert lines[0].endswith("message=tick outer=250ms")


@testing.effect
def test_annotations_and_spans_nest():
    structured: list[logger.StructuredLog] = []
    yield from (
        fx.log("x")
        .annotate_logs({"a": 1, "b": 2})
        .with_log_span("inner")
        .annotate_logs("a", 3)
        .with_log_span("outer")
        .with_logger(logger.format_structured.map(structured.append))
    )
    assert structured[0]["annotations"] == {"a": 1, "b": 2}
    assert list(structured[0]["spans"]) == ["inner", "outer"]


@testing.effect
def test_a_logger_that_raises_is_a_defect():
    def boom(_: logger.Options) -> None:
        raise RuntimeError("logger broke")

    ex = yield from fx.log("x").with_logger(fx.Logger.make(boom)).exit()
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.find_defect(), RuntimeError)


@pytest.mark.parametrize(
    "make",
    [lambda: float("nan"), lambda: int("12345678901234"), lambda: "".join(["re", "q"])],
    ids=["nan", "int", "str"],
)
@testing.effect
def test_annotate_logs_scoped_compares_numbers_and_strings_by_value(make: Callable[[], object]):
    """Effect compares annotation values with ``===`` / ``Object.is``, so a
    later ``annotate_logs_scoped`` setting an equal number or string (a
    distinct Python object, NaN included) still counts as the earlier one's
    value, and closing the earlier scope removes the key. Checked against
    Effect under Node."""
    seen: list[dict[str, object]] = []
    record = fx.Logger.make(lambda o: seen.append(dict(o.fiber.get_ref(fx.CurrentLogAnnotations))))
    first, second = fx.CloseableScope(), fx.CloseableScope()
    a, b = make(), make()
    assert a is not b

    @fx.gen
    def inner():
        yield from fx.annotate_logs_scoped("m", b)
        yield from first.close(fx.Success(None))
        yield from fx.log("after first close")

    @fx.gen
    def outer():
        yield from fx.annotate_logs_scoped("m", a)
        yield from inner.pipe(fx.provide_service(fx.Scope, second))

    yield from outer.pipe(fx.provide_service(fx.Scope, first)).with_logger(record)
    yield from second.close(fx.Success(None))
    assert seen == [{}]


@testing.effect
def test_annotate_logs_scoped_compares_objects_by_identity():
    """An equal but distinct dict is another value (``===``): closing the
    earlier scope leaves the later annotation in place."""
    seen: list[dict[str, object]] = []
    record = fx.Logger.make(lambda o: seen.append(dict(o.fiber.get_ref(fx.CurrentLogAnnotations))))
    first, second = fx.CloseableScope(), fx.CloseableScope()

    @fx.gen
    def inner():
        yield from fx.annotate_logs_scoped("m", {"v": 1})
        yield from first.close(fx.Success(None))
        yield from fx.log("after first close")

    @fx.gen
    def outer():
        yield from fx.annotate_logs_scoped("m", {"v": 1})
        yield from inner.pipe(fx.provide_service(fx.Scope, second))

    yield from outer.pipe(fx.provide_service(fx.Scope, first)).with_logger(record)
    yield from second.close(fx.Success(None))
    assert seen == [{"m": {"v": 1}}]


@testing.effect
def test_annotate_logs_scoped_removes_an_object_annotation_on_close():
    seen: list[dict[str, object]] = []
    record = fx.Logger.make(lambda o: seen.append(dict(o.fiber.get_ref(fx.CurrentLogAnnotations))))
    scope = fx.CloseableScope()

    @fx.gen
    def program():
        yield from fx.annotate_logs_scoped("user", {"id": 7})
        yield from fx.log("inside")
        yield from scope.close(fx.Success(None))
        yield from fx.log("after close")

    yield from program.pipe(fx.provide_service(fx.Scope, scope)).with_logger(record)
    assert seen == [{"user": {"id": 7}}, {}]


# --- installing loggers ---------------------------------------------------------


@testing.effect
def test_with_logger_adds_to_the_current_loggers_once():
    console = testing.TestConsole()
    entries, capture = _capture()
    yield from (
        fx.log("x")
        .with_logger(capture)
        .with_logger(capture)
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    assert len(entries) == 1
    assert [method for method, _ in console.entries] == ["log"]


@testing.effect
def test_layer_replaces_the_loggers_unless_merging():
    console = testing.TestConsole()
    entries, capture = _capture()
    yield from (
        fx.log("x")
        .pipe(fx.provide(logger.layer([capture])))
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    assert len(entries) == 1
    assert console.entries == []
    yield from (
        fx.log("y")
        .pipe(fx.provide(logger.layer([capture], merge_with_existing=True)))
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    assert len(entries) == 2
    assert len(console.entries) == 1


@testing.effect
def test_layer_installs_each_logger_once():
    """The loggers are a set, as Effect's: a logger listed twice, or one
    already installed when merging, logs each entry once."""
    entries, capture = _capture()
    yield from fx.log("x").pipe(fx.provide(logger.layer([capture, capture])))
    yield from (
        fx.log("y")
        .pipe(fx.provide(logger.layer([capture], merge_with_existing=True)))
        .pipe(fx.provide(logger.layer([capture])))
    )
    assert _messages(entries) == [("x",), ("y",)]


@testing.effect
def test_an_empty_layer_silences_logging():
    console = testing.TestConsole()
    yield from (
        fx.log("x")
        .pipe(fx.provide(logger.layer([])))
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    assert console.entries == []


@testing.effect
def test_batched_keeps_flushing_after_the_fiber_that_made_it_ends():
    """The timer is detached (Effect's ``forkDetach``): a batched logger
    made in a fiber that has since ended still flushes on its window.
    Checked against Effect under Node."""
    flushed: list[list[str]] = []
    scope = fx.CloseableScope()

    def flush(batch: Sequence[str]) -> fx.Effect[None]:
        return fx.sync(lambda: flushed.append(list(batch)))

    made = (
        fx.Logger.make(lambda o: str(o.message[0]))
        .batched(window=1, flush=flush)
        .pipe(fx.provide_service(fx.Scope, scope))
    )
    batched = yield from (yield from made.fork()).join()
    yield from fx.log("x").pipe(fx.provide(logger.layer([batched])))
    yield from testing.adjust(1)
    assert flushed == [["x"]]
    yield from scope.close(fx.Success(None))


# --- console loggers ------------------------------------------------------------


@testing.effect
def test_log_to_stderr_switches_the_console_method():
    console = testing.TestConsole()
    yield from (
        fx.log("x")
        .pipe(fx.provide_service(CurrentConsole, console))
        .pipe(fx.provide_service(fx.LogToStderr, True))
    )
    assert [method for method, _ in console.entries] == ["error"]


@testing.effect
def test_with_leveled_console_picks_the_method_by_level():
    console = testing.TestConsole()
    leveled = logger.format_simple.with_leveled_console()
    yield from (
        fx.all(
            fx.log_trace(),
            fx.log_debug(),
            fx.log_info(),
            fx.log_warning(),
            fx.log_error(),
            fx.log_fatal(),
        )
        .as_void()
        .pipe(fx.provide(logger.layer([leveled])))
        .pipe(fx.provide_service(CurrentConsole, console))
        .pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ALL))
    )
    assert [method for method, _ in console.entries] == [
        "trace",
        "debug",
        "info",
        "warn",
        "error",
        "error",
    ]


@testing.effect
def test_console_pretty_writes_a_header_then_a_group():
    console = testing.TestConsole()
    pretty = logger.console_pretty(colors=False, format_date=lambda _: "T")
    yield from (
        fx.log_warning("hello", {"n": 1}, fx.cause.fail("bad"))
        .annotate_logs("user", "ada")
        .pipe(fx.provide(logger.layer([pretty])))
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    methods = [method for method, _ in console.entries]
    assert methods == ["log", "group", "log", "log", "log", "group_end"]
    header = str(console.entries[0][1][0])
    assert header.startswith("[T] WARN (#")
    assert header.endswith(": hello")
    assert "bad" in str(console.entries[2][1][0])
    assert console.entries[3][1] == ({"n": 1},)
    assert console.entries[4][1] == ("user:", "ada")


@testing.effect
def test_console_pretty_puts_a_logged_function_in_the_header():
    """Effect's ``structuredMessage`` turns a function into a string, so a
    function logged first joins the header line."""
    console = testing.TestConsole()

    def handler() -> None: ...

    pretty = logger.console_pretty(colors=False, format_date=lambda _: "T")
    yield from (
        fx.log(handler)
        .pipe(fx.provide(logger.layer([pretty])))
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    assert str(console.entries[0][1][0]).endswith(f": {handler}")
    assert [method for method, _ in console.entries] == ["log", "group", "group_end"]


@testing.effect
def test_console_pretty_colors_the_level():
    console = testing.TestConsole()
    yield from (
        fx.log_error("x")
        .pipe(fx.provide(logger.layer([logger.console_pretty(colors=True)])))
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    header = str(console.entries[0][1][0])
    assert "\x1b[31mERROR\x1b[0m" in header
    assert "\x1b[1m\x1b[36mx\x1b[0m" in header


@testing.effect
def test_console_json_writes_one_json_line():
    console = testing.TestConsole()
    yield from (
        fx.log("x")
        .pipe(fx.provide(logger.layer([logger.console_json])))
        .pipe(fx.provide_service(CurrentConsole, console))
    )
    ((method, (line,)),) = console.entries
    assert method == "log"
    assert str(line).startswith('{"message":"x","level":"INFO"')


def test_live_console_writes_to_stdout_and_stderr_with_group_indentation(
    capsys: pytest.CaptureFixture[str],
):
    console = LiveConsole()
    console.log("a", 1, {"k": "v"})
    console.group("title")
    console.info("two\nlines")
    console.error("oops")
    console.group_end()
    console.trace("t")
    out, err = capsys.readouterr()
    assert out == "a 1 {'k': 'v'}\ntitle\n  two\n  lines\n"
    assert err == "  oops\nTrace: t\n"


# --- the logging bridge -----------------------------------------------------------


@testing.effect
def test_to_logging_hands_entries_to_the_standard_library(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="pyfect.test")
    yield from testing.adjust(1.5)
    yield from (
        fx.log_warning("hello", 42, fx.cause.die(ValueError("bad")))
        .annotate_logs("user", "ada")
        .with_log_span("span")
        .pipe(fx.provide(logger.layer([logger.to_logging("pyfect.test")])))
    )
    (record,) = caplog.records
    extra: Any = record
    assert record.name == "pyfect.test"
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "hello 42"
    assert record.created == 1.5
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], ValueError)
    assert extra.log_annotations == {"user": "ada"}
    assert extra.log_spans == {"span": 0}
    assert str(extra.fiber_id).startswith("#")


def test_to_logging_respects_the_target_level_and_names_trace(
    caplog: pytest.LogCaptureFixture,
):
    target = logging.getLogger("pyfect.levels")
    caplog.set_level(logging.WARNING, logger="pyfect.levels")
    program = (
        fx.all(fx.log_trace("t"), fx.log_info("i"), fx.log_error("e"))
        .as_void()
        .pipe(fx.provide(logger.layer([logger.to_logging(target)])))
        .pipe(fx.provide_service(fx.MinimumLogLevel, fx.LogLevel.ALL))
    )
    testing.run_test(program)
    assert [r.getMessage() for r in caplog.records] == ["e"]
    assert logging.getLevelName(fx.LogLevel.TRACE) == "TRACE"


def test_to_logging_skips_levels_the_target_logger_disables():
    """``Logger.handle`` does not check the logger's own level (``log``
    does), so the bridge must: a handler accepting everything still gets
    nothing below the target's level."""
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    target = logging.getLogger("pyfect.own_level")
    target.setLevel(logging.WARNING)
    target.propagate = False
    handler = Collect(logging.NOTSET)
    target.addHandler(handler)
    try:
        testing.run_test(
            fx.log_info("i")
            .and_then(fx.log_warning("w"))
            .pipe(fx.provide(logger.layer([logger.to_logging(target)])))
        )
    finally:
        target.removeHandler(handler)
    assert [r.getMessage() for r in records] == ["w"]


# --- failures nobody can handle ---------------------------------------------------


def _failing_release(_a: object, _ex: fx.Exit[Any, Any]) -> fx.Effect[None]:
    return fx.die(RuntimeError("release failed"))


@testing.effect
def test_a_failing_pool_finalizer_is_logged_at_the_unhandled_log_level():
    entries, capture = _capture()
    acquire = fx.acquire_release(fx.succeed("item"), _failing_release)

    @fx.gen
    def program():
        pool = yield from fx.Pool.make(acquire, size=1)
        item = yield from pool.use(fx.succeed)
        yield from pool.invalidate(item)
        yield from pool.use(fx.succeed)

    only_capture = fx.provide(logger.layer([capture]))
    yield from fx.scoped(program).pipe(only_capture)
    # The invalidated item, then the replacement when the pool shuts down.
    assert len(entries) == 2
    for entry in entries:
        assert entry.message == ("Unhandled error in pool finalizer",)
        assert entry.log_level is fx.LogLevel.ERROR
        assert isinstance(entry.cause.find_defect(), RuntimeError)
    entries.clear()
    yield from (
        fx.scoped(program).pipe(only_capture).pipe(fx.provide_service(fx.UnhandledLogLevel, None))
    )
    assert entries == []


@testing.effect
def test_a_failing_scoped_cache_finalizer_is_logged_on_eviction():
    entries, capture = _capture()

    def lookup(key: int) -> fx.Effect[int, Never, fx.Scope]:
        return fx.acquire_release(fx.succeed(key), _failing_release)

    @fx.gen
    def program():
        cache = yield from fx.ScopedCache.make(lookup, capacity=1)
        yield from fx.scoped(cache.get(1))
        yield from fx.scoped(cache.get(2))

    # Closing the cache itself still fails with the last entry's release.
    ex = yield from (
        fx.scoped(program)
        .exit()
        .pipe(fx.provide(logger.layer([capture])))
        .pipe(fx.provide_service(fx.UnhandledLogLevel, fx.LogLevel.WARN))
    )
    assert isinstance(ex, fx.Failure)
    assert [(e.message, e.log_level) for e in entries] == [
        (("Unhandled error in ScopedCache finalizer",), fx.LogLevel.WARN)
    ]


# --- rendering values ---------------------------------------------------------------


@dataclass
class _Point:
    x: int
    y: int


def test_format_unknown_writes_json_like_text():
    cyclic: list[object] = [1]
    cyclic.append(cyclic)
    error = ValueError("inner")
    outer = RuntimeError("outer")
    outer.__cause__ = error
    assert format_unknown({"a": [1, "b", None, True, 1.5]}) == '{"a":[1,"b",null,true,1.5]}'
    assert format_unknown(_Point(1, 2)) == '_Point({"x":1,"y":2})'
    assert format_unknown(cyclic) == "[1,[Circular]]"
    assert format_unknown(outer) == "RuntimeError: outer (cause: ValueError: inner)"
    assert format_unknown(math.nan) == "NaN"
    assert format_unknown(frozenset([3])) == "frozenset([3])"


def test_json_text_drops_cycles_and_writes_exceptions_by_name():
    cyclic: dict[str, object] = {"a": 1}
    cyclic["self"] = cyclic
    assert json_text(cyclic) == '{"a":1}'
    assert json_text([math.inf, _Point(1, 2)]) == '[null,{"x":1,"y":2}]'
    assert json_text(KeyError("k")) == '{"name":"KeyError","message":"\'k\'"}'


@pytest.mark.parametrize("format", [logger.format_simple, logger.format_logfmt])
@testing.effect
def test_line_breaks_in_logged_values_cannot_start_a_new_log_line(format: fx.Logger[str]):
    lines: list[str] = []
    yield from (
        fx.log("ok\nlevel=ERROR forged", "\r\nlevel=ERROR")
        .annotate_logs("user", "a\r\nb")
        .pipe(fx.provide(logger.layer([format.map(lines.append)])))
    )
    assert len(lines) == 1
    assert "\n" not in lines[0]
    assert "\r" not in lines[0]
    assert '"ok\\nlevel=ERROR forged"' in lines[0]
    assert 'user="a\\r\\nb"' in lines[0]


@pytest.mark.parametrize("format", [logger.format_simple, logger.format_logfmt])
@pytest.mark.parametrize(
    "brk", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
)
@testing.effect
def test_no_line_separator_in_a_logged_value_reaches_the_line(format: fx.Logger[str], brk: str):
    # str.splitlines (and many log readers) also break lines at these.
    lines: list[str] = []
    yield from (
        fx.log(f"ok{brk}level=ERROR forged")
        .annotate_logs("user", f"a{brk}b")
        .pipe(fx.provide(logger.layer([format.map(lines.append)])))
    )
    assert len(lines) == 1
    assert lines[0].splitlines() == [lines[0]]
