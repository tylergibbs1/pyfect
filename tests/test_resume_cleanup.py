"""A callback's ``resume`` hands over a result, never work that must run.

The effect given to ``resume`` runs as the resumed fiber's next step, after a
point where it can pause and be interrupted: anything chained in it (stopping
race losers, releasing a claim) is then skipped. Work that must happen however
the wait ends belongs in an ``on_exit`` around the callback (Effect's
``onExitUnsafe`` hooks), as ``_race`` does. The interleaving harness found the
race version of this bug (tests/interleave/test_regressions.py); this keeps the
whole class out of ``src``."""

import ast
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "pyfect"

# Combinators that chain more work after (or around) a result, and runtime
# calls that are work in themselves.
CHAINING = {"and_then", "flat_map", "ensuring", "on_exit", "on_interrupt", "tap", "zip_right"}
WORK = {"interrupt_all", "_SetInterruptible", "uninterruptible"}


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def chained_work_in_resumes(source: str) -> list[tuple[int, str]]:
    """``(line, call)`` for each ``resume(...)`` whose argument chains work."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _called_name(node) == "resume" and node.args):
            continue
        for inner in ast.walk(node.args[0]):
            if isinstance(inner, ast.Call) and _called_name(inner) in CHAINING | WORK:
                found.append((node.lineno, ast.unparse(node)[:120]))
                break
    return found


def test_no_resume_in_src_chains_work_after_its_result():
    found = [
        f"{path.relative_to(SRC)}:{line}: {call}"
        for path in sorted(SRC.rglob("*.py"))
        for line, call in chained_work_in_resumes(path.read_text())
    ]
    assert found == [], "work handed to resume (put it in an on_exit):\n" + "\n".join(found)


def test_it_flags_the_race_losers_stopped_inside_resume():
    """The shape ``_race`` had before the fix."""
    before = (
        "resume(_SetInterruptible(_Suspend(stop_losers), False).and_then(_FromExit(ex)))\n"
        "resume(_FromExit(ex))\n"
    )
    assert [line for line, _ in chained_work_in_resumes(before)] == [1]
