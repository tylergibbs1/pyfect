"""The console effects, ``TestConsole``, and ``LiveConsole`` output as
Node 24 prints it (Effect has no ``Console.test.ts``; each expected output
below was printed by Node's ``console`` or by Effect's ``Console`` under
Node)."""

import io
import warnings

import pytest

import pyfect as fx
from pyfect import console, testing
from pyfect.console import CurrentConsole, LiveConsole
from pyfect.console._live import format_elapsed
from pyfect.testing import Entry, TestConsole


def _entries(eff: fx.Effect[object]) -> list[Entry]:
    test_console = TestConsole()
    fx.run_sync(eff.pipe(fx.provide_service(CurrentConsole, test_console)))
    return test_console.entries


# --- the effects ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("eff", "entry"),
    [
        (console.log("a", 1), Entry("log", ("a", 1))),
        (console.info("i"), Entry("info", ("i",))),
        (console.debug("d"), Entry("debug", ("d",))),
        (console.warn("w"), Entry("warn", ("w",))),
        (console.error("e", 2), Entry("error", ("e", 2))),
        (console.trace("t"), Entry("trace", ("t",))),
        (console.assert_(False, "x"), Entry("assert", (False, "x"))),
        (console.clear, Entry("clear", ())),
        (console.count(), Entry("count", ("default",))),
        (console.count("c"), Entry("count", ("c",))),
        (console.count_reset("c"), Entry("count_reset", ("c",))),
        (console.dir({"a": 1}), Entry("dir", ({"a": 1},))),
        (console.table([1], ["a"]), Entry("table", ([1], ["a"]))),
        (console.time_log("t", "extra"), Entry("time_log", ("t", "extra"))),
    ],
)
def test_each_effect_calls_its_console_method(eff: fx.Effect[None], entry: Entry):
    assert _entries(eff) == [entry]


def test_effects_read_the_console_when_they_run_not_when_built():
    eff = console.log("x")
    first, second = TestConsole(), TestConsole()
    fx.run_sync(eff.pipe(fx.provide_service(CurrentConsole, first)))
    fx.run_sync(eff.pipe(fx.provide_service(CurrentConsole, second)))
    assert first.entries == second.entries == [Entry("log", ("x",))]


def test_group_and_time_stay_open_until_the_scope_closes():
    eff = fx.scoped(
        console.group(label="g").and_then(console.time("t")).and_then(console.log("inside"))
    )
    assert _entries(eff) == [
        Entry("group", ("g",)),
        Entry("time", ("t",)),
        Entry("log", ("inside",)),
        Entry("time_end", ("t",)),
        Entry("group_end", ()),
    ]


def test_a_group_without_a_label_writes_no_line_and_collapsed_uses_group_collapsed():
    # Effect passes `undefined` on, and Node prints "undefined"; pyfect writes nothing.
    assert _entries(fx.scoped(console.group())) == [Entry("group", ()), Entry("group_end", ())]
    assert _entries(console.with_group(fx.void, label="L", collapsed=True)) == [
        Entry("group_collapsed", ("L",)),
        Entry("group_end", ()),
    ]


def test_with_group_and_with_time_close_after_a_failure():
    failing: fx.Effect[None, str] = console.log("in").and_then(fx.fail("boom"))
    test_console = TestConsole()
    ex = fx.run_sync_exit(
        console.with_time(console.with_group(failing, label="g"), "t").pipe(
            fx.provide_service(CurrentConsole, test_console)
        )
    )
    assert ex == fx.Failure(fx.cause.fail("boom"))
    assert [e.method for e in test_console.entries] == [
        "time",
        "group",
        "log",
        "group_end",
        "time_end",
    ]


def test_console_with_passes_the_current_console():
    test_console = TestConsole()
    seen = fx.run_sync(
        console.console_with(fx.succeed).pipe(fx.provide_service(CurrentConsole, test_console))
    )
    assert seen is test_console


# --- TestConsole -------------------------------------------------------------------


@testing.effect
def test_effect_tests_run_with_a_fresh_test_console():
    yield from console.log("a", "b")
    yield from console.info("not a log line")
    yield from console.error("e")
    yield from console.log("c")
    assert (yield from testing.log_lines) == ["a", "b", "c"]
    assert (yield from testing.error_lines) == ["e"]
    current = yield from testing.test_console()
    assert len(current.entries) == 4


@testing.effect
def test_the_default_logger_writes_to_the_test_console():
    yield from fx.log_info("hello")
    lines = yield from testing.log_lines
    assert lines[1] == "hello"


@testing.live
def test_live_tests_write_to_the_live_console(capsys: pytest.CaptureFixture[str]):
    yield from console.log("written")
    assert capsys.readouterr().out == "written\n"
    ex = yield from testing.log_lines.exit()
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.reasons[0], fx.cause.Die)
    assert "not a TestConsole" in str(ex.cause.reasons[0].defect)


def test_run_test_provides_a_test_console():
    lines = testing.run_test(console.log("x").and_then(testing.log_lines))
    assert lines == ["x"]


def test_test_console_layer_provides_a_fresh_test_console_per_build():
    eff = console.log("x").and_then(testing.log_lines)
    provided = eff.pipe(fx.provide(TestConsole.layer()))
    assert fx.run_sync(provided) == ["x"]
    assert fx.run_sync(provided) == ["x"]


# --- LiveConsole, as Node prints -------------------------------------------------


def _table(data: object, properties: list[str] | None = None) -> str:
    out = io.StringIO()
    live = LiveConsole()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("sys.stdout", out)
        live.table(data, properties)
    return out.getvalue()


