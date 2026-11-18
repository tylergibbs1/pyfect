"""``match`` takes apart pyfect's data with positional patterns: Exit, Option,
Result, Cause and its reasons, and dataclass tagged errors (schema classes
take keywords, so they match by keyword). ``tests/type_checks.py`` pins how
pyright narrows each case; this pins that the patterns match at run time."""

from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.cause import Die, Fail, Interrupt
from pyfect.errors import Done


@dataclass(eq=False)
class NotFound(fx.TaggedError):
    key: str


class Gone(S.TaggedError):
    id: int


def describe(ex: fx.Exit[int, NotFound]) -> str:
    match ex:
        case fx.Success(value):
            return f"value {value}"
        case fx.Failure(fx.Cause([Fail(NotFound(key))])):
            return f"no {key}"
        case fx.Failure(fx.Cause([Die(ZeroDivisionError() as defect), *_])):
            return f"crashed: {defect}"
        case fx.Failure(fx.Cause([Interrupt(_), *_])):
            return "interrupted"
        case fx.Failure(cause):
            return f"other: {cause!r}"


def test_exits_of_runs_match_positionally() -> None:
    assert describe(fx.run_sync_exit(fx.succeed(1))) == "value 1"
    assert describe(fx.run_sync_exit(fx.fail(NotFound("motd")))) == "no motd"
    crashed = fx.run_sync_exit(fx.sync(lambda: 1 // 0))
    assert describe(crashed) == "crashed: division by zero"
    assert describe(fx.run_sync_exit(fx.interrupt())) == "interrupted"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (fx.Some(None), "some None"),
        (None, "none"),
        (fx.Ok(2), "ok 2"),
        (fx.Err("bad"), "err bad"),
        (Done(3), "done 3"),
        (Gone(id=7), "gone 7"),
    ],
)
def test_options_results_and_errors_match(
    value: fx.Option[None] | fx.Result[int, str] | Done[int] | Gone, expected: str
) -> None:
    match value:
        case fx.Some(inner):
            got = f"some {inner}"
        case None:
            got = "none"
        case fx.Ok(ok):
            got = f"ok {ok}"
        case fx.Err(err):
            got = f"err {err}"
        case Done(left):
            got = f"done {left}"
        case Gone(id=gone):
            got = f"gone {gone}"
        case _:
            got = "no match"
    assert got == expected


def test_schema_classes_refuse_positional_patterns() -> None:
    with pytest.raises(TypeError, match="accepts 0 positional sub-patterns"):
        match Gone(id=1):
            case Gone(_):  # pyright: ignore[reportGeneralTypeIssues, reportUnknownVariableType]
                pass
            case _:
                pass
