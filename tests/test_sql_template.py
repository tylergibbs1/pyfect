"""SQL templates: ``str.format``-style placeholders (and t-strings on 3.14)
compile to parameters, never to interpolated text."""

import sys
from typing import Any

import pytest

import pyfect as fx
from pyfect.sql import statement as st

sql = st.make(fx.never, st.make_compiler_sqlite(), [], None)


def test_automatic_numbered_and_named_placeholders_become_parameters():
    assert sql("SELECT {} + {}", 1, 2).compile() == ("SELECT ? + ?", (1, 2))
    assert sql("SELECT {1}, {0}, {1}", "a", "b").compile() == ("SELECT ?, ?, ?", ("b", "a", "b"))
    assert sql("WHERE id = {id}", id=7).compile() == ("WHERE id = ?", (7,))


def test_doubled_braces_are_literal_text():
    assert sql("SELECT '{{}}', {}", 1).compile() == ("SELECT '{}', ?", (1,))


def test_a_value_that_looks_like_sql_stays_a_parameter():
    assert sql("SELECT {}", "1; DROP TABLE users").compile() == (
        "SELECT ?",
        ("1; DROP TABLE users",),
    )


def test_fragments_and_helpers_nest():
    where = sql("id = {}", 1)
    assert sql("SELECT * FROM {} WHERE {}", sql.identifier("users"), where).compile() == (
        'SELECT * FROM "users" WHERE id = ?',
        (1,),
    )
    assert sql("WHERE id IN {}", sql.in_([1, 2])).compile() == ("WHERE id IN (?,?)", (1, 2))


@pytest.mark.parametrize(
    ("template", "args", "kwargs", "error"),
    [
        ("{} {0}", (1,), {}, ValueError),
        ("{}", (), {}, IndexError),
        ("{name}", (), {}, KeyError),
        ("{}", (1, 2), {}, TypeError),
        ("{!r}", (1,), {}, ValueError),
        ("{:>4}", (1,), {}, ValueError),
        ("{a.b}", (), {"a": 1}, ValueError),
    ],
)
def test_malformed_templates_raise_where_they_are_written(
    template: str, args: tuple[object, ...], kwargs: dict[str, object], error: type[Exception]
):
    with pytest.raises(error):
        sql(template, *args, **kwargs)  # pyright: ignore[reportArgumentType]


def test_empty_insert_is_rejected_where_it_is_built():
    with pytest.raises(ValueError, match="at least one row"):
        sql.insert([])


@pytest.mark.skipif(sys.version_info < (3, 14), reason="t-strings need Python 3.14")
def test_t_strings_keep_their_values_as_parameters():
    user_id = 3
    # Written with eval so the file still parses on 3.13.
    template: Any = eval('t"SELECT * FROM users WHERE id = {user_id}"')
    assert sql(template).compile() == ("SELECT * FROM users WHERE id = ?", (user_id,))
    with pytest.raises(TypeError):
        sql(template, 1)