def test_table_of_mapping_rows():
    assert _table([{"a": 1, "b": "Y"}, {"a": "Z", "b": 2}]) == (
        "┌─────────┬─────┬─────┐\n"
        "│ (index) │ a   │ b   │\n"
        "├─────────┼─────┼─────┤\n"
        "│ 0       │ 1   │ 'Y' │\n"
        "│ 1       │ 'Z' │ 2   │\n"
        "└─────────┴─────┴─────┘\n"
    )


def test_table_indexes_a_mapping_by_key_and_puts_scalars_under_values():
    assert _table({"x": {"a": 1}, "y": {"b": [1, 2]}}) == (
        "┌─────────┬───┬────────┐\n"
        "│ (index) │ a │ b      │\n"
        "├─────────┼───┼────────┤\n"
        "│ x       │ 1 │        │\n"
        "│ y       │   │ [1, 2] │\n"
        "└─────────┴───┴────────┘\n"
    )
    assert _table([1, "two", {"a": 3}]) == (
        "┌─────────┬───┬────────┐\n"
        "│ (index) │ a │ Values │\n"
        "├─────────┼───┼────────┤\n"
        "│ 0       │   │ 1      │\n"
        "│ 1       │   │ 'two'  │\n"
        "│ 2       │ 3 │        │\n"
        "└─────────┴───┴────────┘\n"
    )


def test_table_properties_pick_the_columns_and_drop_values():
    assert _table([1, {"a": 1, "b": 2}], ["a"]) == (
        "┌─────────┬───┐\n"
        "│ (index) │ a │\n"
        "├─────────┼───┤\n"
        "│ 0       │   │\n"
        "│ 1       │ 1 │\n"
        "└─────────┴───┘\n"
    )


def test_table_of_sequence_rows_and_of_nothing():
    assert _table([[1, 2], [3]]) == (
        "┌─────────┬───┬───┐\n"
        "│ (index) │ 0 │ 1 │\n"
        "├─────────┼───┼───┤\n"
        "│ 0       │ 1 │ 2 │\n"
        "│ 1       │ 3 │   │\n"
        "└─────────┴───┴───┘\n"
    )
    assert _table([]) == "┌─────────┐\n│ (index) │\n├─────────┤\n└─────────┘\n"


def test_table_pads_wide_and_combining_characters_by_their_display_width():
    # Node measures cells with getStringWidth: CJK and emoji take two columns.
    assert _table(["日本", "e\u0301"]) == (
        "┌─────────┬────────┐\n"
        "│ (index) │ Values │\n"
        "├─────────┼────────┤\n"
        "│ 0       │ '日本' │\n"
        "│ 1       │ 'e\u0301'    │\n"
        "└─────────┴────────┘\n"
    )


def test_table_logs_a_scalar_or_string_as_is():
    assert _table(5) == "5\n"
    assert _table("str") == "str\n"


def test_assert_count_group_and_dir(capsys: pytest.CaptureFixture[str]):
    live = LiveConsole()
    live.assert_(False, "x", 1)
    live.assert_(False, 1, "x")
    live.assert_(False)
    live.assert_(True, "no")
    live.count()
    live.count()
    live.count("a")
    live.count_reset()
    live.count()
    live.group("G")
    live.warn("w")
    live.group_collapsed()
    live.log("deep\nx")
    live.group_end()
    live.group_end()
    live.group_end()
    live.log("back")
    live.dir("s")
    live.group(1, "two")
    live.log("in")
    live.group_end()
    out, err = capsys.readouterr()
    assert err == "Assertion failed: x 1\nAssertion failed 1 x\nAssertion failed\n  w\n"
    assert out == (
        "default: 1\ndefault: 2\na: 1\ndefault: 1\nG\n    deep\n    x\nback\n's'\n1 two\n  in\n"
    )


def test_misused_counters_and_timers_warn():
    live = LiveConsole()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        live.count_reset("zz")
        live.time()
        live.time()
        live.time_end("nope")
        live.time_log("nope2")
    assert [str(w.message) for w in caught] == [
        "Count for 'zz' does not exist",
        "Label 'default' already exists for console.time()",
        "No such label 'nope' for console.time_end()",
        "No such label 'nope2' for console.time_log()",
    ]
    assert all(w.category is RuntimeWarning for w in caught)


def test_time_log_and_time_end_write_the_elapsed_time(capsys: pytest.CaptureFixture[str]):
    live = LiveConsole()
    live.time("x")
    live.time_log("x", "extra")
    live.time_end("x")
    with pytest.warns(RuntimeWarning, match="No such label 'x'"):
        live.time_end("x")
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("x: ")
    assert lines[0].endswith("ms extra")
    assert lines[1].startswith("x: ")


@pytest.mark.parametrize(
    ("ms", "text"),
    [
        (0.023, "0.023ms"),
        (1.5, "1.5ms"),
        (2.0, "2ms"),
        (0.0625, "0.063ms"),
        (1062.5, "1.063s"),
        (61_062.5, "1:01.063 (m:ss.mmm)"),
        (1099.4, "1.099s"),
        (65_000.0, "1:05.000 (m:ss.mmm)"),
        (3_665_250.0, "1:01:05.250 (h:mm:ss.mmm)"),
    ],
)
def test_elapsed_times_are_formatted_as_node_formats_them(ms: float, text: str):
    assert format_elapsed(ms) == text


def test_clear_writes_nothing_when_stdout_is_not_a_tty(capsys: pytest.CaptureFixture[str]):
    LiveConsole().clear()
    assert capsys.readouterr().out == ""
