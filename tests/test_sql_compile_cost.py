"""The statement compiler takes time linear in a statement's segments: an
``and_`` / ``or_`` over a request-sized list used to copy the whole text for
every segment. Empty ``IN`` lists still read the text before them as a whole."""

import ast
import random
import re

import _source
from _growth import Work, assert_near_linear
from _guards import guards

import pyfect as fx
from pyfect.sql import statement as st
from pyfect.sql.statement import Fragment, Literal, Parameter, and_, make_compiler_sqlite
from pyfect.sql.statement._compiler import _Text  # pyright: ignore[reportPrivateUsage]


@guards("e87833d3", "sql-text-joined-per-append")
def test_and_of_many_clauses_compiles_in_near_linear_time() -> None:
    def sized(n: int) -> Work:
        fragment = and_([Fragment((Literal("tag = "), Parameter(i))) for i in range(n)])
        # A fresh compiler each run: no cached result.
        return lambda: make_compiler_sqlite().compile(fragment)

    assert_near_linear(sized, 5_000, 8 * 5_000, bound=32)


@guards("e87833d3", "sql-empty-in-scans-whole-text")
def test_many_empty_in_lists_on_one_line_compile_in_near_linear_time() -> None:
    sql = st.make(fx.never, make_compiler_sqlite(), [], None)

    def sized(n: int) -> Work:
        fragment = and_([sql("a IN {}", sql.in_([])) for _ in range(n)])
        return lambda: make_compiler_sqlite().compile(fragment)

    assert_near_linear(sized, 2_000, 8 * 2_000, bound=32)


_KEYWORD = re.compile(r"\b(NOT\s+)?IN\s*$", re.IGNORECASE)


def _whole_text(sql: str) -> tuple[int, bool] | None:
    """What the compiler read from the whole text before."""
    match = _KEYWORD.search(sql)
    if match is None:
        return None
    index = match.start()
    if sql.rfind("--", 0, index + 2) > sql.rfind("\n", 0, index + 1):
        return None
    return index, match.group(1) is not None


_PIECES = ["a", " ", "  ", "IN", "in", "NOT", "not", "-", "--", "\n", "JOIN", "x(", "b = ?", " IN "]


def test_empty_in_reads_the_parts_as_the_whole_text_would() -> None:
    rng = random.Random(7)
    for _ in range(20_000):
        parts = [
            "".join(rng.choices(_PIECES, k=rng.randint(0, 4))) for _ in range(rng.randint(0, 6))
        ]
        text = _Text()
        for part in parts:
            text.append(part)
        whole = "".join(parts)
        assert text.empty_in() == _whole_text(whole), parts
        keyword = text.empty_in()
        if keyword is not None:
            text.replace_from(keyword[0], "= ANY('{}')")
            replaced = whole[: keyword[0]] + "= ANY('{}')"
            assert text.value() == replaced
            text.append(" AND c IN\n")
            assert text.empty_in() == _whole_text(replaced + " AND c IN\n"), parts


def test_the_sql_compiler_never_grows_text_on_an_attribute() -> None:
    """``self.text += part`` copies the text each time; parts go in a list."""
    root = _source.SRC / "sql"
    found = [
        f"{path.relative_to(root)}:{node.lineno}"
        for path in _source.files(root)
        for node in _source.walk(path)
        if isinstance(node, ast.AugAssign)
        and isinstance(node.op, ast.Add)
        and isinstance(node.target, ast.Attribute | ast.Subscript)
        and (
            isinstance(node.value, ast.JoinedStr)
            or (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))
        )
    ]
    assert found == []
